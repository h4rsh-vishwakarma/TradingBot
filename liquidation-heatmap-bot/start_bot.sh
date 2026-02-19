#!/bin/bash
export EXPORT_BACKTEST_ARTIFACTS=1
cd /home/ubuntu/trading_bot
nohup venv/bin/python3 enhanced_trading_bot.py >> logs/bot.log 2>&1 &
echo " Bot started with PID \$!\
