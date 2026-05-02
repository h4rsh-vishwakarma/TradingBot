"""
Auto Injector — Hourly Heartbeat Scanner
Runs every hour via cron. Checks:
1. Webhook server is alive (port 5000)
2. Orchestrator service is running
3. Dashboard is reachable
4. Tournament data is fresh
5. Dead letter queue is clean
6. TradingView feed is active, quiet, or potentially stuck
"""

import logging
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
from pathlib import Path

import requests
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(message)s")
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
TRADINGVIEW_STUCK_MINUTES = 360


def send_alert(message):
    if not TOKEN:
        logger.error("No TELEGRAM_BOT_TOKEN set")
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")


def check_http_endpoint(url: str, timeout: int = 5) -> bool:
    try:
        response = requests.get(url, timeout=timeout)
        return response.ok
    except Exception:
        return False


def check_webhook_server():
    return check_http_endpoint("http://127.0.0.1:5000/health", timeout=5)


def check_dashboard_server():
    return check_http_endpoint("http://127.0.0.1:8501", timeout=5)


def check_process(name):
    result = subprocess.run(["pgrep", "-f", name], capture_output=True, text=True, check=False)
    return len(result.stdout.strip()) > 0


def check_systemd_service(service_name: str, process_fallback: str = "") -> bool:
    result = subprocess.run(["systemctl", "is-active", service_name], capture_output=True, text=True, check=False)
    if result.stdout.strip() == "active":
        return True
    return bool(process_fallback and check_process(process_fallback))


def check_data_freshness():
    csv_path = PROJECT_ROOT / "storage" / "reports" / "tournament_winners.csv"
    if not csv_path.exists():
        return False, "tournament_winners.csv missing"
    mtime = datetime.fromtimestamp(csv_path.stat().st_mtime)
    age = datetime.now() - mtime
    if age > timedelta(hours=36):
        return False, f"Stale ({age.total_seconds() / 3600:.0f}h old)"
    return True, f"Fresh ({age.total_seconds() / 3600:.1f}h ago)"


def check_dlq():
    dlq_path = PROJECT_ROOT / "tradingview_webhook_bot" / "storage" / "dead_letter.jsonl"
    if dlq_path.exists() and dlq_path.stat().st_size > 0:
        with open(dlq_path, encoding="utf-8", errors="replace") as handle:
            count = sum(1 for _ in handle)
        return count
    return 0


def _get_signal_activity_snapshot():
    if not SIGNAL_DB_PATH.exists():
        return {"ok": False, "detail": f"signal_queue.db missing ({SIGNAL_DB_PATH})", "last_seen": None, "count": 0}

    lookback_seconds = max(1, int(QUIET_LOOKBACK_MINUTES * 60))
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
        return {
            "ok": True,
            "detail": f"{count} bot-visible signal(s) in last {QUIET_LOOKBACK_MINUTES}m (latest {last_seen_text})",
            "last_seen": last_seen,
            "count": count,
        }

    return {
        "ok": False,
        "detail": f"No bot-visible signals in last {QUIET_LOOKBACK_MINUTES}m",
        "last_seen": None,
        "count": 0,
    }


def check_recent_signal_activity(lookback_minutes=QUIET_LOOKBACK_MINUTES):
    snapshot = _get_signal_activity_snapshot()
    return snapshot["ok"], snapshot["detail"]


def assess_tradingview_feed():
    snapshot = _get_signal_activity_snapshot()
    if "missing" in snapshot["detail"]:
        return "down", snapshot["detail"]
    if snapshot["ok"]:
        return "active", snapshot["detail"]

    if not SIGNAL_DB_PATH.exists():
        return "down", snapshot["detail"]

    with sqlite3.connect(SIGNAL_DB_PATH) as conn:
        cursor = conn.execute("SELECT MAX(created_at) FROM signals")
        last_seen = cursor.fetchone()[0]

    if not last_seen:
        return "warn", "No bot-visible TradingView signals recorded yet"

    age_minutes = int((datetime.utcnow().timestamp() - last_seen) / 60)
    last_seen_text = datetime.utcfromtimestamp(last_seen).strftime("%Y-%m-%d %H:%M:%S UTC")
    if age_minutes >= TRADINGVIEW_STUCK_MINUTES:
        return "down", (
            f"Signal pipeline may be stuck: no signals reached the bot for {age_minutes}m "
            f"(last bot-visible signal {last_seen_text}). Verify TradingView alerts, webhook delivery, and queue ingestion."
        )
    return "warn", (
        f"No signals reached the bot in last {QUIET_LOOKBACK_MINUTES}m "
        f"(last bot-visible signal {last_seen_text}). This may be quiet market or an upstream alert issue."
    )


def _status_line(icon: str, label: str, detail: str) -> str:
    return f"{icon} <b>{label}:</b> {detail}"


def _build_message(title: str, overall_status: str, checklist_lines: list[str], issues: list[str]) -> str:
    lines = [
        f"<b>{title}</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"<b>Status:</b> {overall_status}",
        "",
        *checklist_lines,
    ]
    if issues:
        lines.extend(
            [
                "",
                "<b>Issues:</b>",
                *[f"{idx}. {issue}" for idx, issue in enumerate(issues, start=1)],
            ]
        )
    lines.extend(
        [
            "━━━━━━━━━━━━━━━━━━",
            f"<i>{datetime.now(IST).strftime('%Y-%m-%d %I:%M %p IST')}</i>",
        ]
    )
    return "\n".join(lines)


def run_scan():
    issues = []
    checklist_lines = []

    webhook_up = check_webhook_server()
    if webhook_up:
        checklist_lines.append(_status_line("✅", "Webhook", "UP"))
    else:
        subprocess.run(["sudo", "systemctl", "restart", "trading_webhook"], timeout=15, check=False)
        time.sleep(5)
        if check_webhook_server():
            checklist_lines.append(_status_line("⚠️", "Webhook", "AUTO-RESTARTED (was down, now UP)"))
        else:
            checklist_lines.append(_status_line("❌", "Webhook", "DOWN (restart failed)"))
            issues.append("Webhook server not responding on port 5000")

    orchestrator_up = check_systemd_service("trading_orchestrator", process_fallback="orchestrator.py")
    if orchestrator_up:
        checklist_lines.append(_status_line("✅", "Orchestrator", "RUNNING"))
    else:
        checklist_lines.append(_status_line("❌", "Orchestrator", "DOWN"))
        issues.append("Orchestrator service is not running")

    dashboard_up = check_dashboard_server()
    if dashboard_up:
        checklist_lines.append(_status_line("✅", "Dashboard", "UP"))
    else:
        checklist_lines.append(_status_line("❌", "Dashboard", "DOWN"))
        issues.append("Dashboard on port 8501 is not responding")

    fresh, tournament_detail = check_data_freshness()
    if fresh:
        checklist_lines.append(_status_line("✅", "Tournament", tournament_detail))
    else:
        checklist_lines.append(_status_line("❌", "Tournament", tournament_detail))
        issues.append(f"Tournament data issue: {tournament_detail}")

    dlq_count = check_dlq()
    if dlq_count > 0:
        checklist_lines.append(_status_line("❌", "Dead Letter Queue", f"{dlq_count} failed signals"))
        issues.append(f"DLQ has {dlq_count} unprocessed signals")
    else:
        checklist_lines.append(_status_line("✅", "Dead Letter Queue", "Clean"))

    has_recent_signals, signal_detail = check_recent_signal_activity()
    feed_status, feed_detail = assess_tradingview_feed()
    if feed_status == "active":
        checklist_lines.append(_status_line("✅", "Signal Ingestion", feed_detail))
    elif feed_status == "warn":
        checklist_lines.append(_status_line("⚠️", "Signal Ingestion", feed_detail))
    else:
        checklist_lines.append(_status_line("❌", "Signal Ingestion", feed_detail))
        issues.append(feed_detail)

    if "missing" in signal_detail:
        checklist_lines.append(_status_line("❌", "Signal Queue DB", signal_detail))
        issues.append(f"Signal activity check issue: {signal_detail}")
    elif has_recent_signals:
        checklist_lines.append(_status_line("✅", "Signal Queue", signal_detail))
    else:
        checklist_lines.append(_status_line("⚠️", "Signal Queue", signal_detail))

    logger.info("Heartbeat scan complete: " + " | ".join(line.replace("<b>", "").replace("</b>", "") for line in checklist_lines))

    if issues:
        send_alert(_build_message("HOURLY HEARTBEAT ALERT", "Attention needed", checklist_lines, issues))
    else:
        send_alert(_build_message("HOURLY LIVE CONFIRMATION", "Bot is live and healthy", checklist_lines, []))
        logger.info("Infrastructure nominal (services up, DLQ clean). Full governance verdict in hourly_heartbeat_report. Hourly checklist sent.")


if __name__ == "__main__":
    run_scan()
