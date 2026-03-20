#!/bin/bash

# --- Paths ---
BOT_DIR="/home/ubuntu/tradingview_webhook_bot"
VENV_PYTHON="$BOT_DIR/venv/bin/python3"

echo "🚀 Starting Alpha Engine Automation Setup..."

# 1. Give permissions to all scripts
chmod +x $BOT_DIR/scripts/*.py
chmod +x $BOT_DIR/tradingview_webhook_bot/core/*.py

# 2. Backup old crontab
crontab -l > crontab_backup.txt
echo "✅ Old crontab backed up to crontab_backup.txt"

# 3. Create fresh Crontab entries
cat <<EOF > new_cron
# 1. Midnight: Fetch 3-Year Binance Data
0 0 * * * cd $BOT_DIR && $VENV_PYTHON scripts/fetch_historical_data.py >> $BOT_DIR/cron_logs.log 2>&1

# 2. 00:15 AM: Run Grid-Search Tournament
15 0 * * * cd $BOT_DIR && $VENV_PYTHON scripts/strategy_tournament.py >> $BOT_DIR/cron_logs.log 2>&1

# 3. 09:00 AM: Dispatch Winners to Telegram
0 9 * * * cd $BOT_DIR && $VENV_PYTHON tradingview_webhook_bot/core/script_vault.py >> $BOT_DIR/cron_logs.log 2>&1

# 4. Hourly: Heartbeat Scan
0 * * * * $VENV_PYTHON $BOT_DIR/scripts/auto_injector.py >> $BOT_DIR/auto_scan.log 2>&1
EOF

# 4. Install the new crontab
crontab new_cron
rm new_cron

echo "🎯 SUCCESS: 3-Year Alpha Loop is now ACTIVE."
echo "📈 Tournament runs at 00:15 AM | Dispatch at 09:00 AM"
