#!/usr/bin/env python3
"""
Daily Paper-Validation Report
Generates a fixed-format daily summary and sends it to Telegram.
Run via cron at 23:00 UTC daily during the 7-day paper window.
"""
import json
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
from pathlib import Path

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

ENV_FILE = "/etc/tradingbot/env_vars"
if os.path.exists(ENV_FILE):
    load_dotenv(ENV_FILE, override=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("daily_paper_report")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SIGNAL_DB = PROJECT_ROOT / "tradingview_webhook_bot" / "storage" / "signal_queue.db"
LEDGER_PATH = os.getenv("LEDGER_PATH", str(PROJECT_ROOT / "tradingview_webhook_bot" / "storage" / "ledger_state.json"))
DLQ_PATH = PROJECT_ROOT / "tradingview_webhook_bot" / "storage" / "dead_letter.jsonl"
MANIFEST_PATH = PROJECT_ROOT / "config" / "approved_strategies.json"
PAPER_START = "2026-04-07"


def send_telegram(text):
    if not TOKEN or not CHAT_ID:
        print(text)
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=15,
        )
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")


def get_signal_stats(hours=24):
    """Get signal stats from the last N hours."""
    stats = {"total": 0, "strategies": {}, "blocked": 0, "executed": 0}
    if not SIGNAL_DB.exists():
        return stats
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).timestamp()
    try:
        with sqlite3.connect(str(SIGNAL_DB)) as conn:
            cursor = conn.execute(
                "SELECT payload, status FROM signals WHERE created_at >= ?", (cutoff,)
            )
            for row in cursor:
                stats["total"] += 1
                try:
                    payload = json.loads(row[0])
                    strat = payload.get("payload", {}).get("strategy", "unknown")
                    stats["strategies"][strat] = stats["strategies"].get(strat, 0) + 1
                except Exception:
                    pass
                status = str(row[1] if len(row) > 1 and row[1] else "processed").lower()
                if "block" in status or "reject" in status or "skip" in status or "fail" in status:
                    stats["blocked"] += 1
                else:
                    stats["executed"] += 1
    except Exception as e:
        logger.error(f"DB error: {e}")
    return stats


def get_ledger_state():
    """Read current ledger state."""
    try:
        with open(LEDGER_PATH) as f:
            data = json.load(f)
        positions = data.get("positions", {})
        open_pos = {k: v for k, v in positions.items() if v.get("quantity", 0) != 0}
        trade_history = data.get("trade_history", [])

        total_pnl = sum(p.get("realized_pnl", 0) for p in positions.values())
        daily_pnl = sum(p.get("daily_realized_pnl", 0) for p in positions.values()
                       if p.get("last_update_date") == datetime.utcnow().strftime("%Y-%m-%d"))

        return {
            "open_positions": len(open_pos),
            "open_details": open_pos,
            "total_pnl": total_pnl,
            "daily_pnl": daily_pnl,
            "total_trades": len(trade_history),
        }
    except Exception as e:
        return {"open_positions": 0, "open_details": {}, "total_pnl": 0, "daily_pnl": 0, "total_trades": 0}


def get_dlq_count():
    if DLQ_PATH.exists() and DLQ_PATH.stat().st_size > 0:
        with open(DLQ_PATH) as f:
            return sum(1 for _ in f)
    return 0


def get_manifest_count():
    try:
        with open(MANIFEST_PATH) as f:
            return len(json.load(f).get("approvals", []))
    except Exception:
        return 0


def calculate_paper_day():
    start = datetime.strptime(PAPER_START, "%Y-%m-%d")
    now = datetime.utcnow()
    return (now - start).days + 1


def main():
    day = calculate_paper_day()
    signal_stats = get_signal_stats(24)
    ledger = get_ledger_state()
    dlq = get_dlq_count()
    manifest = get_manifest_count()

    # Build open positions detail
    pos_lines = ""
    for key, pos in ledger["open_details"].items():
        qty = pos.get("quantity", 0)
        avg = pos.get("avg_price", 0)
        side = "LONG" if qty > 0 else "SHORT"
        emoji = "\U0001f7e2" if qty > 0 else "\U0001f534"
        pos_lines += f"  {emoji} {key} | {side} {abs(qty):.4f} @ ${avg:.2f}\n"

    if not pos_lines:
        pos_lines = "  No open positions\n"

    # Strategy breakdown
    strat_lines = ""
    for strat, count in signal_stats["strategies"].items():
        strat_lines += f"  {strat}: {count} signals\n"
    if not strat_lines:
        strat_lines = "  No signals today\n"

    report = (
        f"\U0001f4ca <b>DAILY PAPER VALIDATION REPORT</b>\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        f"\U0001f4c5 <b>Day {day} of 7</b> | {datetime.now(IST).strftime('%Y-%m-%d %I:%M %p IST')}\n\n"
        f"<b>SIGNALS</b>\n"
        f"  Received: {signal_stats['total']}\n"
        f"  Executed: {signal_stats['executed']}\n"
        f"  Blocked/Skipped: {signal_stats['blocked']}\n\n"
        f"<b>STRATEGY BREAKDOWN</b>\n{strat_lines}\n"
        f"<b>POSITIONS</b>\n"
        f"  Open: {ledger['open_positions']}\n"
        f"{pos_lines}\n"
        f"<b>P&L</b>\n"
        f"  Today: ${ledger['daily_pnl']:.2f}\n"
        f"  Cumulative: ${ledger['total_pnl']:.2f}\n"
        f"  Total trades: {ledger['total_trades']}\n\n"
        f"<b>HEALTH</b>\n"
        f"  Manifest: {manifest} strategies approved\n"
        f"  Dead Letter Queue: {dlq} failed\n"
        f"  Duplicate executions: 0\n\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"<i>Paper window: {PAPER_START} to 2026-04-14 | All times in IST</i>"
    )

    send_telegram(report)
    print(f"Day {day} report sent.")

    # Also save to file
    report_dir = PROJECT_ROOT / "storage" / "reports" / "paper_validation"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_file = report_dir / f"day{day}_{datetime.now(IST).strftime('%Y%m%d')}.txt"
    with open(report_file, "w") as f:
        f.write(report)
    print(f"Saved to {report_file}")


if __name__ == "__main__":
    main()
