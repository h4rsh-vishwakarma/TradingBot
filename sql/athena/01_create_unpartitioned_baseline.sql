CREATE EXTERNAL TABLE IF NOT EXISTS trading_analytics.klines_unpartitioned (
  open_time BIGINT,
  open DECIMAL(38,18),
  high DECIMAL(38,18),
  low DECIMAL(38,18),
  close DECIMAL(38,18),
  volume DECIMAL(38,18),
  close_time BIGINT,
  quote_asset_volume DECIMAL(38,18),
  number_of_trades BIGINT,
  taker_buy_base_asset_volume DECIMAL(38,18),
  taker_buy_quote_asset_volume DECIMAL(38,18),
  event_time TIMESTAMP,
  event_date DATE,
  price_change DECIMAL(38,18),
  quote_volume DECIMAL(38,18),
  run_id STRING,
  ingested_at TIMESTAMP
)
STORED AS PARQUET
LOCATION 's3://REPLACE_BUCKET/curated-unpartitioned/klines/';
