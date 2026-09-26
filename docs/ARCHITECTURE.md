# Architecture decisions

## Dataset and grain

The primary source is Binance's public monthly spot-kline archive. One curated row represents one `(symbol, interval, open_time)` candlestick. Decimal market fields use `DECIMAL(38,18)` instead of binary floating point. Timestamps are normalized to UTC; both historical millisecond and newer microsecond archive epochs are accepted.

## Storage zones

| Zone | Format | Mutation policy | Purpose |
|---|---|---|---|
| `raw/` | CSV | Immutable | Replayable source of truth with SHA-256 metadata |
| `quarantine/` | JSON | Per-run overwrite | Invalid records plus rejection reason |
| `curated/klines/` | Parquet | Deterministic batch overwrite | Typed analytical data |
| `curated/daily_klines/` | Parquet | Dynamic partition overwrite | Daily OHLCV aggregates |
| `curated-unpartitioned/klines/` | Parquet | Per-run overwrite | Controlled Athena scan baseline |
| `athena-results/` | Athena output | Managed results | Query evidence |
| `spark-ui/` | Spark event logs | Append | Execution-plan evidence |

## Partition choice

Curated klines use `symbol/year/month`. Market analysis commonly filters by symbol and time range, so these keys allow Athena partition pruning without producing one tiny partition per day. `interval` remains a column because the initial data set uses a controlled interval; add it as a partition only after measurements show a material benefit and adequate file sizes.

## Idempotency and replay

Ingestion calculates SHA-256 and a deterministic run ID. Existing equal content is skipped; conflicting content at an immutable raw key is rejected. Glue isolates quarantine output by run ID and overwrites its deterministic target. Curated deduplication resolves repeated event identities using the latest close time. Re-running the same bounded input therefore preserves the logical row set.

An optional sanitized signal JSONL uses only `signal_id`, `symbol`, `signal_time`, `side`, and a non-private strategy label. The job left-joins each signal to its symbol's containing one-minute candle. Private payloads, account identifiers, order IDs, and credentials are outside the contract.

## Data-quality rules

- Required timestamps and OHLCV fields must parse.
- Close time cannot precede open time.
- Prices must be positive; high/low must contain open and close.
- Volume and trade counts cannot be negative.
- Every raw row must reconcile to curated, quarantine, or duplicate counts.

## Security and cost controls

The S3 bucket blocks public access, enables versioning and SSE-S3, and refuses automatic destruction. The Glue role is scoped to the project bucket and operational APIs. Athena enforces encrypted results, publishes metrics, and stops any single query after 10 GiB scanned. The default job uses two `G.1X` workers and a 30-minute timeout.
