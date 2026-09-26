-- Correctness and reconciliation
SELECT symbol, year, month, count(*) AS rows
FROM trading_analytics.klines
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3;

-- Partition-pruned analytical query. Record DataScannedInBytes from Athena execution details.
SELECT symbol, event_date, avg(close) AS avg_close, sum(quote_volume) AS quote_volume
FROM trading_analytics.klines
WHERE symbol = 'BTCUSDT' AND year = 2024 AND month = 1
GROUP BY 1, 2
ORDER BY 2;

-- Baseline for the same result without partition pruning.
SELECT 'BTCUSDT' AS symbol, event_date, avg(close) AS avg_close, sum(quote_volume) AS quote_volume
FROM trading_analytics.klines_unpartitioned
WHERE event_date BETWEEN DATE '2024-01-01' AND DATE '2024-01-31'
GROUP BY 1, 2
ORDER BY 2;
