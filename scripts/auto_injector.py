"""
Auto Injector — Hourly Heartbeat Scanner
Runs every hour via cron. Checks:
1. Webhook server is alive (port 5000)
2. Telegram listener is running
3. Signal queue is not stuck (DLQ check)
4. Tournament data is fresh (< 36 hours old)
5. Alerts on Telegram if anything is wrong
6. Sends a quiet-hour live confirmation if no signals arrived recently
"""

import logging
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(message)s')
logger = logging.getLogger("auto_injector")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

ENV_VARS_PATH = "/etc/tradingbot/env_vars"
if os.path.exists(ENV_VARS_PATH):
    load_dotenv(dotenv_path=ENV_VARS_PATH, override=True)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "5736858710")
SIGNAL_DB_PATH = PROJECT_ROOT / "tradingview_webhook_bot" / "storage" / "signal_queue.db"
QUIET_LOOKBACK_MINUTES = 60

def send_alert(message):
    if not TOKEN:
        logger.error("No TELEGRAM_BOT_TOKEN set")
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")

def check_webhook_server():
    try:
        r = requests.get("http://127.0.0.1:5000/health", timeout=5)
        return True
    except Exception:
        return False

def check_process(name):
    result = subprocess.run(["pgrep", "-f", name], capture_output=True, text=True)
    return len(result.stdout.strip()) > 0

def check_data_freshness():
    csv_path = PROJECT_ROOT / "storage" / "reports" / "tournament_winners.csv"
    if not csv_path.exists():
        return False, "tournament_winners.csv missing"
    mtime = datetime.fromtimestamp(csv_path.stat().st_mtime)
    age = datetime.now() - mtime
    if age > timedelta(hours=36):
        return False, f"Tournament data stale ({age.total_seconds()/3600:.0f}h old)"
    return True, f"Fresh ({age.total_seconds()/3600:.1f}h ago)"

def check_dlq():
    dlq_path = PROJECT_ROOT / "tradingview_webhook_bot" / "storage" / "dead_letter.jsonl"
    if dlq_path.exists() and dlq_path.stat().st_size > 0:
        with open(dlq_path) as f:
            count = sum(1 for _ in f)
        return count
    return 0


def check_recent_signal_activity(lookback_minutes=QUIET_LOOKBACK_MINUTES):
    if not SIGNAL_DB_PATH.exists():
        return False, f"signal_queue.db missing ({SIGNAL_DB_PATH})"

    lookback_seconds = max(1, int(lookback_minutes * 60))
    with sqlite3.connect(SIGNAL_DB_PATH) as conn:
        cursor = conn.execute(
            """
            SELECT COUNT(*), MAX(created_at)
            FROM signals
            WHERE created_at >= ?
            """,
            (datetime.utcnow().timestamp() - lookback_seconds,),
        )
        count, last_seen = cursor.fetchone()

    if count:
        last_seen_text = datetime.utcfromtimestamp(last_seen).strftime("%Y-%m-%d %H:%M:%S UTC")
        return True, f"{count} queued signal(s) in last {lookback_minutes}m (latest {last_seen_text})"

    return False, f"No queued signals in last {lookback_minutes}m"

def run_scan():
    issues = []
    status_lines = []

    # 1. Webhook Server (auto-restart if down)
    if check_webhook_server():
        status_lines.append("Webhook Server: UP")
    else:
        # Auto-restart webhook before alerting
        import subprocess
        subprocess.run(["sudo", "systemctl", "restart", "trading_webhook"], timeout=15)
        import time
        time.sleep(5)
        if check_webhook_server():
            status_lines.append("Webhook Server: AUTO-RESTARTED (was down, now UP)")
        else:
            status_lines.append("Webhook Server: DOWN (restart failed)")
            issues.append("Webhook server not responding on port 5000 (auto-restart failed)")

    # 2. Telegram Listener
    if check_process("telegram_backtest_bot") or check_process("orchestrator"):
        status_lines.append("Telegram & Orchestrator: UP")
    else:
        status_lines.append("Telegram & Orchestrator: DOWN")
        issues.append("Telegram bot or Orchestrator not running")

    # 3. Data Freshness
    fresh, detail = check_data_freshness()
    status_lines.append(f"Tournament Data: {detail}")
    if not fresh:
        issues.append(f"Tournament data issue: {detail}")

    # 4. DLQ
    dlq_count = check_dlq()
    if dlq_count > 0:
        status_lines.append(f"Dead Letter Queue: {dlq_count} failed signals")
        issues.append(f"DLQ has {dlq_count} unprocessed signals")
    else:
        status_lines.append("Dead Letter Queue: Clean")

    # 5. Recent live activity
    has_recent_signals, activity_detail = check_recent_signal_activity()
    status_lines.append(f"Recent Signals: {activity_detail}")
    if "missing" in activity_detail:
        issues.append(f"Signal activity check issue: {activity_detail}")

    # Log everything
    logger.info("Heartbeat scan complete: " + " | ".join(status_lines))

    # Alert only if issues found
    if issues:
        msg = (
            "<b>HOURLY HEARTBEAT ALERT</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            + "\n".join(f"<b>{i+1}.</b> {issue}" for i, issue in enumerate(issues))
            + f"\n━━━━━━━━━━━━━━━━━━\n"
            f"<i>{datetime.now().strftime('%Y-%m-%d %H:%M')}</i>"
        )
        send_alert(msg)
    else:
        if has_recent_signals:
            logger.info("All systems nominal. Recent signals exist, so no extra heartbeat alert needed.")
        else:
            msg = (
                "<b>HOURLY LIVE CONFIRMATION</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "<b>Status:</b> Bot is live and healthy.\n"
                f"<b>Signals:</b> {activity_detail}\n"
                f"<b>Tournament:</b> {detail}\n"
                "<b>Queue:</b> Dead Letter Queue clean\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"<i>{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</i>"
            )
            send_alert(msg)
            logger.info("All systems nominal. Quiet-hour confirmation alert sent.")

if __name__ == "__main__":
    run_scan()
