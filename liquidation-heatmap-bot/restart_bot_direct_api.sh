#!/bin/bash
# Proper bot restart with direct API integration

echo "=== Bot Restart with Direct Binance API ==="
date

# Kill all existing bot processes
echo "Stopping existing bot processes..."
pkill -9 -f enhanced_trading_bot.py
sleep 2

# Remove PID lock
rm -f /tmp/trading-bot.pid
echo "PID lock removed"

# Start bot
echo "Starting bot with direct API integration..."
cd /home/ubuntu/trading_bot
nohup /home/ubuntu/trading_bot/venv/bin/python3 enhanced_trading_bot.py > bot.log 2>&1 &

sleep 3

# Check if started
if pgrep -f "enhanced_trading_bot.py" > /dev/null; then
    echo "✅ Bot started successfully (PID: $(pgrep -f 'enhanced_trading_bot.py'))"
    echo "Recent log entries:"
    tail -20 bot.log
else
    echo "❌ Bot failed to start"
    tail -50 bot.log
    exit 1
fi
