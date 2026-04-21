#!/usr/bin/env python3
"""
Daily Reconciler Incident Summary
Checks orchestrator logs for drift events and summarizes by severity.
Run via cron at 23:05 UTC daily during paper window.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
from pathlib import Path

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]

ENV_FILE = "/etc/tradingbot/env_vars"
if os.path.exists(ENV_FILE):
    load_dotenv(ENV_FILE, override=True)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


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
        print(f"Telegram failed: {e}")


def get_journal_lines(service, hours=24):
    """Get journalctl lines from the last N hours."""
    try:
        result = subprocess.run(
            ["journalctl", "-u", service, "--no-pager", f"--since={hours} hours ago"],
            capture_output=True, text=True, timeout=30,
        )
        return result.stdout.splitlines()
    except Exception:
        return []


def main():
    lines = get_journal_lines("trading_orchestrator", hours=24)

    # Count incidents by category
    counts = {
        "SYNCED": 0,
        "UNEXPECTED_FLAT": 0,
        "UNEXPECTED_OPEN": 0,
        "SIDE_MISMATCH": 0,
        "POSITION_MISMATCH": 0,
        "auto_synced": 0,
        "sl_placed": 0,
        "sl_failed": 0,
        "tp_placed": 0,
        "tp_failed": 0,
        "approval_blocked": 0,
        "dedup_blocked": 0,
        "cooldown_blocked": 0,
        "candle_lock_blocked": 0,
        "circuit_breaker": 0,
        "execution_success": 0,
        "execution_failed": 0,
    }

    for line in lines:
        lower = line.lower()
        if "unexpected_flat" in lower: counts["UNEXPECTED_FLAT"] += 1
        elif "unexpected_open" in lower: counts["UNEXPECTED_OPEN"] += 1
        elif "side_mismatch" in lower: counts["SIDE_MISMATCH"] += 1
        elif "position_mismatch" in lower: counts["POSITION_MISMATCH"] += 1
        if "auto-synced" in lower or "auto_synced" in lower: counts["auto_synced"] += 1
        if "sl placed" in lower: counts["sl_placed"] += 1
        if "sl failed" in lower or "sl placement failed" in lower: counts["sl_failed"] += 1
        if "tp placed" in lower: counts["tp_placed"] += 1
        if "tp failed" in lower: counts["tp_failed"] += 1
        if "approval blocked" in lower: counts["approval_blocked"] += 1
        if "duplicate signal blocked" in lower: counts["dedup_blocked"] += 1
        if "cooldown block" in lower or "cooldown active" in lower: counts["cooldown_blocked"] += 1
        if "candle lock" in lower and "block" in lower: counts["candle_lock_blocked"] += 1
        if "circuit breaker" in lower and "trip" in lower: counts["circuit_breaker"] += 1
        if "order success" in lower or "execution_res" in lower and "success" in lower: counts["execution_success"] += 1
        if "execution failure" in lower: counts["execution_failed"] += 1

    # Determine severity
    critical = counts["SIDE_MISMATCH"] + counts["circuit_breaker"]
    high = counts["UNEXPECTED_FLAT"] + counts["UNEXPECTED_OPEN"] + counts["sl_failed"] + counts["tp_failed"] + counts["execution_failed"]
    medium = counts["POSITION_MISMATCH"]
    ok = critical == 0 and high == 0

    severity_emoji = "\u2705" if ok else ("\u26a0\ufe0f" if critical == 0 else "\U0001f6a8")

    report = (
        f"{severity_emoji} <b>DAILY RECONCILER & INCIDENT SUMMARY</b>\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        f"<b>DRIFT EVENTS (24h)</b>\n"
        f"  SIDE_MISMATCH (CRITICAL): {counts['SIDE_MISMATCH']}\n"
        f"  UNEXPECTED_FLAT (HIGH): {counts['UNEXPECTED_FLAT']}\n"
        f"  UNEXPECTED_OPEN (HIGH): {counts['UNEXPECTED_OPEN']}\n"
        f"  POSITION_MISMATCH (MEDIUM): {counts['POSITION_MISMATCH']}\n"
        f"  Auto-synced corrections: {counts['auto_synced']}\n\n"
        f"<b>EXECUTION (24h)</b>\n"
        f"  Trades executed: {counts['execution_success']}\n"
        f"  Execution failures: {counts['execution_failed']}\n"
        f"  SL placed: {counts['sl_placed']} | failed: {counts['sl_failed']}\n"
        f"  TP placed: {counts['tp_placed']} | failed: {counts['tp_failed']}\n\n"
        f"<b>GATE BLOCKS (24h)</b>\n"
        f"  Approval manifest: {counts['approval_blocked']}\n"
        f"  Dedup: {counts['dedup_blocked']}\n"
        f"  Cooldown: {counts['cooldown_blocked']}\n"
        f"  Candle lock: {counts['candle_lock_blocked']}\n"
        f"  Circuit breaker trips: {counts['circuit_breaker']}\n\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"<i>{datetime.now(IST).strftime('%Y-%m-%d %I:%M %p IST')}</i>"
    )

    send_telegram(report)
    print("Reconciler incident summary sent.")

    # Save to file
    report_dir = PROJECT_ROOT / "storage" / "reports" / "paper_validation"
    report_dir.mkdir(parents=True, exist_ok=True)
    with open(report_dir / f"recon_{datetime.now(IST).strftime('%Y%m%d')}.txt", "w") as f:
        f.write(report)


if __name__ == "__main__":
    main()
