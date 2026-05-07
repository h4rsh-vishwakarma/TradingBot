#!/usr/bin/env python3
"""paper_window_watchdog.py - T11: zero-signal alert for active paper window."""
import json, os, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path
import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
ENV_FILE = "/etc/tradingbot/env_vars"
if os.path.exists(ENV_FILE):
    load_dotenv(ENV_FILE, override=True)
else:
    load_dotenv()

TOKEN     = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "5736858710")
MANIFEST  = PROJECT_ROOT / "config" / "approved_strategies.json"
SIGNAL_DB = PROJECT_ROOT / "storage" / "signal_queue.db"
WARN_H    = int(os.getenv("SIGNAL_WATCHDOG_WARN_HOURS", "24"))

def _send(msg):
    if not TOKEN:
        print("[watchdog] no TOKEN")
        return
    try:
        requests.post(
            "https://api.telegram.org/bot{}/sendMessage".format(TOKEN),
            json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        print("[watchdog] send failed:", e)

def _nominees():
    try:
        d = json.load(open(MANIFEST))
        return [a for a in d.get("approvals", [])
                if a.get("label") == "P07_NOMINEE" and a.get("paper_window_status") == "ACTIVE"]
    except Exception as e:
        print("[watchdog] manifest error:", e)
        return []

def _age_h():
    if not SIGNAL_DB.exists() or SIGNAL_DB.stat().st_size == 0:
        return None
    try:
        with sqlite3.connect(str(SIGNAL_DB)) as c:
            row = c.execute("SELECT created_at FROM signals ORDER BY created_at DESC LIMIT 1").fetchone()
            if not row:
                return None
            last = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
            return round((datetime.now(timezone.utc) - last).total_seconds() / 3600, 1)
    except Exception as e:
        print("[watchdog] db error:", e)
        return None

def run():
    noms = _nominees()
    if not noms:
        print("[watchdog] no ACTIVE P07_NOMINEE")
        return
    age   = _age_h()
    empty = not SIGNAL_DB.exists() or SIGNAL_DB.stat().st_size == 0
    now   = datetime.now(timezone.utc).isoformat()
    for n in noms:
        s  = n.get("strategy", "?")
        ws = n.get("paper_window_start", "?")
        if empty or age is None:
            msg = "PAPER WINDOW WATCHDOG\nStrategy: {}\nWindow: {}\nsignal_queue.db EMPTY - no TV signals received.\nAction: verify TV alert URL + WEBHOOK_SECRET.\nChecked: {}".format(s, ws, now)
            print("[watchdog] ALERT: db empty for", s)
            _send(msg)
        elif age > WARN_H:
            msg = "PAPER WINDOW WATCHDOG\nStrategy: {}\nWindow: {}\nLast signal: {}h ago (threshold {}h)\nAction: check TV alert + WEBHOOK_SECRET.\nChecked: {}".format(s, ws, age, WARN_H, now)
            print("[watchdog] ALERT: {}h gap for {}".format(age, s))
            _send(msg)
        else:
            print("[watchdog] OK: {} last signal {}h ago".format(s, age))

if __name__ == "__main__":
    run()
