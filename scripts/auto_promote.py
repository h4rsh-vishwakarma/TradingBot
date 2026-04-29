#!/usr/bin/env python3
"""
auto_promote.py — Auto-promote paper-validated strategies to candidate_for_tiny_capital.

Hard gates (ALL must pass):
  1. Not already candidate_for_tiny_capital (or label == LIVE_VERIFIED)
  2. At least PAPER_MIN_DAYS days of paper window coverage
  3. At least MIN_CLOSED_TRADES closed trades (is_exit=True in execution_metrics.jsonl,
     on an approved symbol). Threshold: 4H=5, 1H=10, 15m=20. This mirrors Gate #25.
  4. OOS baseline > 0 in tournament_winners_4h_v4.csv (current engine, fixed sizing)

Soft indicator (logged but not a gate):
  - Signal count from signal_queue.db (activity proxy)

On success:
  - Updates config/approved_strategies.json
  - Sends Telegram promotion notice
  - Logs to storage/reports/auto_promote_log.jsonl

Governance note (P-01):
  Auto-promotion adds label="AUTO_PROMOTED" and sets approval_class=candidate_for_tiny_capital.
  Human review + Sainath sign-off still required before real capital deployment.
  AUTO_PROMOTE_FREEZE=true blocks all promotions unconditionally.

Usage:
  python3 scripts/auto_promote.py
"""

import json
import os
import sys
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

ENV_FILE = "/etc/tradingbot/env_vars"
if os.path.exists(ENV_FILE):
    load_dotenv(ENV_FILE, override=True)

TOKEN    = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID  = os.getenv("TELEGRAM_CHAT_ID", "5736858710")

MANIFEST_PATH   = PROJECT_ROOT / "config" / "approved_strategies.json"
SIGNAL_DB       = PROJECT_ROOT / "tradingview_webhook_bot" / "storage" / "signal_queue.db"
LEDGER_PATH     = PROJECT_ROOT / "tradingview_webhook_bot" / "storage" / "ledger_state.json"
TOURNAMENT_CSV  = PROJECT_ROOT / "storage" / "reports" / "tournament_winners_4h_v4.csv"
EXEC_METRICS    = PROJECT_ROOT / "storage" / "reports" / "paper_validation" / "execution_metrics.jsonl"
PROMO_LOG       = PROJECT_ROOT / "storage" / "reports" / "auto_promote_log.jsonl"

PAPER_MIN_DAYS       = int(os.getenv("PAPER_MIN_DAYS",        "7"))
MIN_SIGNALS          = int(os.getenv("MIN_SIGNALS",            "5"))   # signal activity proxy
MIN_CLOSED_TRADES_4H = int(os.getenv("MIN_CLOSED_TRADES_4H",  "5"))   # hard gate — mirrors Gate #25


def send_telegram(text):
    if not TOKEN:
        print(text); return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=15,
        )
    except Exception:
        pass


def load_manifest():
    with open(MANIFEST_PATH) as f:
        return json.load(f)


def save_manifest(data):
    data["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data["version"]    = data.get("version", 1) + 1
    with open(MANIFEST_PATH, "w") as f:
        json.dump(data, f, indent=2)


def load_tournament_oos():
    """Return dict: strategy_name -> OOS_Daily_ROI_%"""
    result = {}
    try:
        import csv
        with open(TOURNAMENT_CSV) as f:
            for row in csv.DictReader(f):
                result[row["Strategy"]] = float(row.get("OOS_Daily_ROI_%", 0) or 0)
    except Exception:
        pass
    return result


def get_paper_stats(strategy_name):
    """
    Pull actual paper trade stats from the signal DB.
    Returns: {signals_count, days_active, avg_return_pct, first_signal_ts, last_signal_ts}
    or None if not enough data.
    """
    try:
        conn = sqlite3.connect(str(SIGNAL_DB))
        now  = datetime.now(timezone.utc).timestamp()
        rows = conn.execute(
            """
            SELECT payload, status, created_at
            FROM   signals
            WHERE  status = 'completed'
            ORDER  BY created_at ASC
            """,
        ).fetchall()
        conn.close()
    except Exception:
        return None

    matching = []
    for payload_raw, status, created_at in rows:
        try:
            d = json.loads(payload_raw)
            p = d.get("payload", d) if isinstance(d, dict) else {}
            strat = str(p.get("strategy", ""))
            if strat != strategy_name:
                continue
            matching.append({"ts": float(created_at), "payload": p})
        except Exception:
            continue

    if not matching:
        return None

    first_ts = matching[0]["ts"]
    last_ts  = matching[-1]["ts"]
    days_active = (last_ts - first_ts) / 86400

    return {
        "signals_count": len(matching),
        "days_active":   round(days_active, 1),
        "first_ts":      datetime.utcfromtimestamp(first_ts).strftime("%Y-%m-%d"),
        "last_ts":       datetime.utcfromtimestamp(last_ts).strftime("%Y-%m-%d"),
    }


def get_closed_trade_count(strategy_name: str, approved_symbols: list) -> int:
    """
    Count is_exit=True entries in execution_metrics.jsonl for this strategy
    on any of its approved symbols. This is the same logic as Gate #25.
    """
    if not EXEC_METRICS.exists():
        return 0
    norm = strategy_name.strip().lower().replace(" ", "_").replace("-", "_")
    count = 0
    try:
        with open(EXEC_METRICS) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if not rec.get("is_exit"):
                    continue
                rec_strat = rec.get("strategy", "")
                rec_sym   = rec.get("symbol", "")
                rec_norm  = rec_strat.strip().lower().replace(" ", "_").replace("-", "_")
                if rec_norm != norm:
                    continue
                if approved_symbols and rec_sym not in approved_symbols:
                    continue
                count += 1
    except Exception:
        pass
    return count


def check_and_promote():
    now      = datetime.now(timezone.utc)
    manifest = load_manifest()
    oos_roi  = load_tournament_oos()
    promoted = []
    skipped  = []

    for entry in manifest.get("approvals", []):
        strat   = entry["strategy"]
        aclass  = entry.get("approval_class", "")
        label   = str(entry.get("label", "")).upper()

        # Only consider paper_only or unlabelled RESEARCH entries
        if aclass == "candidate_for_tiny_capital" and label not in ("RESEARCH",):
            continue
        if label == "LIVE_VERIFIED":
            continue

        stats = get_paper_stats(strat)
        if not stats:
            skipped.append((strat, "no paper signals found"))
            continue

        if stats["signals_count"] < MIN_SIGNALS:
            skipped.append((strat, f"only {stats['signals_count']} signals (need {MIN_SIGNALS})"))
            continue

        if stats["days_active"] < PAPER_MIN_DAYS:
            skipped.append((strat, f"only {stats['days_active']} days active (need {PAPER_MIN_DAYS})"))
            continue

        # Hard gate: minimum closed trades (is_exit=True) on approved symbols — mirrors Gate #25
        approved_symbols = entry.get("symbols", [])
        closed = get_closed_trade_count(strat, approved_symbols)
        # Threshold is timeframe-aware; default to 4H threshold for now
        timeframes = entry.get("timeframes", ["240"])
        tf = str(timeframes[0]) if timeframes else "240"
        if tf in ("15", "15m"):
            min_closed = 20
        elif tf in ("60", "1h", "1H"):
            min_closed = 10
        else:
            min_closed = MIN_CLOSED_TRADES_4H  # 4H default = 5
        if closed < min_closed:
            skipped.append((strat, f"only {closed} closed trades on {approved_symbols} (need {min_closed})"))
            continue

        # OOS baseline must be present and positive in the current v4 tournament output
        baseline = oos_roi.get(strat)
        if baseline is None or baseline <= 0:
            skipped.append((strat, "no positive OOS baseline in tournament_4h_v4.csv"))
            continue

        entry["approval_class"]  = "candidate_for_tiny_capital"
        entry["label"]           = "AUTO_PROMOTED"
        entry["promoted_at"]     = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        entry["class_reason"]    = (
            f"Auto-promoted {now.strftime('%Y-%m-%d')}: "
            f"{stats['signals_count']} signals over {stats['days_active']} days. "
            f"OOS baseline ROI: {baseline}%/day. "
            f"Human review required before real capital deployment."
        )
        promoted.append({
            "strategy":     strat,
            "signals":      stats["signals_count"],
            "days_active":  stats["days_active"],
            "closed_trades": closed,
            "oos_baseline": baseline,
            "promoted_at":  entry["promoted_at"],
        })

    if promoted:
        save_manifest(manifest)
        # Write promotion log
        with open(PROMO_LOG, "a") as f:
            for p in promoted:
                f.write(json.dumps({**p, "run_ts": now.strftime("%Y-%m-%dT%H:%M:%SZ")}) + "\n")

        promo_lines = "\n".join(
            f"  ✅ <b>{p['strategy']}</b> — {p['closed_trades']} closed trades / {p['days_active']}d  OOS={p['oos_baseline']}%/day"
            for p in promoted
        )
        send_telegram(
            f"<b>Auto-Promote Report</b> — {now.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
            f"Promoted to <code>candidate_for_tiny_capital</code>:\n{promo_lines}\n\n"
            f"<i>Label: AUTO_PROMOTED — human review required before real capital.</i>\n"
            f"Use /manifest to see updated manifest."
        )
        print(f"Promoted {len(promoted)} strategies.")
    else:
        print("No promotions this run.")

    if skipped:
        print(f"Skipped ({len(skipped)}):")
        for name, reason in skipped:
            print(f"  {name}: {reason}")

    return promoted


if __name__ == "__main__":
    # Governance freeze guard (CEO audit A-07): block auto-promotion during checkpoint window.
    # Remove this block only after Sainath checkpoint verdict is issued.
    _freeze_flag = os.path.join(os.path.dirname(MANIFEST_PATH), ".auto_promote_freeze")
    _env_freeze = os.getenv("AUTO_PROMOTE_FREEZE", "true").lower()
    if _env_freeze == "true" or os.path.exists(_freeze_flag):
        msg = "[auto_promote] FREEZE ACTIVE — checkpoint in progress. No promotions written. Set AUTO_PROMOTE_FREEZE=false to override."
        print(msg)
        send_telegram(f"⚠️ <b>Auto-Promote BLOCKED</b>\n{msg}")
        sys.exit(0)
    check_and_promote()
