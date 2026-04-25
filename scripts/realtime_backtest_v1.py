#!/usr/bin/env python3
"""
realtime_backtest_v1.py
=======================
Evidence-grade backtest engine with all realism fixes applied.

Fixes vs backtest_engine_v4 / paper_sim_engine
───────────────────────────────────────────────────────────────────────────────
 PROBLEM                        OLD ENGINE             THIS ENGINE
 ─────────────────────────────  ─────────────────────  ─────────────────────
 Data leakage                   entry at bar-i close   entry at bar-(i+1) open
 Slippage                       zero                   per-symbol tier model
 Position sizing                95% equity compound    fixed notional ($500)
 Paper sim SL/TP                hardcoded 3%/5%        reads env vars
 Walk-forward validation        none (single split)    3-fold anchored WFA
 TP calibration                 single value           parametric sweep
───────────────────────────────────────────────────────────────────────────────

Strategies implemented (Python equivalents of Pine Script logic):
  CCI Trend    — CCI(20) crossover ±0, EMA(200) trend filter, long+short
  Donchian Trend — DC(20) channel breakout, RSI(14) filter, long+short

Run:
    python scripts/realtime_backtest_v1.py
    python scripts/realtime_backtest_v1.py --symbol ETHUSDT --tf 4h
    python scripts/realtime_backtest_v1.py --tp-sweep   # sweep TP values
    python scripts/realtime_backtest_v1.py --wfa        # walk-forward only
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

UTC = timezone.utc

# ── Default live params (read from env_vars if available) ─────────────────────
def _env(key: str, default: str) -> str:
    env_file = Path("/etc/tradingbot/env_vars")
    if env_file.exists():
        for line in env_file.read_text(errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() == key:
                return v.strip().strip('"').strip("'")
    return os.getenv(key, default)

LIVE_SL_PCT        = float(_env("STOP_LOSS_PCT",    "2.0")) / 100.0
LIVE_TP_PCT        = float(_env("TAKE_PROFIT_PCT", "12.0")) / 100.0
LIVE_LEVERAGE      = float(_env("LEVERAGE", "2"))
FIXED_NOTIONAL_USD = 500.0       # matches manifest backtest_hash provenance
COMMISSION_SIDE    = 0.0006      # 0.06% per side (Binance futures taker)

# ── Slippage tiers (added on top of commission) ───────────────────────────────
# Based on average daily volume and spread. ETH is liquid; altcoins are not.
SLIPPAGE_TIERS: dict[str, float] = {
    "ETHUSDT":   0.0008,   # 0.08% per side  → 0.28% round-trip total
    "BTCUSDT":   0.0006,   # 0.06% per side  → 0.24% round-trip total
    "SOLUSDT":   0.0010,   # 0.10% per side  → 0.32% round-trip total
    "XRPUSDT":   0.0012,   # 0.12% per side  → 0.36% round-trip total
    "LINKUSDT":  0.0015,   # 0.15% per side  → 0.42% round-trip total
    "DEFAULT":   0.0018,   # 0.18% per side  → 0.48% round-trip total (altcoins)
}

DATA_DIR   = PROJECT_ROOT / "storage" / "backtest_data"
REPORT_DIR = PROJECT_ROOT / "storage" / "reports" / "realtime_backtest"


# ─── Indicator helpers ────────────────────────────────────────────────────────

def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()

def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(n).mean()
    loss  = (-delta.clip(upper=0)).rolling(n).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100.0 - 100.0 / (1.0 + rs)

def _cci(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 20) -> pd.Series:
    tp    = (high + low + close) / 3.0
    ma    = tp.rolling(n).mean()
    md    = tp.rolling(n).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    return (tp - ma) / (0.015 * md)


# ─── Signal generators ────────────────────────────────────────────────────────

def signals_cci_trend(df: pd.DataFrame) -> pd.Series:
    """
    CCI Trend — Python equivalent of Pine Script CCI crossover strategy.

    Long entry  : CCI(20) crosses above 0  AND  close > EMA(200)
    Short entry : CCI(20) crosses below 0  AND  close < EMA(200)
    Exit        : managed by backtest engine (SL / TP / trail)

    Entry-only signals (fire once per crossover, no persistent regime).
    All indicators computed on confirmed previous-bar data — no lookahead.
    """
    cci   = _cci(df["high"], df["low"], df["close"], 20)
    ema200 = _ema(df["close"], 200)

    # prev bar CCI and trend filter to avoid lookahead
    cci_prev = cci.shift(1)
    trend_ok_long  = df["close"] > ema200
    trend_ok_short = df["close"] < ema200

    long_cross  = (cci > 0) & (cci_prev <= 0) & trend_ok_long
    short_cross = (cci < 0) & (cci_prev >= 0) & trend_ok_short

    sig = np.zeros(len(df), dtype=int)
    sig = np.where(long_cross,  1,  sig)
    sig = np.where(short_cross, -1, sig)
    return pd.Series(sig, index=df.index, name="sig")


def signals_donchian_trend(df: pd.DataFrame) -> pd.Series:
    """
    Donchian Trend — matches donchian_backtest_v2.py signal logic.

    Long entry  : close crosses above 20-bar DC high (prev bar) AND RSI < 70
    Short entry : close crosses below 20-bar DC low  (prev bar) AND RSI > 30
    """
    dc_high = df["close"].rolling(20).max().shift(1)
    dc_low  = df["close"].rolling(20).min().shift(1)
    rsi     = _rsi(df["close"], 14)

    long_cross  = (df["close"] > dc_high) & (df["close"].shift(1) <= dc_high.shift(1))
    short_cross = (df["close"] < dc_low)  & (df["close"].shift(1) >= dc_low.shift(1))

    sig = np.zeros(len(df), dtype=int)
    sig = np.where(long_cross  & (rsi < 70),  1,  sig)
    sig = np.where(short_cross & (rsi > 30), -1,  sig)
    return pd.Series(sig, index=df.index, name="sig")


STRATEGIES = {
    "CCI Trend":      signals_cci_trend,
    "Donchian Trend": signals_donchian_trend,
}


# ─── Core simulation (FIXED: next-bar-open entry, fixed notional, slippage) ──

def simulate(
    df: pd.DataFrame,
    sig: pd.Series,
    symbol: str     = "ETHUSDT",
    sl_pct: float   = LIVE_SL_PCT,
    tp_pct: float   = LIVE_TP_PCT,
    trail_pct: float = 0.04,
    leverage: float  = LIVE_LEVERAGE,
    notional: float  = FIXED_NOTIONAL_USD,
    min_gap_bars: int = 2,
) -> dict:
    """
    Simulate trades with ALL realism fixes applied.

    KEY FIXES vs old engine:
    1. Entry at bar[i+1] open  → eliminates bar-close lookahead
    2. Fixed notional per trade → no infinite compounding
    3. Per-symbol slippage      → realistic friction model
    4. Commission both sides    → correct P&L
    """
    slip   = SLIPPAGE_TIERS.get(symbol.upper(), SLIPPAGE_TIERS["DEFAULT"])
    total_friction_per_side = COMMISSION_SIDE + slip   # fee + slippage
    round_trip_cost_pct     = total_friction_per_side * 2

    close_arr = df["close"].values.astype(float)
    open_arr  = df["open"].values.astype(float)
    high_arr  = df["high"].values.astype(float)
    low_arr   = df["low"].values.astype(float)
    sig_arr   = sig.values.astype(int)
    n         = len(df)

    dates = None
    if "timestamp" in df.columns:
        try:
            dates = pd.to_datetime(df["timestamp"]).dt.date.values
        except Exception:
            pass

    position       = 0
    entry_price    = 0.0
    entry_bar      = -1
    trail_stop     = 0.0
    last_exit_bar  = -min_gap_bars - 1
    trades         = []
    daily_pnl      = {}

    for i in range(1, n - 1):   # stop at n-2 so entry at open[i+1] is valid
        hi  = high_arr[i]
        lo  = low_arr[i]
        sig_i = sig_arr[i]

        # ── EXIT logic (check current bar high/low for SL/TP) ─────────────────
        if position != 0:
            exit_px = None

            if position == 1:
                sl_lvl = entry_price * (1.0 - sl_pct)
                tp_lvl = entry_price * (1.0 + tp_pct)
                if trail_pct > 0.0:
                    trail_stop = max(trail_stop, close_arr[i] * (1.0 - trail_pct))
                if lo <= sl_lvl:
                    exit_px = sl_lvl
                elif hi >= tp_lvl:
                    exit_px = tp_lvl
                elif trail_pct > 0.0 and lo <= trail_stop:
                    exit_px = trail_stop
                elif sig_i == -1:
                    exit_px = open_arr[i + 1]   # reversal exits at next open

            elif position == -1:
                sl_lvl = entry_price * (1.0 + sl_pct)
                tp_lvl = entry_price * (1.0 - tp_pct)
                if trail_pct > 0.0:
                    trail_stop = min(trail_stop, close_arr[i] * (1.0 + trail_pct))
                if hi >= sl_lvl:
                    exit_px = sl_lvl
                elif lo <= tp_lvl:
                    exit_px = tp_lvl
                elif trail_pct > 0.0 and hi >= trail_stop:
                    exit_px = trail_stop
                elif sig_i == 1:
                    exit_px = open_arr[i + 1]

            if exit_px is not None:
                if position == 1:
                    ret_pct = (exit_px - entry_price) / entry_price * leverage
                else:
                    ret_pct = (entry_price - exit_px) / entry_price * leverage
                # P&L = notional × return − round-trip friction on notional
                pnl = notional * ret_pct - notional * round_trip_cost_pct * leverage
                trades.append({
                    "entry_bar":  entry_bar,
                    "exit_bar":   i,
                    "entry_price": entry_price,
                    "exit_price": exit_px,
                    "side":       "long" if position == 1 else "short",
                    "ret_pct":    ret_pct,
                    "pnl_usd":    pnl,
                })
                if dates is not None:
                    d = str(dates[i])
                    daily_pnl[d] = daily_pnl.get(d, 0.0) + pnl
                position      = 0
                last_exit_bar = i
                trail_stop    = 0.0

        # ── ENTRY logic (enter at NEXT bar's open — FIXES DATA LEAKAGE) ───────
        if position == 0 and sig_i != 0 and (i - last_exit_bar) > min_gap_bars:
            # FIX: use open_arr[i+1] not close_arr[i]
            entry_price = open_arr[i + 1]
            position    = sig_i
            entry_bar   = i
            trail_stop  = (entry_price * (1.0 - trail_pct) if position == 1
                           else entry_price * (1.0 + trail_pct))

    # ── Metrics ───────────────────────────────────────────────────────────────
    if not trades:
        return {"trades": 0, "error": "no_trades"}

    pnl_arr  = np.array([t["pnl_usd"] for t in trades])
    ret_arr  = np.array([t["ret_pct"] for t in trades])
    wins     = pnl_arr > 0
    losses   = pnl_arr < 0

    total_trades  = len(trades)
    win_rate      = float(wins.sum()) / total_trades * 100.0
    gross_profit  = float(pnl_arr[wins].sum()) if wins.any() else 0.0
    gross_loss    = float(abs(pnl_arr[losses].sum())) if losses.any() else 1e-9
    profit_factor = gross_profit / gross_loss
    total_pnl     = float(pnl_arr.sum())
    avg_win       = float(pnl_arr[wins].mean())  if wins.any()   else 0.0
    avg_loss      = float(pnl_arr[losses].mean()) if losses.any() else 0.0
    expectancy    = float(pnl_arr.mean())

    # Equity curve (starting from 0 — fixed notional, no compounding)
    equity    = np.cumsum(np.concatenate([[0], pnl_arr]))
    peak      = np.maximum.accumulate(equity)
    dd        = equity - peak
    max_dd    = float(dd.min())

    # Sharpe (daily returns √252)
    sharpe = 0.0
    if daily_pnl and len(daily_pnl) >= 20:
        dp   = pd.Series(daily_pnl)
        mean = dp.mean()
        std  = dp.std()
        if std > 0:
            sharpe = float(mean / std * (252 ** 0.5))

    # CAGR — on fixed notional basis, annualised
    if df is not None and "timestamp" in df.columns:
        try:
            t0 = pd.to_datetime(df["timestamp"].iloc[0])
            t1 = pd.to_datetime(df["timestamp"].iloc[-1])
            years = (t1 - t0).days / 365.25
        except Exception:
            years = 3.0
    else:
        years = 3.0

    # Annual P&L / notional × 100 = annual ROI%
    annual_roi = (total_pnl / years / notional) * 100.0 if years > 0 else 0.0

    return {
        "trades":         total_trades,
        "win_rate_pct":   round(win_rate,  2),
        "profit_factor":  round(profit_factor, 3),
        "total_pnl_usd":  round(total_pnl, 2),
        "annual_roi_pct": round(annual_roi, 2),
        "max_dd_usd":     round(max_dd, 2),
        "sharpe":         round(sharpe, 3),
        "avg_win_usd":    round(avg_win, 2),
        "avg_loss_usd":   round(avg_loss, 2),
        "expectancy_usd": round(expectancy, 2),
        "sl_pct":         round(sl_pct * 100, 2),
        "tp_pct":         round(tp_pct * 100, 2),
        "round_trip_cost_pct": round(round_trip_cost_pct * 100, 3),
        "notional":       notional,
        "leverage":       leverage,
        "trade_list":     trades,
    }


# ─── Walk-Forward Analysis ────────────────────────────────────────────────────

def run_wfa(
    df: pd.DataFrame,
    signal_fn,
    symbol: str,
    sl_pct: float = LIVE_SL_PCT,
    tp_pct: float = LIVE_TP_PCT,
    n_folds: int  = 3,
    oos_frac: float = 0.2,  # 20% of total data per OOS fold
) -> list[dict]:
    """
    Anchored walk-forward: training window grows, OOS window rolls forward.

    With 3 years of 4H data (~6576 bars):
      Fold 1: Train bar 0–3945  OOS bar 3945–5261   (train ~60%, oos ~20%)
      Fold 2: Train bar 0–4608  OOS bar 4608–5924   (train ~70%, oos ~20%)
      Fold 3: Train bar 0–5271  OOS bar 5271–6576   (train ~80%, oos ~20%)

    No parameter optimization here — parameters are FIXED (SL/TP from env).
    WFA shows whether the strategy degrades on truly unseen data.
    """
    total = len(df)
    oos_size = int(total * oos_frac)
    fold_results = []

    for fold in range(n_folds):
        # Anchored: train always starts from 0, OOS window rolls
        oos_start = total - oos_size * (n_folds - fold)
        oos_end   = oos_start + oos_size
        if oos_start < 500 or oos_end > total:
            continue

        df_train = df.iloc[:oos_start].copy().reset_index(drop=True)
        df_oos   = df.iloc[oos_start:oos_end].copy().reset_index(drop=True)

        sig_train = signal_fn(df_train)
        sig_oos   = signal_fn(df_oos)

        r_train = simulate(df_train, sig_train, symbol=symbol, sl_pct=sl_pct, tp_pct=tp_pct)
        r_oos   = simulate(df_oos,   sig_oos,   symbol=symbol, sl_pct=sl_pct, tp_pct=tp_pct)

        ts_start = df_oos["timestamp"].iloc[0]  if "timestamp" in df_oos.columns else f"fold_{fold}"
        ts_end   = df_oos["timestamp"].iloc[-1] if "timestamp" in df_oos.columns else ""

        fold_results.append({
            "fold":          fold + 1,
            "oos_start":     str(ts_start),
            "oos_end":       str(ts_end),
            "train_trades":  r_train.get("trades", 0),
            "train_pf":      r_train.get("profit_factor", 0),
            "train_wr_pct":  r_train.get("win_rate_pct", 0),
            "oos_trades":    r_oos.get("trades", 0),
            "oos_pf":        r_oos.get("profit_factor", 0),
            "oos_wr_pct":    r_oos.get("win_rate_pct", 0),
            "oos_pnl_usd":   r_oos.get("total_pnl_usd", 0),
            "oos_sharpe":    r_oos.get("sharpe", 0),
            "verdict":       "PASS" if r_oos.get("profit_factor", 0) > 1.0 else "FAIL",
        })

    return fold_results


# ─── TP sweep ─────────────────────────────────────────────────────────────────

def tp_sweep(df: pd.DataFrame, signal_fn, symbol: str, sl_pct: float) -> list[dict]:
    """Find the TP% that maximises expected value per trade."""
    tp_values = [0.03, 0.04, 0.05, 0.06, 0.08, 0.10, 0.12, 0.15]
    results = []
    for tp in tp_values:
        r = simulate(df, signal_fn(df), symbol=symbol, sl_pct=sl_pct, tp_pct=tp)
        if r.get("trades", 0) >= 5:
            results.append({
                "tp_pct":        round(tp * 100, 1),
                "trades":        r["trades"],
                "win_rate_pct":  r["win_rate_pct"],
                "profit_factor": r["profit_factor"],
                "total_pnl_usd": r["total_pnl_usd"],
                "expectancy":    r["expectancy_usd"],
                "sharpe":        r["sharpe"],
            })
    return results


# ─── Report printer ───────────────────────────────────────────────────────────

def _bar(label: str, width: int = 70) -> str:
    return f"\n{'─' * width}\n  {label}\n{'─' * width}"

def print_report(full_results: dict) -> None:
    print("\n" + "═" * 70)
    print("  REALTIME BACKTEST v1  —  Evidence-Grade Report")
    print(f"  Generated: {full_results['generated_at']}")
    print("═" * 70)

    cfg = full_results["config"]
    print(f"\n  Symbol : {cfg['symbol']}  |  Timeframe : {cfg['timeframe']}")
    print(f"  SL     : {cfg['sl_pct']}%  |  TP (live) : {cfg['tp_pct']}%")
    print(f"  Notional: ${cfg['notional_usd']} fixed  |  Leverage : {cfg['leverage']}x")
    print(f"  Slippage: {cfg['slippage_pct_per_side']}%/side  |  Commission: {cfg['commission_pct_per_side']}%/side")
    print(f"  Round-trip friction: {cfg['round_trip_total_pct']}%")

    for strat_name, strat_data in full_results["strategies"].items():
        print(_bar(f"STRATEGY: {strat_name}"))

        full = strat_data["full_backtest"]
        if "error" in full:
            print(f"  ERROR: {full['error']}")
            continue

        print(f"\n  FULL BACKTEST (3-year, next-bar-open, fixed notional, real slippage)")
        print(f"  Trades         : {full['trades']}")
        print(f"  Win Rate       : {full['win_rate_pct']}%")
        print(f"  Profit Factor  : {full['profit_factor']}")
        print(f"  Total P&L      : ${full['total_pnl_usd']:,.2f}")
        print(f"  Annual ROI     : {full['annual_roi_pct']}%  (on ${full['notional']} notional)")
        print(f"  Max Drawdown   : ${full['max_dd_usd']:,.2f}")
        print(f"  Sharpe (√252)  : {full['sharpe']}")
        print(f"  Avg Win        : ${full['avg_win_usd']:.2f}  |  Avg Loss: ${full['avg_loss_usd']:.2f}")
        print(f"  Expectancy     : ${full['expectancy_usd']:.2f} per trade")

        # WFA
        wfa = strat_data.get("wfa", [])
        if wfa:
            print(f"\n  WALK-FORWARD ANALYSIS ({len(wfa)} folds, anchored, OOS only shown)")
            print(f"  {'Fold':<6} {'OOS Period':<25} {'Trades':>7} {'WR%':>7} {'PF':>6} {'PnL':>9} {'Sharpe':>7} {'Verdict'}")
            print(f"  {'─'*6} {'─'*25} {'─'*7} {'─'*7} {'─'*6} {'─'*9} {'─'*7} {'─'*7}")
            all_pass = True
            for f in wfa:
                period = f["oos_start"][:10] + " → " + f["oos_end"][:10]
                verdict = f["verdict"]
                if verdict == "FAIL":
                    all_pass = False
                print(f"  {f['fold']:<6} {period:<25} {f['oos_trades']:>7} "
                      f"{f['oos_wr_pct']:>7.1f} {f['oos_pf']:>6.3f} "
                      f"${f['oos_pnl_usd']:>8.2f} {f['oos_sharpe']:>7.3f} {verdict}")
            wfa_verdict = "CONSISTENT EDGE" if all_pass else "OVERFITTING RISK — NOT CONSISTENT"
            print(f"\n  WFA Verdict: {wfa_verdict}")

        # TP sweep
        sweep = strat_data.get("tp_sweep", [])
        if sweep:
            print(f"\n  TP SWEEP  (SL fixed at {full['sl_pct']}%)")
            print(f"  {'TP%':<7} {'Trades':>7} {'WR%':>7} {'PF':>7} {'PnL':>10} {'Expect':>9} {'Sharpe':>7}")
            print(f"  {'─'*7} {'─'*7} {'─'*7} {'─'*7} {'─'*10} {'─'*9} {'─'*7}")
            best = max(sweep, key=lambda x: x["expectancy"])
            for row in sweep:
                marker = " ← OPTIMAL" if row["tp_pct"] == best["tp_pct"] else ""
                live_m = " ← LIVE"    if abs(row["tp_pct"] - cfg["tp_pct"]) < 0.1 else ""
                print(f"  {row['tp_pct']:<7.1f} {row['trades']:>7} {row['win_rate_pct']:>7.1f} "
                      f"{row['profit_factor']:>7.3f} ${row['total_pnl_usd']:>9.2f} "
                      f"${row['expectancy']:>8.2f} {row['sharpe']:>7.3f}{marker}{live_m}")

    print("\n" + "═" * 70)
    print("  VERDICT SUMMARY")
    print("═" * 70)
    for strat_name, strat_data in full_results["strategies"].items():
        full = strat_data.get("full_backtest", {})
        pf   = full.get("profit_factor", 0)
        wfa  = strat_data.get("wfa", [])
        wfa_ok = all(f["verdict"] == "PASS" for f in wfa) if wfa else None
        verdict = (
            "DEPLOY-READY"   if pf > 1.2 and wfa_ok is True  else
            "MONITOR-ONLY"   if pf > 1.0 and wfa_ok is not False else
            "PAPER-ONLY"     if pf > 1.0 else
            "REJECT"
        )
        print(f"  {strat_name:<25} PF={pf:.3f}  WFA={'PASS' if wfa_ok else 'FAIL' if wfa_ok is False else 'N/A'}  → {verdict}")
    print("═" * 70 + "\n")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Evidence-grade backtest engine v1")
    ap.add_argument("--symbol",   default="ETHUSDT")
    ap.add_argument("--tf",       default="4h")
    ap.add_argument("--sl",       type=float, default=None, help="SL%% (default: from env)")
    ap.add_argument("--tp",       type=float, default=None, help="TP%% (default: from env)")
    ap.add_argument("--tp-sweep", action="store_true")
    ap.add_argument("--wfa",      action="store_true")
    ap.add_argument("--no-wfa",   action="store_true")
    ap.add_argument("--strategies", nargs="*", default=list(STRATEGIES.keys()))
    args = ap.parse_args()

    sl_pct = (args.sl / 100.0) if args.sl else LIVE_SL_PCT
    tp_pct = (args.tp / 100.0) if args.tp else LIVE_TP_PCT
    sym    = args.symbol.upper()
    tf     = args.tf.lower().replace("h", "h")

    # Map tf → file suffix
    tf_map = {"4h": "4h", "1h": "1h", "15m": "15m", "15": "15m"}
    tf_key = tf_map.get(tf, "4h")

    data_file = DATA_DIR / f"{sym}_3y_{tf_key}.csv"
    if not data_file.exists():
        print(f"ERROR: Data file not found: {data_file}")
        sys.exit(1)

    df = pd.read_csv(data_file)
    df.columns = [c.lower() for c in df.columns]
    print(f"Loaded {len(df)} bars  |  {df['timestamp'].iloc[0]} → {df['timestamp'].iloc[-1]}")

    slip      = SLIPPAGE_TIERS.get(sym, SLIPPAGE_TIERS["DEFAULT"])
    round_trip = (COMMISSION_SIDE + slip) * 2

    config = {
        "symbol":                  sym,
        "timeframe":               tf_key,
        "sl_pct":                  round(sl_pct * 100, 2),
        "tp_pct":                  round(tp_pct * 100, 2),
        "notional_usd":            FIXED_NOTIONAL_USD,
        "leverage":                LIVE_LEVERAGE,
        "commission_pct_per_side": round(COMMISSION_SIDE * 100, 3),
        "slippage_pct_per_side":   round(slip * 100, 3),
        "round_trip_total_pct":    round(round_trip * 100, 3),
        "entry_execution":         "next_bar_open (no lookahead)",
        "sizing":                  f"fixed_${FIXED_NOTIONAL_USD}_notional",
    }

    strategies_output: dict[str, dict] = {}

    do_wfa   = not args.no_wfa
    do_sweep = args.tp_sweep

    for strat_name in args.strategies:
        if strat_name not in STRATEGIES:
            print(f"Unknown strategy: {strat_name}. Options: {list(STRATEGIES)}")
            continue

        print(f"\nRunning: {strat_name} on {sym} {tf_key}...")
        sig_fn = STRATEGIES[strat_name]
        sig    = sig_fn(df)

        full = simulate(df, sig, symbol=sym, sl_pct=sl_pct, tp_pct=tp_pct)
        # Remove trade list from report (keep metrics only)
        trade_list = full.pop("trade_list", [])

        wfa_results = []
        if do_wfa:
            print(f"  Running WFA ({3} folds)...")
            wfa_results = run_wfa(df, sig_fn, symbol=sym, sl_pct=sl_pct, tp_pct=tp_pct)

        sweep_results = []
        if do_sweep:
            print(f"  Running TP sweep...")
            sweep_results = tp_sweep(df, sig_fn, symbol=sym, sl_pct=sl_pct)

        strategies_output[strat_name] = {
            "full_backtest": full,
            "wfa":           wfa_results,
            "tp_sweep":      sweep_results,
            "trade_count_detail": {
                "total":  len(trade_list),
                "wins":   sum(1 for t in trade_list if t["pnl_usd"] > 0),
                "losses": sum(1 for t in trade_list if t["pnl_usd"] < 0),
            },
        }

    output = {
        "generated_at": datetime.now(UTC).isoformat(),
        "config":       config,
        "strategies":   strategies_output,
    }

    print_report(output)

    # Save JSON report
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ts   = datetime.now(UTC).strftime("%Y%m%d_%H%M")
    out_path = REPORT_DIR / f"backtest_{sym}_{tf_key}_{ts}.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"  Report saved → {out_path}")

    # Also write latest symlink
    latest_path = REPORT_DIR / "latest.json"
    with open(latest_path, "w") as f:
        json.dump(output, f, indent=2, default=str)


if __name__ == "__main__":
    main()
