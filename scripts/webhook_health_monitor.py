#!/usr/bin/env python3
"""
Webhook Health Monitor
======================
Runs every 30 min via cron. Sends a synthetic POST probe to /webhook/tradingview
with an intentionally invalid secret. A healthy server returns 401 (unauthorized).
Any 5xx or connection error means the signal pipeline is broken — logs ALERT and
optionally fires a Telegram message.

Exit codes: 0=healthy, 1=degraded/down
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv("/etc/tradingbot/env_vars") if Path("/etc/tradingbot/env_vars").exists() else load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_FILE = PROJECT_ROOT / "storage" / "reports" / "webhook_health.log"
WEBHOOK_URL = "http://127.0.0.1:5000/webhook/tradingview"
TIMEOUT_S = 10

UTC = timezone.utc


def _log(line: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")
    print(line)


def _telegram_alert(msg: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
            timeout=8,
        )
    except Exception:
        pass


def probe() -> int:
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        resp = requests.post(
            WEBHOOK_URL,
            json={
                "secret": "HEALTH_PROBE_INVALID_DO_NOT_PROCESS",
                "strategy": "HealthProbe",
                "symbol": "PROBE",
                "action": "buy",
                "price": 1.0,
                "is_health_check": True,
            },
            timeout=TIMEOUT_S,
        )
        code = resp.status_code
        if code == 401:
            _log(f"[{ts}] OK  — webhook POST returned {code} (expected 401, pipeline healthy)")
            return 0
        elif 200 <= code < 300:
            # Probe somehow passed — still means server is alive
            _log(f"[{ts}] OK  — webhook POST returned {code} (server alive)")
            return 0
        elif code >= 500:
            msg = f"[{ts}] ALERT — webhook POST returned {code} (server error — pipeline broken)"
            _log(msg)
            _telegram_alert(
                f"🚨 <b>Webhook Health Monitor ALERT</b>\n"
                f"POST /webhook/tradingview returned <b>HTTP {code}</b>\n"
                f"Signal pipeline may be broken — check logs immediately.\n"
                f"Time: {ts}"
            )
            return 1
        else:
            _log(f"[{ts}] WARN — webhook POST returned {code} (unexpected, monitor manually)")
            return 0
    except requests.exceptions.ConnectionError:
        msg = f"[{ts}] ALERT — webhook POST connection refused (Flask server DOWN)"
        _log(msg)
        _telegram_alert(
            f"🚨 <b>Webhook Health Monitor ALERT</b>\n"
            f"Cannot connect to webhook server (connection refused).\n"
            f"Flask may be down — check <code>systemctl status tradingbot-webhook</code>\n"
            f"Time: {ts}"
        )
        return 1
    except requests.exceptions.Timeout:
        msg = f"[{ts}] ALERT — webhook POST timed out after {TIMEOUT_S}s (server unresponsive)"
        _log(msg)
        _telegram_alert(
            f"🚨 <b>Webhook Health Monitor ALERT</b>\n"
            f"Webhook POST timed out after {TIMEOUT_S}s.\n"
            f"Server may be overloaded or hung.\n"
            f"Time: {ts}"
        )
        return 1
    except Exception as exc:
        _log(f"[{ts}] ALERT — probe exception: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(probe())
