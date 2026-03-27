#!/bin/bash
# Daily backup of critical bot data (ledger, queue, idempotency)
# Scheduled: 23:50 UTC daily via setup_cron.sh
# Retention: 7 days

BACKUP_DIR="/home/ubuntu/bot_backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
STORAGE_DIR="/home/ubuntu/tradingview_webhook_bot/tradingview_webhook_bot/storage"

mkdir -p "$BACKUP_DIR"

# Backup critical files only (not all storage)
zip -j "$BACKUP_DIR/bot_data_$TIMESTAMP.zip" \
    "$STORAGE_DIR/ledger_state.json" \
    "$STORAGE_DIR/signal_queue.db" \
    "$STORAGE_DIR/idempotency.db" \
    "$STORAGE_DIR/circuit_breaker_state.json" \
    2>/dev/null

# 7-day retention: keep only last 7 backups
ls -t "$BACKUP_DIR"/bot_data_*.zip 2>/dev/null | tail -n +8 | xargs rm -f

echo "✅ Backup completed at $TIMESTAMP (7-day retention)"
