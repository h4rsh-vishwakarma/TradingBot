#!/usr/bin/env python3
"""
Daily Top-10 Strategies Report (Phase 5)
=========================================
Runs every day at 8:00 AM IST via cron. Pipeline:

  1. Run advanced_metrics.py to enrich the latest tournament_winners.csv
  2. Run composite_ranker.py to produce candidates_top10.csv
  3. Compare with yesterday's top-10 snapshot → flag unchanged / new / dropped
  4. Send Telegram message with:
        - Top 10 strategies ranked by Risk_Adjusted_Score
        - Per-strategy: ROI, DD, WR, Calmar, trades, hard-filter status
        - Pine script filename pointer (if found in strategies/)
        - Summary counters (unchanged, new, dropped)
  5. Save today's snapshot → storage/reports/daily_top/top10_<date>.json

Failsafe: if enrichment or ranking fails, send a CRITICAL Telegram alert
rather than failing silently. The cron continues to retry next day.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

IST = timezone(timedelta(hours=5, minutes=30))
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

ENV_FILE = "/etc/tradingbot/env_vars"
if os.path.exists(ENV_FILE):
    load_dotenv(ENV_FILE, override=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("daily_top_strategies")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TOURNAMENT_CSV = PROJECT_ROOT / "storage" / "reports" / "tournament_winners.csv"
ENRICHED_CSV = PROJECT_ROOT / "storage" / "reports" / "tournament_winners_enriched.csv"
TOP10_CSV = PROJECT_ROOT / "storage" / "reports" / "candidates_top10.csv"
SNAPSHOT_DIR = PROJECT_ROOT / "storage" / "reports" / "daily_top"
PINE_DIR = PROJECT_ROOT / "strategies"
GENERATED_PINE_DIR = PROJECT_ROOT / "storage" / "generated_alpha_scripts"


def send_telegram(text: str, chunk_size: int = 3800) -> None:
    """Send a (possibly long) Telegram message, chunking if necessary."""
    import requests

    if not TOKEN or not CHAT_ID:
        print("[TELEGRAM NOT CONFIGURED — printing locally]")
        print(text)
        return

    # Telegram hard limit ~4096 chars
    for chunk_start in range(0, len(text), chunk_size):
        chunk = text[chunk_start : chunk_start + chunk_size]
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                json={"chat_id": CHAT_ID, "text": chunk, "parse_mode": "HTML"},
                timeout=20,
            )
            if r.status_code != 200:
                logger.error(f"Telegram send failed: {r.status_code} {r.text}")
        except Exception as exc:
            logger.error(f"Telegram send exception: {exc}")


def run_explorer() -> bool:
    """Run strategy_explorer.py to discover new single-indicator strategies."""
    logger.info("Running strategy_explorer.py (4h timeframe) ...")
    try:
        r = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "strategy_explorer.py"),
             "--timeframe", "4h", "--min-roi", "-999", "--quiet"],
            capture_output=True, text=True, timeout=300, cwd=str(PROJECT_ROOT),
        )
        if r.returncode != 0:
            logger.warning(f"strategy_explorer.py failed (non-blocking): {r.stderr[:500]}")
            return False
        return True
    except Exception as exc:
        logger.warning(f"strategy_explorer.py exception (non-blocking): {exc}")
        return False


def run_ensemble() -> bool:
    """Run ensemble_builder.py to discover strategy combinations."""
    logger.info("Running ensemble_builder.py (4h timeframe) ...")
    try:
        r = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "ensemble_builder.py"),
             "--timeframe", "4h", "--min-roi", "-999", "--quiet"],
            capture_output=True, text=True, timeout=600, cwd=str(PROJECT_ROOT),
        )
        if r.returncode != 0:
            logger.warning(f"ensemble_builder.py failed (non-blocking): {r.stderr[:500]}")
            return False
        return True
    except Exception as exc:
        logger.warning(f"ensemble_builder.py exception (non-blocking): {exc}")
        return False


def run_enrichment() -> bool:
    """Run advanced_metrics.py. Returns True on success."""
    logger.info("Running advanced_metrics.py ...")
    try:
        r = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "advanced_metrics.py"), "--quiet"],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(PROJECT_ROOT),
        )
        if r.returncode != 0:
            logger.error(f"advanced_metrics.py failed: {r.stderr[:500]}")
            return False
        return True
    except Exception as exc:
        logger.error(f"advanced_metrics.py exception: {exc}")
        return False


def run_ranker() -> bool:
    """Run composite_ranker.py. Returns True on success."""
    logger.info("Running composite_ranker.py ...")
    try:
        r = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "composite_ranker.py"), "--quiet"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(PROJECT_ROOT),
        )
        if r.returncode != 0:
            logger.error(f"composite_ranker.py failed: {r.stderr[:500]}")
            return False
        return True
    except Exception as exc:
        logger.error(f"composite_ranker.py exception: {exc}")
        return False


def load_top10() -> list[dict]:
    """Read today's top-10 from candidates_top10.csv."""
    import pandas as pd

    if not TOP10_CSV.exists():
        return []
    df = pd.read_csv(TOP10_CSV)
    return df.to_dict(orient="records")


def save_snapshot(rows: list[dict]) -> Path:
    """Save today's top-10 as JSON."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(IST).strftime("%Y%m%d")
    path = SNAPSHOT_DIR / f"top10_{today}.json"
    snapshot = {
        "date": today,
        "generated_at": datetime.now(IST).isoformat(),
        "entries": [
            {
                "strategy": str(r.get("Strategy", "")),
                "symbol": str(r.get("Symbol", "")),
                "daily_roi_pct": float(r.get("Daily_ROI_%", 0) or 0),
                "gross_dd_pct": float(r.get("Gross_DD_%", 0) or 0),
                "win_rate_pct": float(r.get("Win_Rate_%", 0) or 0),
                "risk_adjusted_score": float(r.get("Risk_Adjusted_Score", 0) or 0),
                "calmar_ratio": float(r.get("Calmar_Ratio", 0) or 0),
                "passes_hard_filter": bool(r.get("Passes_Hard_Filter", False)),
                "filter_mode": str(r.get("Filter_Mode", "unknown")),
            }
            for r in rows
        ],
    }
    path.write_text(json.dumps(snapshot, indent=2))
    return path


def load_yesterday_snapshot() -> list[dict]:
    """Read yesterday's snapshot if present."""
    yesterday = (datetime.now(IST) - timedelta(days=1)).strftime("%Y%m%d")
    path = SNAPSHOT_DIR / f"top10_{yesterday}.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return data.get("entries", [])
    except Exception as exc:
        logger.warning(f"could not parse yesterday snapshot: {exc}")
        return []


def compare_with_yesterday(today: list[dict], yesterday: list[dict]) -> dict:
    """Return set-based diff: unchanged, new, dropped (by strategy+symbol key)."""
    def _key(e):
        return f"{str(e.get('Strategy') or e.get('strategy', '')).strip()}|{str(e.get('Symbol') or e.get('symbol', '')).strip()}"

    today_keys = {_key(e): i + 1 for i, e in enumerate(today)}
    yday_keys = {_key(e): i + 1 for i, e in enumerate(yesterday)}

    unchanged = {k: (today_keys[k], yday_keys[k]) for k in today_keys if k in yday_keys}
    new_entries = [k for k in today_keys if k not in yday_keys]
    dropped = [k for k in yday_keys if k not in today_keys]

    return {
        "unchanged": unchanged,
        "new": new_entries,
        "dropped": dropped,
    }


def find_pine_script(strategy_name: str) -> str | None:
    """Try to find a Pine script filename matching the strategy name."""
    if not strategy_name:
        return None
    # Normalize the name for matching
    needle = strategy_name.lower().replace(" ", "_").replace("-", "_")
    for directory in [PINE_DIR, GENERATED_PINE_DIR]:
        if not directory.exists():
            continue
        for p in directory.rglob("*.pine"):
            if needle in p.stem.lower() or p.stem.lower() in needle:
                return str(p.relative_to(PROJECT_ROOT))
        for p in directory.rglob("*.txt"):
            if needle in p.stem.lower() or p.stem.lower() in needle:
                return str(p.relative_to(PROJECT_ROOT))
    return None


def format_telegram_message(rows: list[dict], diff: dict) -> str:
    today_str = datetime.now(IST).strftime("%Y-%m-%d %I:%M %p IST")
    if not rows:
        return (
            f"📊 <b>DAILY TOP-10 STRATEGIES REPORT</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"⚠️ <b>No candidates found today.</b>\n\n"
            f"The tournament produced zero strategies matching the current filter. "
            f"Check the backtest engine or tournament cron logs.\n\n"
            f"<i>{today_str}</i>"
        )

    filter_mode = rows[0].get("Filter_Mode", "unknown")
    filter_label = {
        "strict": "✅ STRICT (ROI≥1 AND DD≤12 AND WR≥45 AND trades≥100)",
        "soft": "🟡 SOFT fallback (ROI≥0.3 AND DD≤25 AND WR≥40 AND trades≥50)",
        "unfiltered_fallback": "🔴 UNFILTERED (no rows matched any filter)",
        "bypass": "⚪ BYPASS (filter disabled)",
    }.get(filter_mode, filter_mode)

    msg = (
        f"📊 <b>DAILY TOP-10 STRATEGIES REPORT</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>Date:</b> {today_str}\n"
        f"<b>Filter:</b> {filter_label}\n"
        f"<b>Unchanged from yesterday:</b> {len(diff['unchanged'])}\n"
        f"<b>New entries:</b> {len(diff['new'])}\n"
        f"<b>Dropped from yesterday:</b> {len(diff['dropped'])}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
    )

    for i, r in enumerate(rows, 1):
        strategy = str(r.get("Strategy", "N/A"))
        symbol = str(r.get("Symbol", "N/A"))
        key = f"{strategy}|{symbol}"
        was_yesterday = key in diff["unchanged"]
        marker = "🔁" if was_yesterday else "🆕"

        daily_roi = float(r.get("Daily_ROI_%", 0) or 0)
        gross_dd = float(r.get("Gross_DD_%", 0) or 0)
        win_rate = float(r.get("Win_Rate_%", 0) or 0)
        trades = int(r.get("Total_Trades", 0) or 0)
        calmar = float(r.get("Calmar_Ratio", 0) or 0)
        sortino = float(r.get("Sortino_Ratio", 0) or 0)
        ras = float(r.get("Risk_Adjusted_Score", 0) or 0)
        wfa = float(r.get("WFA_Consistency", 0) or 0)
        mc_dd = float(r.get("MC_Worst_DD_95_Est", 0) or 0)
        uw_days = int(r.get("Underwater_Days_Est", 0) or 0)
        passes = bool(r.get("Passes_Hard_Filter", False))
        pass_badge = "✅" if passes else "⚪"

        pine_path = find_pine_script(strategy)
        pine_line = f"\n  🧾 <i>Pine:</i> <code>{pine_path}</code>" if pine_path else ""

        msg += (
            f"<b>#{i} {marker} {pass_badge} {strategy}</b>\n"
            f"  💎 <b>{symbol}</b>\n"
            f"  📈 ROI: {daily_roi:.3f}% daily | DD: {gross_dd:.1f}% | WR: {win_rate:.1f}% | Trades: {trades}\n"
            f"  ⚖️ Calmar: {calmar:.2f} | Sortino: {sortino:.2f} | WFA: {wfa:.2f}\n"
            f"  🧮 MC-DD-95: {mc_dd:.1f}% | UW days: {uw_days}\n"
            f"  🎯 <b>Score:</b> <code>{ras:.4f}</code>{pine_line}\n\n"
        )

    msg += (
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Legend: ✅=passes strict gate  ⚪=via soft filter  🔁=unchanged from yesterday  🆕=new entry\n\n"
        f"<i>Generated by daily_top_strategies_report.py</i>"
    )
    return msg


def main():
    logger.info("Daily top-10 report starting ...")

    if not TOURNAMENT_CSV.exists():
        send_telegram(
            "🚨 <b>Daily Top-10 Report FAILED</b>\n\n"
            f"Tournament CSV not found: <code>{TOURNAMENT_CSV}</code>\n"
            "Check the tournament cron."
        )
        return 1

    # Discovery: explorer + ensemble run first (non-blocking — if they fail
    # the daily report still works with just tournament data).
    run_explorer()
    run_ensemble()

    if not run_enrichment():
        send_telegram(
            "🚨 <b>Daily Top-10 Report FAILED</b>\n\n"
            "advanced_metrics.py failed. See journalctl cron logs."
        )
        return 1

    if not run_ranker():
        send_telegram(
            "🚨 <b>Daily Top-10 Report FAILED</b>\n\n"
            "composite_ranker.py failed. See journalctl cron logs."
        )
        return 1

    today_rows = load_top10()
    yesterday_rows = load_yesterday_snapshot()
    diff = compare_with_yesterday(today_rows, yesterday_rows)

    message = format_telegram_message(today_rows, diff)
    send_telegram(message)

    snapshot_path = save_snapshot(today_rows)
    logger.info(f"Snapshot saved: {snapshot_path}")
    logger.info(
        f"Report summary: {len(today_rows)} entries, "
        f"{len(diff['unchanged'])} unchanged, {len(diff['new'])} new"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
