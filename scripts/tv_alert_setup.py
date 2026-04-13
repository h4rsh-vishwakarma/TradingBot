#!/usr/bin/env python3
"""
tv_alert_setup.py — Auto-send TradingView alert setup guide via Telegram.

For every approved strategy × symbol combination:
  1. Verifies Pine script exists in strategies/pine_v3/ or strategies/pine_combos/
  2. Generates step-by-step Telegram message with exact JSON + webhook URL
  3. User only needs to: (a) add script to chart, (b) create alert, (c) paste webhook URL once

Usage:
  python3 scripts/tv_alert_setup.py                     # all approved strategies
  python3 scripts/tv_alert_setup.py CCI_Trend ETHUSDT   # specific
  python3 scripts/tv_alert_setup.py --top5              # top 5 from combo_winners.csv

Telegram command: /setup_alerts [strategy] [symbol]
"""

import json
import os
import sys
import glob
import argparse
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

ENV_FILE = "/etc/tradingbot/env_vars"
if os.path.exists(ENV_FILE):
    load_dotenv(ENV_FILE, override=True)

TOKEN          = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID        = os.getenv("TELEGRAM_CHAT_ID", "5736858710")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "squeeze_tradingview_cluster_2026_secure")
SERVER_URL     = "http://15.207.152.119:5000/webhook/tradingview"

MANIFEST_PATH  = PROJECT_ROOT / "config" / "approved_strategies.json"
PINE_V3_DIR    = PROJECT_ROOT / "strategies" / "pine_v3"
PINE_COMBO_DIR = PROJECT_ROOT / "strategies" / "pine_combos"
COMBO_CSV      = PROJECT_ROOT / "storage" / "reports" / "combo_winners.csv"


# ── Core JSON builders ────────────────────────────────────────────────────────
def make_alert_json(strategy, action, ticker="{{ticker}}"):
    return json.dumps({
        "secret":   WEBHOOK_SECRET,
        "strategy": strategy,
        "action":   action,
        "ticker":   ticker,
        "interval": "{{interval}}",
        "price":    "{{close}}",
    }, separators=(",", ":"))


def make_alert_block(strategy, symbol):
    """Returns a formatted Telegram message for one strategy/symbol pair."""
    long_json   = make_alert_json(strategy, "BUY",         ticker=symbol)
    short_json  = make_alert_json(strategy, "SELL",        ticker=symbol)
    clong_json  = make_alert_json(strategy, "CLOSE_LONG",  ticker=symbol)
    cshort_json = make_alert_json(strategy, "CLOSE_SHORT", ticker=symbol)

    # Look for a generated Pine script
    safe_strat = strategy.replace(" ", "_")
    pine_files = (
        list(PINE_V3_DIR.glob(f"{symbol}_{safe_strat}*.pine"))
        + list(PINE_COMBO_DIR.glob(f"*{safe_strat}*.pine"))
        + list(PINE_V3_DIR.glob(f"{symbol}_*.pine"))
    )
    pine_note = (
        f"Pine script: <code>strategies/pine_v3/{pine_files[0].name}</code>"
        if pine_files else
        "Pine script: not generated yet — run generate_pine_v3.py first"
    )

    return f"""
<b>Alert Setup — {strategy} / {symbol}</b>
{pine_note}

<b>Step 1</b> — Add Pine script to chart
  • Open TradingView → {symbol} → 4H chart
  • Pine Editor → paste script → Add to chart

<b>Step 2</b> — Create alert (do this ONCE per symbol)
  • Click the bell icon (Alerts)
  • Condition: <b>Any alert() function call</b>  ← IMPORTANT
  • Message box: leave BLANK (script fills it automatically)
  • Webhook URL: <code>{SERVER_URL}</code>
  • Alert name: {strategy} {symbol}
  • Save

<b>Step 3</b> — Verify (optional)
  • Send test signal:
<code>curl -X POST {SERVER_URL} \\
  -H "Content-Type: application/json" \\
  -d '{long_json}'</code>

<b>JSON reference (for manual alerts):</b>
  BUY:         <code>{long_json}</code>
  SELL:        <code>{short_json}</code>
  CLOSE LONG:  <code>{clong_json}</code>
  CLOSE SHORT: <code>{cshort_json}</code>

Webhook URL: <code>{SERVER_URL}</code>
"""


# ── Telegram helpers ──────────────────────────────────────────────────────────
def send_telegram(text, chat_id=None):
    cid = chat_id or CHAT_ID
    if not TOKEN:
        print(text); return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": cid, "text": text, "parse_mode": "HTML"},
            timeout=15,
        )
    except Exception as e:
        print(f"Telegram send failed: {e}")


def send_long(text, chat_id=None):
    """Split long messages at 4096 char limit."""
    limit = 4000
    for i in range(0, len(text), limit):
        send_telegram(text[i:i + limit], chat_id)


# ── Manifest reader ───────────────────────────────────────────────────────────
def load_manifest():
    with open(MANIFEST_PATH) as f:
        return json.load(f)


def get_approved_combos(filter_strategy=None, filter_symbol=None):
    """Return list of (strategy, symbol) pairs from manifest."""
    data    = load_manifest()
    combos  = []
    for entry in data.get("approvals", []):
        strat   = entry["strategy"]
        symbols = entry.get("symbols", ["*"])
        if filter_strategy and strat != filter_strategy:
            continue
        if "*" in symbols:
            # Wildcard — default to the 6 primary symbols
            effective = ["ETHUSDT", "BTCUSDT", "XRPUSDT", "LDOUSDT", "AVAXUSDT", "SUIUSDT", "LINKUSDT"]
        else:
            effective = symbols
        for sym in effective:
            if filter_symbol and sym != filter_symbol:
                continue
            combos.append((strat, sym))
    return combos


# ── Main ──────────────────────────────────────────────────────────────────────
def run_setup(filter_strategy=None, filter_symbol=None, top5_combos=False, chat_id=None):
    if top5_combos:
        # Pull top-5 from combo_winners.csv
        try:
            import pandas as pd
            df = pd.read_csv(COMBO_CSV).head(5)
            pairs = [(row['Combo'], row['Symbol']) for _, row in df.iterrows()]
        except Exception as e:
            send_telegram(f"Could not read combo_winners.csv: {e}", chat_id)
            return
    else:
        pairs = get_approved_combos(filter_strategy, filter_symbol)

    if not pairs:
        send_telegram("No matching strategy/symbol pairs found in manifest.", chat_id)
        return

    header = (
        f"<b>TradingView Alert Setup Guide</b>\n"
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"Pairs: {len(pairs)}\n"
        f"Webhook: <code>{SERVER_URL}</code>\n"
    )
    send_telegram(header, chat_id)

    for strat, sym in pairs:
        block = make_alert_block(strat, sym)
        send_long(block.strip(), chat_id)

    send_telegram(
        "<b>Setup complete!</b>\n"
        "After alerts are live, send a test signal using the curl commands above.\n"
        "Then watch Telegram for execution confirmation.",
        chat_id,
    )


def run_single(strategy, symbol, chat_id=None):
    block = make_alert_block(strategy, symbol)
    send_long(block.strip(), chat_id)


# ── CLI entry ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate TradingView alert setup guide")
    parser.add_argument("strategy", nargs="?", default=None, help="Strategy name filter")
    parser.add_argument("symbol",   nargs="?", default=None, help="Symbol filter (e.g. ETHUSDT)")
    parser.add_argument("--top5",   action="store_true",     help="Show top 5 from combo_winners.csv")
    args = parser.parse_args()

    if args.strategy and args.symbol:
        run_single(args.strategy, args.symbol)
    else:
        run_setup(
            filter_strategy=args.strategy,
            filter_symbol=args.symbol,
            top5_combos=args.top5,
        )
