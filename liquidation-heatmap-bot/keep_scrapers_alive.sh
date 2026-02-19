#!/bin/bash
# Keep data scrapers running
# Add to cron: */5 * * * * /home/ubuntu/trading_bot/keep_scrapers_alive.sh 

cd /home/ubuntu/trading_bot

# Function to check and restart process
check_and_start() {
    local script=$1
    local logfile=$2

    if ! pgrep -f "$script" > /dev/null; then
        echo "[$(date)] $script not running, starting..."
        # Use venv python for visual scraper (needs cv2)
        if [[ $script == *"visual"* ]]; then
            nohup /home/ubuntu/trading_bot/venv/bin/python3 "$script" >> "$logfile" 2>&1 &
        else
            nohup python3 "$script" >> "$logfile" 2>&1 &
        fi
        sleep 2
        if pgrep -f "$script" > /dev/null; then
            echo "[$(date)] $script started successfully"
        else
            echo "[$(date)] $script failed to start - check $logfile"
        fi
    fi
}

# Check each scraper
check_and_start "coinglass_visual_scraper.py" "logs/coinglass_scraper.log"
check_and_start "coinglass_lsr_scraper.py" "logs/lsr_scraper.log"
check_and_start "collect_oi_funding.py" "logs/oi_funding.log"

# Check bot
if ! pgrep -f "enhanced_trading_bot.py" > /dev/null; then
    echo "[$(date)] ALERT: Trading bot not running!"
    # Could add restart logic or notification here
fi
