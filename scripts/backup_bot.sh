#!/bin/bash
BACKUP_DIR="/home/ubuntu/bot_backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
SOURCE_DIR="/home/ubuntu/tradingview_webhook_bot/tradingview_webhook_bot/storage"

# Create a zip of the storage folder
zip -r $BACKUP_DIR/bot_data_$TIMESTAMP.zip $SOURCE_DIR

# Keep only last 10 backups to save space
ls -t $BACKUP_DIR/bot_data_*.zip | tail -n +11 | xargs rm -f

echo "Backup completed at $TIMESTAMP"
