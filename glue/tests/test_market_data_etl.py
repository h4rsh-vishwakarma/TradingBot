import pytest

pytest.importorskip("pyspark")

from pyspark.sql import SparkSession

from glue.jobs.market_data_etl import KLINE_SCHEMA, daily_aggregates, join_signals, reconcile, transform


@pytest.fixture(scope="session")
def spark():
    session = SparkSession.builder.master("local[2]").appName("etl-tests").getOrCreate()
    yield session
    session.stop()


def test_transform_quarantines_and_deduplicates(spark):
    valid = (1704067200000, 10, 12, 9, 11, 5, 1704067259999, 55, 3, 2, 22, "0", "BTCUSDT", "1m", "2024-01")
    invalid = (1704067260000, 10, 8, 9, 11, 5, 1704067319999, 55, 3, 2, 22, "0", "BTCUSDT", "1m", "2024-01")
    frame = spark.createDataFrame([valid, valid, invalid], KLINE_SCHEMA)
    curated, quarantine = transform(frame, "test-run")
    assert curated.count() == 1
    assert quarantine.count() == 1
    assert quarantine.first().quality_reason == "invalid_ohlc"


def test_reconciliation_rejects_loss():
    with pytest.raises(RuntimeError, match="Reconciliation failed"):
        reconcile(10, 8, 1, 0)


def test_daily_aggregation_and_optional_signal_join(spark):
    valid = (1704067200000, 10, 12, 9, 11, 5, 1704067259999, 55, 3, 2, 22, "0", "BTCUSDT", "1m", "2024-01")
    curated, _ = transform(spark.createDataFrame([valid], KLINE_SCHEMA), "test-run")
    assert daily_aggregates(curated).first().candle_count == 1
    signals = spark.createDataFrame(
        [("sig-1", "BTCUSDT", "2024-01-01T00:00:30Z", "BUY", "public-demo")],
        ["signal_id", "symbol", "signal_time", "side", "strategy"],
    )
    assert join_signals(curated, signals).first().open_time == 1704067200000
