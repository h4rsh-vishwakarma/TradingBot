#!/usr/bin/env python3
"""
Paper Simulation Engine
=======================
Simulates P&L for paper_only strategies by replaying their signals
against real Binance OHLCV data.

How it works:
1. Reads signal_queue.db — finds all signals for paper_only strategies
2. For each entry signal, records the entry price (from payload or Binance API)
3. Fetches subsequent OHLCV candles via Binance public REST API
4. Applies configurable SL% and TP% — exits when hit, or on signal flip
5. Writes per-strategy daily P&L to storage/reports/paper_sim/

Run:
    python scripts/paper_sim_engine.py            # simulate all paper_only
    python scripts/paper_sim_engine.py --report   # print summary table
    python scripts/paper_sim_engine.py --days 7   # only last N days of signals
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("paper_sim")

SIGNAL_DB = PROJECT_ROOT / "tradingview_webhook_bot" / "storage" / "signal_queue.db"
MANIFEST_PATH = PROJECT_ROOT / "config" / "approved_strategies.json"
SIM_DIR = PROJECT_ROOT / "storage" / "reports" / "paper_sim"
SIM_RESULTS_FILE = SIM_DIR / "paper_sim_results.json"

BINANCE_BASE = "https://fapi.binance.com"

# Default risk parameters (used when strategy config doesn't specify)
DEFAULT_SL_PCT = 3.0
DEFAULT_TP_PCT = 5.0
DEFAULT_FIXED_NOTIONAL = 100.0   # $100 per simulated trade (paper only)

_TF_TO_BINANCE_INTERVAL = {
    "1": "1m", "3": "3m", "5": "5m", "15": "15m", "30": "30m",
    "60": "1h", "120": "2h", "240": "4h", "480": "8h", "720": "12h",
    "1d": "1d", "D": "1d", "W": "1w",
}


# ─── Binance helpers ───────────────────────────────────────────────────────────

def _binance_klines(symbol: str, interval: str, start_ms: int, limit: int = 100) -> list[list]:
    """Fetch OHLCV from Binance Futures public endpoint."""
    url = f"{BINANCE_BASE}/fapi/v1/klines"
    params = {"symbol": symbol.upper(), "interval": interval,
               "startTime": start_ms, "limit": limit}
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning(f"Binance klines failed ({symbol} {interval}): {exc}")
        return []


def _binance_mark_price(symbol: str) -> float | None:
    """Current mark price for a symbol."""
    try:
        url = f"{BINANCE_BASE}/fapi/v1/premiumIndex"
        resp = requests.get(url, params={"symbol": symbol.upper()}, timeout=5)
        resp.raise_for_status()
        return float(resp.json()["markPrice"])
    except Exception:
        return None


def _tf_to_interval(tf: str) -> str:
    """Convert TradingView timeframe string to Binance interval."""
    tf = str(tf).strip()
    if tf in _TF_TO_BINANCE_INTERVAL:
        return _TF_TO_BINANCE_INTERVAL[tf]
    try:
        mins = int(tf)
        if mins < 60:
            return f"{mins}m"
        if mins % 60 == 0:
            return f"{mins // 60}h"
    except ValueError:
        pass
    return "4h"


# ─── Manifest helpers ──────────────────────────────────────────────────────────

def _load_paper_only_approvals() -> list[dict]:
    try:
        with open(MANIFEST_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        approvals = data.get("approvals", [])
        return [a for a in approvals if a.get("approval_class") == "paper_only"]
    except Exception as exc:
        logger.error(f"Cannot load manifest: {exc}")
        return []


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(name).lower()).strip()


def _build_paper_lookup(approvals: list[dict]) -> dict[str, dict]:
    """Map normalised strategy name → approval entry."""
    return {_norm(a["strategy"]): a for a in approvals}


# ─── Signal DB reader ──────────────────────────────────────────────────────────

def _extract_payload(raw: str) -> dict:
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and isinstance(data.get("payload"), dict):
            return data["payload"]
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _load_signals(days: int = 30) -> list[dict]:
    """Load signals from signal_queue.db for the last N days."""
    if not SIGNAL_DB.exists():
        logger.error(f"signal_queue.db not found: {SIGNAL_DB}")
        return []
    cutoff = (datetime.now(UTC) - timedelta(days=days)).timestamp()
    signals = []
    try:
        with sqlite3.connect(str(SIGNAL_DB)) as conn:
            rows = conn.execute(
                "SELECT payload, status, created_at FROM signals WHERE created_at >= ? ORDER BY created_at ASC",
                (cutoff,),
            ).fetchall()
        for raw, status, created_at in rows:
            payload = _extract_payload(raw)
            if not payload:
                continue
            payload["_db_status"] = status
            payload["_db_ts"] = float(created_at)
            signals.append(payload)
    except Exception as exc:
        logger.error(f"signal_queue.db read error: {exc}")
    return signals


# ─── Simulation core ───────────────────────────────────────────────────────────

def _determine_action(payload: dict) -> str | None:
    """Return 'long', 'short', or 'exit' from signal payload."""
    raw = str(payload.get("action") or payload.get("signal") or payload.get("side") or "").lower()
    if any(x in raw for x in ("buy", "long", "entry_long")):
        return "long"
    if any(x in raw for x in ("sell", "short", "entry_short")):
        return "short"
    if any(x in raw for x in ("exit", "close", "flat")):
        return "exit"
    return None


def _simulate_trade(
    entry_price: float,
    side: str,          # "long" or "short"
    symbol: str,
    interval: str,
    entry_ts_ms: int,
    sl_pct: float = DEFAULT_SL_PCT,
    tp_pct: float = DEFAULT_TP_PCT,
    notional: float = DEFAULT_FIXED_NOTIONAL,
    max_candles: int = 48,
) -> dict:
    """
    Fetch candles after entry_ts_ms and walk forward until SL, TP, or timeout.
    Returns a trade result dict.
    """
    sl_price = entry_price * (1 - sl_pct / 100) if side == "long" else entry_price * (1 + sl_pct / 100)
    tp_price = entry_price * (1 + tp_pct / 100) if side == "long" else entry_price * (1 - tp_pct / 100)
    qty = notional / entry_price

    klines = _binance_klines(symbol, interval, start_ms=entry_ts_ms + 1, limit=max_candles)
    if not klines:
        return {
            "exit_reason": "no_data",
            "pnl_usd": 0.0, "pnl_pct": 0.0,
            "entry_price": entry_price, "exit_price": None,
            "bars_held": 0,
        }

    for bar_idx, kline in enumerate(klines):
        # kline format: [open_time, open, high, low, close, volume, ...]
        high = float(kline[2])
        low = float(kline[3])
        close = float(kline[4])

        if side == "long":
            if low <= sl_price:
                exit_price = sl_price
                exit_reason = "SL"
                break
            if high >= tp_price:
                exit_price = tp_price
                exit_reason = "TP"
                break
        else:  # short
            if high >= sl_price:
                exit_price = sl_price
                exit_reason = "SL"
                break
            if low <= tp_price:
                exit_price = tp_price
                exit_reason = "TP"
                break
    else:
        # Timed out — exit at last close
        exit_price = close
        exit_reason = f"timeout_{max_candles}bars"
        bar_idx = max_candles - 1

    multiplier = 1 if side == "long" else -1
    pnl_usd = qty * (exit_price - entry_price) * multiplier
    pnl_pct = (exit_price - entry_price) / entry_price * 100 * multiplier

    return {
        "exit_reason": exit_reason,
        "pnl_usd": round(pnl_usd, 4),
        "pnl_pct": round(pnl_pct, 4),
        "entry_price": round(entry_price, 6),
        "exit_price": round(exit_price, 6),
        "bars_held": bar_idx + 1,
        "sl_price": round(sl_price, 6),
        "tp_price": round(tp_price, 6),
        "qty": round(qty, 6),
        "notional": notional,
    }


# ─── Main simulation loop ──────────────────────────────────────────────────────

def run_simulation(days: int = 30, sl_pct: float = DEFAULT_SL_PCT, tp_pct: float = DEFAULT_TP_PCT) -> dict:
    """
    Simulate all paper_only signals from the last N days.
    Returns per-strategy results dict.
    """
    paper_approvals = _load_paper_only_approvals()
    if not paper_approvals:
        logger.warning("No paper_only approvals found in manifest.")
        return {}

    paper_lookup = _build_paper_lookup(paper_approvals)
    signals = _load_signals(days=days)

    logger.info(f"Loaded {len(signals)} signals from last {days} days")
    logger.info(f"Paper-only strategies in manifest: {len(paper_approvals)}")

    # Group signals by strategy+symbol, walk through in order
    # Track open positions per strategy+symbol
    open_positions: dict[str, dict] = {}  # key = "strategy|symbol"
    results: dict[str, list] = {}         # key = "strategy|symbol" → list of trade dicts

    for sig in signals:
        strat_raw = sig.get("strategy", "")
        strat_norm = _norm(strat_raw)
        symbol = str(sig.get("symbol", "")).upper()
        tf = str(sig.get("timeframe", "240")).strip()
        action = _determine_action(sig)
        ts_ms = int(sig["_db_ts"] * 1000)

        # Only process paper_only strategies
        if strat_norm not in paper_lookup:
            continue

        # Skip exit signals if no open position
        key = f"{strat_norm}|{symbol}"

        # Get entry price from payload (TV signals usually include close price)
        entry_price = None
        for price_field in ("close", "price", "entry_price", "mark_price", "last"):
            val = sig.get(price_field)
            if val is not None:
                try:
                    entry_price = float(val)
                    break
                except (TypeError, ValueError):
                    pass

        if action in ("long", "short"):
            # Close existing position first if flipping
            if key in open_positions:
                prev = open_positions.pop(key)
                # Simplified: mark existing position as closed at this signal's price
                # (signal flip exit — no P&L simulation needed for the closing side)
                prev_result = prev.get("sim_result")
                if prev_result:
                    results.setdefault(key, []).append(prev_result)

            # Open new simulated position
            if entry_price is None:
                # Fetch from Binance at signal time
                interval = _tf_to_interval(tf)
                kl = _binance_klines(symbol, interval, start_ms=ts_ms - 5 * 60 * 1000, limit=2)
                if kl:
                    entry_price = float(kl[-1][4])   # close of last completed bar
                    time.sleep(0.05)  # rate limit courtesy

            if entry_price is None or entry_price <= 0:
                logger.warning(f"No entry price for {strat_raw} {symbol} at {ts_ms} — skipping")
                continue

            interval = _tf_to_interval(tf)
            logger.info(f"  Simulating {action.upper()} {strat_raw} {symbol} @ {entry_price:.4f}")

            sim = _simulate_trade(
                entry_price=entry_price,
                side=action,
                symbol=symbol,
                interval=interval,
                entry_ts_ms=ts_ms,
                sl_pct=sl_pct,
                tp_pct=tp_pct,
                notional=DEFAULT_FIXED_NOTIONAL,
            )
            time.sleep(0.1)  # Binance rate limit courtesy

            open_positions[key] = {
                "strategy": strat_raw,
                "symbol": symbol,
                "side": action,
                "entry_price": entry_price,
                "entry_ts": sig["_db_ts"],
                "sim_result": {
                    **sim,
                    "strategy": strat_raw,
                    "symbol": symbol,
                    "side": action,
                    "entry_ts": sig["_db_ts"],
                    "entry_dt": datetime.fromtimestamp(sig["_db_ts"], UTC).isoformat(),
                },
            }

        elif action == "exit":
            if key in open_positions:
                prev = open_positions.pop(key)
                sim_result = prev.get("sim_result")
                if sim_result:
                    results.setdefault(key, []).append(sim_result)

    # Close any still-open positions (mark as pending / in-progress)
    for key, pos in open_positions.items():
        sim_result = pos.get("sim_result")
        if sim_result:
            sim_result["exit_reason"] = "still_open"
            results.setdefault(key, []).append(sim_result)

    return results


def _build_strategy_summary(results: dict) -> list[dict]:
    """Aggregate trades per strategy+symbol into a summary."""
    rows = []
    for key, trades in results.items():
        closed = [t for t in trades if t.get("exit_reason") != "still_open"]
        open_trades = [t for t in trades if t.get("exit_reason") == "still_open"]
        total_pnl = sum(t.get("pnl_usd", 0) for t in closed)
        wins = [t for t in closed if t.get("pnl_usd", 0) > 0]
        losses = [t for t in closed if t.get("pnl_usd", 0) < 0]
        strategy, symbol = key.split("|", 1)
        rows.append({
            "strategy_key": key,
            "strategy": closed[0]["strategy"] if closed else open_trades[0]["strategy"] if open_trades else strategy,
            "symbol": symbol.upper(),
            "closed_trades": len(closed),
            "open_trades": len(open_trades),
            "total_pnl_usd": round(total_pnl, 4),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_pct": round(len(wins) / len(closed) * 100, 1) if closed else 0.0,
            "avg_win_usd": round(sum(t["pnl_usd"] for t in wins) / len(wins), 4) if wins else 0.0,
            "avg_loss_usd": round(sum(t["pnl_usd"] for t in losses) / len(losses), 4) if losses else 0.0,
            "trades": trades,
        })
    rows.sort(key=lambda r: r["total_pnl_usd"], reverse=True)
    return rows


def _save_results(summary: list[dict], days: int, sl_pct: float, tp_pct: float) -> None:
    SIM_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "generated_at": datetime.now(UTC).isoformat(),
        "simulation_days": days,
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
        "fixed_notional_usd": DEFAULT_FIXED_NOTIONAL,
        "note": "Paper-only strategies simulated against Binance OHLCV. No real capital involved.",
        "strategies": summary,
    }
    SIM_RESULTS_FILE.write_text(json.dumps(out, indent=2))
    logger.info(f"Results saved: {SIM_RESULTS_FILE}")


def _print_report(summary: list[dict]) -> None:
    print()
    print("=" * 72)
    print("PAPER SIMULATION REPORT — per-strategy P&L")
    print("=" * 72)
    print(f"  Notional per trade: ${DEFAULT_FIXED_NOTIONAL:.0f} | SL/TP: configurable")
    print(f"  Source: Binance Futures OHLCV + signal_queue.db")
    print()

    header = f"{'Strategy':<35} {'Symbol':<10} {'Trades':>6} {'Open':>5} {'PnL $':>9} {'WR%':>6}"
    print(header)
    print("-" * 72)

    total_pnl = 0.0
    for row in summary:
        strat = str(row["strategy"])[:34]
        sym = str(row["symbol"])[:9]
        trades = row["closed_trades"]
        open_t = row["open_trades"]
        pnl = row["total_pnl_usd"]
        wr = row["win_rate_pct"]
        total_pnl += pnl
        flag = " [OPEN]" if open_t > 0 else ""
        print(f"{strat:<35} {sym:<10} {trades:>6} {open_t:>5} {pnl:>+9.2f} {wr:>5.1f}%{flag}")

    print("-" * 72)
    print(f"{'TOTAL':>52} {total_pnl:>+9.2f}")
    print()

    # Top winners and losers
    winners = [r for r in summary if r["total_pnl_usd"] > 0]
    losers = [r for r in summary if r["total_pnl_usd"] < 0]
    no_trades = [r for r in summary if r["closed_trades"] == 0]

    if winners:
        print(f"Best performer:  {winners[0]['strategy'][:40]}  ${winners[0]['total_pnl_usd']:+.2f}")
    if losers:
        print(f"Worst performer: {losers[-1]['strategy'][:40]}  ${losers[-1]['total_pnl_usd']:+.2f}")
    if no_trades:
        print(f"No signals fired ({len(no_trades)} strategies): " +
              ", ".join(r["strategy"][:20] for r in no_trades[:3]))
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Paper Simulation Engine — paper_only strategy P&L")
    parser.add_argument("--days", type=int, default=30, help="Look back N days for signals (default: 30)")
    parser.add_argument("--sl", type=float, default=DEFAULT_SL_PCT, help=f"Stop-loss %% (default: {DEFAULT_SL_PCT})")
    parser.add_argument("--tp", type=float, default=DEFAULT_TP_PCT, help=f"Take-profit %% (default: {DEFAULT_TP_PCT})")
    parser.add_argument("--report", action="store_true", help="Print summary table after simulation")
    parser.add_argument("--report-only", action="store_true", help="Print last saved results without re-running simulation")
    args = parser.parse_args()

    if args.report_only:
        if not SIM_RESULTS_FILE.exists():
            print("No saved results found. Run without --report-only first.")
            return 1
        saved = json.loads(SIM_RESULTS_FILE.read_text())
        _print_report(saved["strategies"])
        print(f"Generated at: {saved['generated_at']}")
        return 0

    logger.info(f"Starting paper simulation: last {args.days} days, SL={args.sl}%, TP={args.tp}%")
    results = run_simulation(days=args.days, sl_pct=args.sl, tp_pct=args.tp)

    if not results:
        print("No paper_only signals found in the specified time window.")
        return 0

    summary = _build_strategy_summary(results)
    _save_results(summary, days=args.days, sl_pct=args.sl, tp_pct=args.tp)

    if args.report or True:   # always print
        _print_report(summary)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
