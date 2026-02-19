#!/bin/bash
# Comprehensive Overnight Watchdog - Enhanced monitoring for unattended operation
# Deploy: chmod +x overnight_watchdog.sh && crontab -e
# Add: */2 * * * * /home/ubuntu/trading_bot/overnight_watchdog.sh >> /home/ubuntu/watchdog.log 2>&1

LOG_FILE="/home/ubuntu/watchdog.log"
BOT_DIR="/home/ubuntu/trading_bot"
ALERT_FILE="/home/ubuntu/critical_alerts.txt"

# Configuration
MAX_DECISION_AGE_SEC=180  # Alert if no decisions in 3 minutes
MAX_HEALTH_AGE_SEC=120    # Alert if no health events in 2 minutes
MIN_DISK_SPACE_GB=2       # Alert if disk space below 2GB
MAX_MEMORY_PCT=85         # Alert if memory usage above 85%
MAX_LOG_SIZE_MB=500       # Alert if any log file exceeds 500MB

echo "========================================" >> "$LOG_FILE"
echo "🔍 OVERNIGHT WATCHDOG: $(date '+%Y-%m-%d %H:%M:%S %Z')" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"

# Function to send critical alert
send_alert() {
    local message="$1"
    echo "🚨 CRITICAL ALERT: $message" >> "$LOG_FILE"
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $message" >> "$ALERT_FILE"
}

# 1. Check bot process
echo "1️⃣ Checking bot process..." >> "$LOG_FILE"
BOT_PID=$(pgrep -f "enhanced_trading_bot.py")
if [ -z "$BOT_PID" ]; then
    send_alert "Bot is NOT running - Attempting restart"
    cd "$BOT_DIR"
    rm -f /tmp/trading-bot.pid
    nohup "$BOT_DIR/venv/bin/python3" enhanced_trading_bot.py > /tmp/bot_restart.log 2>&1 &
    sleep 5
    
    NEW_PID=$(pgrep -f "enhanced_trading_bot.py")
    if [ -n "$NEW_PID" ]; then
        echo "✅ Bot restarted successfully (PID: $NEW_PID)" >> "$LOG_FILE"
    else
        send_alert "FAILED TO RESTART BOT - Manual intervention required"
        exit 1
    fi
else
    echo "✅ Bot running (PID: $BOT_PID)" >> "$LOG_FILE"
    
    # Check if bot is consuming excessive CPU (possible infinite loop)
    CPU_USAGE=$(ps -p "$BOT_PID" -o %cpu --no-headers | awk '{print int($1)}')
    if [ "$CPU_USAGE" -gt 90 ]; then
        echo "⚠️ High CPU usage: ${CPU_USAGE}%" >> "$LOG_FILE"
    fi
fi

# 2. Check recent decision activity
echo "2️⃣ Checking decision activity..." >> "$LOG_FILE"
if [ -f "$BOT_DIR/logs/events/decision.jsonl" ]; then
    LAST_DECISION=$(stat -c %Y "$BOT_DIR/logs/events/decision.jsonl" 2>/dev/null || stat -f %m "$BOT_DIR/logs/events/decision.jsonl" 2>/dev/null)
    CURRENT_TIME=$(date +%s)
    DECISION_AGE=$((CURRENT_TIME - LAST_DECISION))
    
    if [ "$DECISION_AGE" -gt "$MAX_DECISION_AGE_SEC" ]; then
        send_alert "No decisions in ${DECISION_AGE}s - Bot may be frozen"
    else
        echo "✅ Decision activity OK (last: ${DECISION_AGE}s ago)" >> "$LOG_FILE"
    fi
    
    # Count decisions in last hour
    RECENT_DECISIONS=$(tail -1000 "$BOT_DIR/logs/events/decision.jsonl" | wc -l)
    echo "📊 Recent decisions (last 1000 lines): $RECENT_DECISIONS" >> "$LOG_FILE"
else
    send_alert "decision.jsonl file not found"
fi

# 3. Check health events
echo "3️⃣ Checking health events..." >> "$LOG_FILE"
if [ -f "$BOT_DIR/logs/events/health.jsonl" ]; then
    LAST_HEALTH=$(tail -1 "$BOT_DIR/logs/events/health.jsonl" | jq -r '.ts' 2>/dev/null)
    if [ -n "$LAST_HEALTH" ] && [ "$LAST_HEALTH" != "null" ]; then
        LAST_HEALTH_SEC=$(date -d "$LAST_HEALTH" +%s 2>/dev/null || date -j -f "%Y-%m-%dT%H:%M:%S" "${LAST_HEALTH:0:19}" +%s 2>/dev/null)
        HEALTH_AGE=$(($(date +%s) - LAST_HEALTH_SEC))
        
        if [ "$HEALTH_AGE" -gt "$MAX_HEALTH_AGE_SEC" ]; then
            send_alert "No health events in ${HEALTH_AGE}s - Bot may be frozen"
        else
            echo "✅ Health events OK (last: ${HEALTH_AGE}s ago)" >> "$LOG_FILE"
            
            # Check critical flags from latest health event
            KILL_SWITCH=$(tail -1 "$BOT_DIR/logs/events/health.jsonl" | jq -r '.kill_switch_active' 2>/dev/null)
            DAILY_CAP=$(tail -1 "$BOT_DIR/logs/events/health.jsonl" | jq -r '.daily_cap_hit' 2>/dev/null)
            WS_CONNECTED=$(tail -1 "$BOT_DIR/logs/events/health.jsonl" | jq -r '.ws_connected' 2>/dev/null)
            
            [ "$KILL_SWITCH" = "true" ] && echo "⚠️ Kill switch is ACTIVE" >> "$LOG_FILE"
            [ "$DAILY_CAP" = "true" ] && echo "⚠️ Daily cap has been hit" >> "$LOG_FILE"
            [ "$WS_CONNECTED" = "false" ] && send_alert "WebSocket disconnected - No real-time data"
        fi
    fi
fi

# 4. Check disk space
echo "4️⃣ Checking disk space..." >> "$LOG_FILE"
DISK_AVAIL_GB=$(df -BG /home/ubuntu | tail -1 | awk '{print $4}' | sed 's/G//')
if [ "$DISK_AVAIL_GB" -lt "$MIN_DISK_SPACE_GB" ]; then
    send_alert "Low disk space: ${DISK_AVAIL_GB}GB remaining"
    echo "🧹 Cleaning old logs..." >> "$LOG_FILE"
    find "$BOT_DIR/logs" -name "*.gz" -mtime +7 -delete
    find "$BOT_DIR/logs" -name "*.log.*" -mtime +3 -delete
else
    echo "✅ Disk space OK: ${DISK_AVAIL_GB}GB available" >> "$LOG_FILE"
fi

# 5. Check memory usage
echo "5️⃣ Checking memory usage..." >> "$LOG_FILE"
MEMORY_PCT=$(free | grep Mem | awk '{print int($3/$2 * 100)}')
if [ "$MEMORY_PCT" -gt "$MAX_MEMORY_PCT" ]; then
    send_alert "High memory usage: ${MEMORY_PCT}%"
else
    echo "✅ Memory usage OK: ${MEMORY_PCT}%" >> "$LOG_FILE"
fi

# 6. Check log file sizes
echo "6️⃣ Checking log file sizes..." >> "$LOG_FILE"
LARGE_LOGS=$(find "$BOT_DIR/logs/events" -name "*.jsonl" -size +${MAX_LOG_SIZE_MB}M 2>/dev/null)
if [ -n "$LARGE_LOGS" ]; then
    echo "⚠️ Large log files detected:" >> "$LOG_FILE"
    echo "$LARGE_LOGS" >> "$LOG_FILE"
fi

# 7. Check scraper processes
echo "7️⃣ Checking data scrapers..." >> "$LOG_FILE"
OI_SCRAPER=$(pgrep -f "collect_oi_funding.py" | wc -l)
echo "   OI/Funding scraper: $OI_SCRAPER processes" >> "$LOG_FILE"

# 8. Verify cron jobs are active
echo "8️⃣ Checking cron status..." >> "$LOG_FILE"
if systemctl is-active --quiet cron 2>/dev/null || service cron status >/dev/null 2>&1; then
    echo "✅ Cron service is running" >> "$LOG_FILE"
else
    send_alert "Cron service is NOT running - Data collection may fail"
fi

# 9. Check for Python exceptions in recent logs
echo "9️⃣ Checking for exceptions..." >> "$LOG_FILE"
ERROR_COUNT=$(find "$BOT_DIR/logs/events" -name "*.jsonl" -mmin -10 -exec grep -i "exception\|traceback\|error" {} \; 2>/dev/null | wc -l)
if [ "$ERROR_COUNT" -gt 5 ]; then
    echo "⚠️ ${ERROR_COUNT} errors found in last 10 minutes" >> "$LOG_FILE"
fi

# 10. Summary
echo "" >> "$LOG_FILE"
echo "📊 SUMMARY:" >> "$LOG_FILE"
echo "   Bot PID: ${BOT_PID:-NOT RUNNING}" >> "$LOG_FILE"
echo "   Memory: ${MEMORY_PCT}%" >> "$LOG_FILE"
echo "   Disk: ${DISK_AVAIL_GB}GB free" >> "$LOG_FILE"
echo "   Decision age: ${DECISION_AGE:-N/A}s" >> "$LOG_FILE"
echo "   Health age: ${HEALTH_AGE:-N/A}s" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"

# Keep watchdog log manageable
if [ -f "$LOG_FILE" ]; then
    LOG_SIZE=$(stat -c %s "$LOG_FILE" 2>/dev/null || stat -f %z "$LOG_FILE" 2>/dev/null)
    if [ "$LOG_SIZE" -gt 5242880 ]; then  # 5MB
        tail -1000 "$LOG_FILE" > "${LOG_FILE}.tmp"
        mv "${LOG_FILE}.tmp" "$LOG_FILE"
    fi
fi

exit 0
