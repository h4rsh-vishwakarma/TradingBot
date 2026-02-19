#!/bin/bash
# Export backtest artifacts script
# Run every 6 hours via cron: 0 */6 * * *

cd /home/ubuntu/trading_bot || exit 1

echo "[$(date)] Starting backtest artifacts export..."

# Activate virtual environment
source /home/ubuntu/trading_bot/venv/bin/activate

# Run the exporter
python3 -c "from backtest_artifacts_exporter import export_all; export_all()" >> /home/ubuntu/export_artifacts.log 2>&1

echo "[$(date)] Export complete"
