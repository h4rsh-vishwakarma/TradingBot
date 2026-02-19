#!/bin/bash
# Bot Health Monitor - Ensures bot stays running overnight
# Add to crontab: */5 * * * * /home/ubuntu/trading_bot/monitor_bot_health.sh >> /home/ubuntu/bot_monitor.log 2>&1

LOG_FILE="/home/ubuntu/bot_monitor.log"
BOT_DIR="/home/ubuntu/trading_bot"
BOT_SCRIPT="enhanced_trading_bot.py"
BOT_LOG="$BOT_DIR/bot.log"
PID_FILE="/tmp/trading-bot.pid"

echo "=== Bot Health Check: $(date) ===" >> "$LOG_FILE"

# Check if bot process is running
if pgrep -f "$BOT_SCRIPT" > /dev/null; then
    echo "✅ Bot is running (PID: $(pgrep -f "$BOT_SCRIPT"))" >> "$LOG_FILE"
    
    # Check if bot log has recent activity (within last 10 minutes)
    if [ -f "$BOT_LOG" ]; then
        LAST_LOG_TIME=$(stat -c %Y "$BOT_LOG" 2>/dev/null || stat -f %m "$BOT_LOG" 2>/dev/null)
        CURRENT_TIME=$(date +%s)
        TIME_DIFF=$((CURRENT_TIME - LAST_LOG_TIME))
        
        if [ $TIME_DIFF -gt 600 ]; then
            echo "⚠️ Bot log hasn't been updated in $TIME_DIFF seconds - Bot may be frozen" >> "$LOG_FILE"
            echo "🔄 Restarting frozen bot..." >> "$LOG_FILE"
            pkill -9 -f "$BOT_SCRIPT"
            sleep 2
            rm -f "$PID_FILE"
            cd "$BOT_DIR"
            nohup "$BOT_DIR/venv/bin/python3" "$BOT_SCRIPT" > "$BOT_LOG" 2>&1 &
            echo "✅ Bot restarted after freeze detection" >> "$LOG_FILE"
        fi
    fi
else
    echo "❌ Bot is NOT running - Starting bot..." >> "$LOG_FILE"
    rm -f "$PID_FILE"
    cd "$BOT_DIR"
    nohup "$BOT_DIR/venv/bin/python3" "$BOT_SCRIPT" > "$BOT_LOG" 2>&1 &
    sleep 3
    
    if pgrep -f "$BOT_SCRIPT" > /dev/null; then
        echo "✅ Bot started successfully (PID: $(pgrep -f "$BOT_SCRIPT"))" >> "$LOG_FILE"
    else
        echo "❌ CRITICAL: Bot failed to start! Check $BOT_LOG" >> "$LOG_FILE"
        tail -50 "$BOT_LOG" >> "$LOG_FILE"
    fi
fi

# Check scraper health
echo "--- Scraper Health Check ---" >> "$LOG_FILE"

# Check OI/Funding scraper
if pgrep -f "collect_oi_funding.py" > /dev/null; then
    echo "✅ OI/Funding scraper: Running" >> "$LOG_FILE"
else
    echo "⚠️ OI/Funding scraper: Not running (controlled by cron)" >> "$LOG_FILE"
fi

# Check Coinglass scraper
if pgrep -f "coinglass_visual_scraper.py" > /dev/null; then
    echo "✅ Coinglass scraper: Running" >> "$LOG_FILE"
else
    echo "⚠️ Coinglass scraper: Not running (controlled by cron)" >> "$LOG_FILE"
fi

# Check LSR scraper
if pgrep -f "binance_lsr_scraper.py" > /dev/null; then
    echo "✅ LSR scraper: Running" >> "$LOG_FILE"
else
    echo "⚠️ LSR scraper: Not running (controlled by cron)" >> "$LOG_FILE"
fi

echo "===========================================\n" >> "$LOG_FILE"
