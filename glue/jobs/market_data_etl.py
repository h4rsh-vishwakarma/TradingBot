"""AWS Glue 5.0 job for validated, deduplicated Binance kline analytics data."""

from __future__ import annotations

import json
import sys
import time

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F
from pyspark.sql.types import DecimalType, LongType, StringType, StructField, StructType

RAW_SCHEMA = StructType(
    [
        StructField("open_time", LongType()),
        StructField("open", DecimalType(38, 18)),
        StructField("high", DecimalType(38, 18)),
        StructField("low", DecimalType(38, 18)),
        StructField("close", DecimalType(38, 18)),
        StructField("volume", DecimalType(38, 18)),
        StructField("close_time", LongType()),
        StructField("quote_asset_volume", DecimalType(38, 18)),
        StructField("number_of_trades", LongType()),
        StructField("taker_buy_base_asset_volume", DecimalType(38, 18)),
        StructField("taker_buy_quote_asset_volume", DecimalType(38, 18)),
        StructField("ignore", StringType()),
    ]
)
KLINE_SCHEMA = StructType(
    list(RAW_SCHEMA.fields)
    + [StructField("symbol", StringType()), StructField("interval", StringType()), StructField("source_month", StringType())]
)


def _timestamp_seconds(column):
    """Binance spot archives use milliseconds historically and microseconds since 2025."""
    return F.when(column >= F.lit(10**14), column / F.lit(1_000_000)).otherwise(
        column / F.lit(1_000)
    )


def with_quality_reason(frame: DataFrame) -> DataFrame:
    required = ["open_time", "close_time", "open", "high", "low", "close", "volume"]
    missing = F.greatest(*[F.col(name).isNull().cast("int") for name in required]) == 1
    return frame.withColumn(
        "quality_reason",
        F.when(missing, "schema_or_type_error")
        .when((F.col("open_time") < 0) | (F.col("close_time") < F.col("open_time")), "invalid_timestamp_range")
        .when(
            (F.least("open", "high", "low", "close") <= 0)
            | (F.col("low") > F.least("open", "close"))
            | (F.col("high") < F.greatest("open", "close")),
            "invalid_ohlc",
        )
        .when((F.col("high") < F.col("low")) | (F.col("volume") < 0) | (F.col("number_of_trades") < 0), "negative_or_inverted_metric"),
    )


def transform(frame: DataFrame, run_id: str) -> tuple[DataFrame, DataFrame]:
    checked = with_quality_reason(frame)
    quarantine = checked.filter(F.col("quality_reason").isNotNull()).withColumn("run_id", F.lit(run_id))
    valid = checked.filter(F.col("quality_reason").isNull()).drop("quality_reason")
    normalized = (
        valid.withColumn(
            "event_time", F.timestamp_seconds(_timestamp_seconds(F.col("open_time")).cast("long"))
        )
        .withColumn("event_date", F.to_date("event_time"))
        .withColumn("year", F.year("event_time"))
        .withColumn("month", F.month("event_time"))
        .withColumn("price_change", F.col("close") - F.col("open"))
        .withColumn("quote_volume", F.col("quote_asset_volume"))
        .withColumn("run_id", F.lit(run_id))
        .withColumn("ingested_at", F.current_timestamp())
    )
    ranking = Window.partitionBy("symbol", "interval", "open_time").orderBy(
        F.col("close_time").desc(), F.col("run_id").desc()
    )
    curated = normalized.withColumn("_rank", F.row_number().over(ranking)).filter("_rank = 1").drop("_rank", "ignore")
    return curated, quarantine


def daily_aggregates(curated: DataFrame) -> DataFrame:
    """Build one analytical row per market/day from the curated candle grain."""
    opening = Window.partitionBy("symbol", "interval", "event_date").orderBy("event_time")
    closing = Window.partitionBy("symbol", "interval", "event_date").orderBy(F.col("event_time").desc())
    ranked = curated.withColumn("day_open", F.first("open").over(opening)).withColumn(
        "day_close", F.first("close").over(closing)
    )
    return ranked.groupBy("symbol", "interval", "event_date", "year", "month").agg(
        F.first("day_open").alias("open"),
        F.max("high").alias("high"),
        F.min("low").alias("low"),
        F.first("day_close").alias("close"),
        F.sum("volume").alias("base_volume"),
        F.sum("quote_volume").alias("quote_volume"),
        F.sum("number_of_trades").alias("number_of_trades"),
        F.count(F.lit(1)).alias("candle_count"),
    )


def join_signals(curated: DataFrame, signals: DataFrame) -> DataFrame:
    """Attach sanitized signals to their symbol's containing candle (optional input)."""
    clean_signals = signals.select(
        "signal_id",
        F.upper("symbol").alias("signal_symbol"),
        F.to_timestamp("signal_time").alias("signal_time"),
        "side",
        "strategy",
    )
    return clean_signals.join(
        curated,
        (clean_signals.signal_symbol == curated.symbol)
        & (clean_signals.signal_time >= curated.event_time)
        & (clean_signals.signal_time < F.expr("event_time + INTERVAL 1 MINUTE")),
        "left",
    ).drop("signal_symbol")


def read_raw(spark: SparkSession, input_path: str) -> DataFrame:
    raw = (
        spark.read.option("header", "false")
        .option("mode", "PERMISSIVE")
        .schema(RAW_SCHEMA)
        .csv(input_path)
    )
    path = F.input_file_name()
    return (
        raw.withColumn("symbol", F.regexp_extract(path, r"symbol=([^/\\]+)", 1))
        .withColumn("interval", F.regexp_extract(path, r"interval=([^/\\]+)", 1))
        .withColumn("source_month", F.regexp_extract(path, r"month=([^/\\]+)", 1))
    )


def reconcile(raw_count: int, curated_count: int, quarantined_count: int, duplicate_count: int) -> None:
    if raw_count != curated_count + quarantined_count + duplicate_count:
        raise RuntimeError(
            f"Reconciliation failed: raw={raw_count}, curated={curated_count}, "
            f"quarantine={quarantined_count}, duplicates={duplicate_count}"
        )


def run(
    spark: SparkSession,
    input_path: str,
    curated_path: str,
    baseline_path: str,
    daily_path: str,
    quarantine_path: str,
    run_id: str,
    signals_path: str | None = None,
    enriched_path: str | None = None,
    logger=print,
) -> dict:
    started = time.perf_counter()
    raw = read_raw(spark, input_path).cache()
    curated, quarantine = transform(raw, run_id)
    raw_count = raw.count()
    quarantine_count = quarantine.count()
    curated_count = curated.count()
    valid_count = raw_count - quarantine_count
    duplicate_count = valid_count - curated_count
    reconcile(raw_count, curated_count, quarantine_count, duplicate_count)
    curated.explain(mode="formatted")

    spark.conf.set("spark.sql.sources.partitionOverwriteMode", "dynamic")
    quarantine.write.mode("overwrite").json(f"{quarantine_path}/run_id={run_id}")
    curated.write.mode("overwrite").parquet(baseline_path)
    (
        curated.repartition("symbol", "year", "month")
        .write.mode("overwrite")
        .partitionBy("symbol", "year", "month")
        .parquet(curated_path)
    )
    (
        daily_aggregates(curated)
        .repartition("symbol", "year", "month")
        .write.mode("overwrite")
        .partitionBy("symbol", "year", "month")
        .parquet(daily_path)
    )
    if signals_path and enriched_path:
        signals = spark.read.option("multiLine", "false").json(signals_path)
        join_signals(curated, signals).write.mode("overwrite").parquet(
            f"{enriched_path}/run_id={run_id}"
        )
    metrics = {
        "run_id": run_id,
        "raw_rows": raw_count,
        "curated_rows": curated_count,
        "quarantined_rows": quarantine_count,
        "duplicate_rows": duplicate_count,
        "duration_seconds": round(time.perf_counter() - started, 3),
    }
    logger(json.dumps({"event": "reconciliation", **metrics}, sort_keys=True))
    raw.unpersist()
    return metrics


def main() -> None:
    from awsglue.context import GlueContext
    from awsglue.job import Job
    from awsglue.utils import getResolvedOptions
    from pyspark.context import SparkContext

    names = [
        "JOB_NAME",
        "INPUT_PATH",
        "CURATED_PATH",
        "BASELINE_PATH",
        "DAILY_PATH",
        "QUARANTINE_PATH",
        "RUN_ID",
    ]
    args = getResolvedOptions(sys.argv, names)
    optional = getResolvedOptions(sys.argv, [name for name in ("SIGNALS_PATH", "ENRICHED_PATH") if f"--{name}" in sys.argv])
    glue_context = GlueContext(SparkContext.getOrCreate())
    job = Job(glue_context)
    job.init(args["JOB_NAME"], args)
    run(
        glue_context.spark_session,
        args["INPUT_PATH"],
        args["CURATED_PATH"],
        args["BASELINE_PATH"],
        args["DAILY_PATH"],
        args["QUARANTINE_PATH"],
        args["RUN_ID"],
        optional.get("SIGNALS_PATH"),
        optional.get("ENRICHED_PATH"),
        glue_context.get_logger().info,
    )
    job.commit()


if __name__ == "__main__":
    main()
