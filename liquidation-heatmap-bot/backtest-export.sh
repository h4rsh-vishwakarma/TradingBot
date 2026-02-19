#!/bin/bash
# Backtest Artifact Exporter - Cron Job Script
# Schedule: Every 6 hours (00:00, 06:00, 12:00, 18:00 UTC)
# Usage: Add to crontab: 0 */6 * * * /home/ubuntu/trading_bot/backtest-export.sh

set -e

TRADING_BOT_DIR="/home/ubuntu/trading_bot"
LOG_FILE="/home/ubuntu/trading_bot/logs/backtest_export.log"
EVENTS_DIR="/home/ubuntu/trading_bot/logs/events"
OUT_DIR="/home/ubuntu/trading_bot/backtest_artifacts"
INITIAL_EQUITY=1000.0

cd "$TRADING_BOT_DIR"

# Extract current run_id from latest health event
RUN_ID=$(tail -1 "$EVENTS_DIR/health.jsonl" | jq -r '.run_id // "unknown"')

echo "====================================================================" >> "$LOG_FILE"
echo "Backtest Export - $(date -u +"%Y-%m-%d %H:%M:%S UTC")" >> "$LOG_FILE"
echo "Run ID: $RUN_ID" >> "$LOG_FILE"
echo "====================================================================" >> "$LOG_FILE"

# Run exporter
source venv/bin/activate
python3 backtest_artifacts_exporter.py \
    --run-id "$RUN_ID" \
    --events-dir "$EVENTS_DIR" \
    --out-dir "$OUT_DIR" \
    --initial-equity "$INITIAL_EQUITY" \
    >> "$LOG_FILE" 2>&1

# Cleanup old artifacts (keep last 7 days)
find "$OUT_DIR" -type f -name "*.csv" -mtime +7 -delete

echo "Export completed successfully" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"
