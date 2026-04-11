#!/usr/bin/env python3
"""
Strategy Explorer — discovers winning strategies outside the tournament
========================================================================
Runs the library defined in scripts/strategy_library_v2.py against historical
OHLCV data for every available symbol × parameter variant, computes the same
metrics as the main tournament, and outputs results to:

    storage/reports/explorer_winners.csv

This CSV uses the SAME schema as tournament_winners.csv so advanced_metrics.py
and composite_ranker.py can consume it transparently.

Pipeline:
  1. Discover symbols from storage/backtest_data/*.csv
  2. Load each OHLCV CSV
  3. For each (strategy, params) combo:
     - Generate signal array
     - Apply the same fee model + SL/TP + cooldown + WR calc as tournament
     - Compute Daily_ROI, Gross_DD, Win_Rate, Sharpe, Trades
  4. Write top performers to explorer_winners.csv

Parameters:
  --symbols    : comma list (default: BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,AVAXUSDT)
  --timeframe  : 4h or 15m (default: 15m to match tournament)
  --min-roi    : filter out strategies with Daily_ROI below this (default 0.05)
  --output     : override output CSV path
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from strategy_library_v2 import STRATEGY_REGISTRY, DEFAULT_PARAM_GRIDS  # noqa: E402

DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "AVAXUSDT"]
DATA_DIR = PROJECT_ROOT / "storage" / "backtest_data"
DEFAULT_OUTPUT = PROJECT_ROOT / "storage" / "reports" / "explorer_winners.csv"
DEFAULT_MIN_ROI_FILTER = 0.05  # include if at least 0.05% daily ROI
FEE_PER_SIDE = 0.0004  # Binance Futures taker 0.04% one side
MIN_HOLD_BARS = 2      # same as tournament
BARS_PER_DAY_15M = 96
BARS_PER_DAY_4H = 6
# Per-trade risk management (matches live orchestrator defaults)
TRADE_SL_PCT = 0.05    # -5% per-trade cap (loose vs live 0.5% to match raw backtest)
TRADE_TP_PCT = 0.15    # +15% per-trade target
TRADE_MAX_HOLD_BARS = 120  # force-exit after 120 bars even if no hit


def backtest_signal(df: pd.DataFrame, signal: np.ndarray,
                    bars_per_day: float) -> dict:
    """Explicit trade-loop backtest with SL/TP + fees.

    Walks bar-by-bar, tracks position state, applies SL/TP per trade,
    and computes equity curve + metrics in tournament CSV schema.
    """
    df = df.copy()
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    pct = np.zeros(len(df), dtype=float)

    # Convert point signals to state signals (forward-fill)
    state_signal = signal.copy().astype(int)
    current = 0
    for i in range(len(state_signal)):
        if state_signal[i] != 0:
            current = int(state_signal[i])
        else:
            state_signal[i] = current

    # Explicit trade loop
    equity = 1.0
    equity_curve = [1.0]
    in_position = 0  # +1 long, -1 short, 0 flat
    entry_px = 0.0
    bars_held = 0
    trade_pnls = []  # per-trade realized return
    cooldown = 0    # bars to skip re-entry after a forced exit

    for i in range(1, len(df)):
        sig = state_signal[i - 1]   # use prior bar's signal (no lookahead)

        # Mark-to-market if holding
        if in_position != 0:
            bars_held += 1
            trade_ret = (close[i] - entry_px) / entry_px * in_position
            # Check SL/TP using intrabar high/low (conservative)
            if in_position == 1:
                intrabar_low_ret = (low[i] - entry_px) / entry_px
                intrabar_high_ret = (high[i] - entry_px) / entry_px
                if intrabar_low_ret <= -TRADE_SL_PCT:
                    exit_ret = -TRADE_SL_PCT
                    exit_triggered = True
                elif intrabar_high_ret >= TRADE_TP_PCT:
                    exit_ret = TRADE_TP_PCT
                    exit_triggered = True
                else:
                    exit_triggered = False
            else:  # short
                intrabar_high_ret = -(high[i] - entry_px) / entry_px  # profit on fall
                intrabar_low_ret = -(low[i] - entry_px) / entry_px
                if intrabar_high_ret <= -TRADE_SL_PCT:
                    exit_ret = -TRADE_SL_PCT
                    exit_triggered = True
                elif intrabar_low_ret >= TRADE_TP_PCT:
                    exit_ret = TRADE_TP_PCT
                    exit_triggered = True
                else:
                    exit_triggered = False

            # Force exit on signal flip or max hold
            if not exit_triggered and (sig != in_position or bars_held >= TRADE_MAX_HOLD_BARS):
                exit_ret = trade_ret
                exit_triggered = True

            if exit_triggered:
                exit_ret -= 2 * FEE_PER_SIDE  # entry fee + exit fee
                equity *= (1.0 + exit_ret)
                trade_pnls.append(exit_ret)
                pct[i] = exit_ret
                in_position = 0
                entry_px = 0.0
                bars_held = 0
                cooldown = 1  # one-bar cooldown to avoid instant re-entry

        # Entry (only if flat and no cooldown)
        if in_position == 0 and cooldown == 0 and sig != 0:
            in_position = sig
            entry_px = close[i]
            bars_held = 0

        if cooldown > 0:
            cooldown -= 1

        equity_curve.append(equity)

    # Close any open position at last bar
    if in_position != 0 and len(df) > 0:
        final_ret = (close[-1] - entry_px) / entry_px * in_position - 2 * FEE_PER_SIDE
        equity *= (1.0 + final_ret)
        trade_pnls.append(final_ret)
        equity_curve[-1] = equity

    equity_arr = np.array(equity_curve)

    # ROI — annualize by trading days, convert to daily %
    total_bars = max(len(df), 1)
    total_days = max(total_bars / bars_per_day, 1)
    total_return_pct = (equity_arr[-1] - 1.0) * 100
    daily_roi = total_return_pct / total_days

    # Gross DD from equity curve
    peak = np.maximum.accumulate(equity_arr)
    dd_series = ((equity_arr - peak) / peak) * 100
    gross_dd = float(dd_series.min()) if len(dd_series) > 0 else 0.0
    net_dd = gross_dd  # simplification; same for SL/TP-managed strategies

    total_trades = len(trade_pnls)
    winning_trades = sum(1 for p in trade_pnls if p > 0)
    win_rate = round((winning_trades / total_trades * 100), 1) if total_trades > 0 else 0.0

    # Sharpe: use per-bar returns from equity delta
    equity_returns = np.diff(equity_arr) / equity_arr[:-1]
    mean_ret = equity_returns.mean() if len(equity_returns) > 0 else 0
    std_ret = equity_returns.std() if len(equity_returns) > 0 else 0
    ann_factor = bars_per_day * 365
    sharpe = round(float((mean_ret / std_ret) * np.sqrt(ann_factor)), 2) if std_ret > 1e-9 else 0.0

    # OOS split — use last 30% of the equity curve
    split = int(len(equity_arr) * 0.7)
    oos_equity = equity_arr[split:]
    if len(oos_equity) > 1:
        oos_return_pct = (oos_equity[-1] / oos_equity[0] - 1.0) * 100
        oos_days = max(len(oos_equity) / bars_per_day, 1)
        oos_roi = oos_return_pct / oos_days
        oos_peak = np.maximum.accumulate(oos_equity)
        oos_dd = float(((oos_equity - oos_peak) / oos_peak * 100).min())
        oos_ret_series = np.diff(oos_equity) / oos_equity[:-1]
        if oos_ret_series.std() > 1e-9:
            oos_sharpe = round(float((oos_ret_series.mean() / oos_ret_series.std()) * np.sqrt(ann_factor)), 2)
        else:
            oos_sharpe = 0.0
    else:
        oos_roi = 0.0
        oos_dd = 0.0
        oos_sharpe = 0.0

    return {
        "Daily_ROI_%": round(daily_roi, 3),
        "Gross_DD_%": round(gross_dd, 2),
        "Net_DD_%": round(net_dd, 2),
        "Max_DD_%": round(gross_dd, 2),
        "GDD_Date": "",
        "GDD_Capital_Left": 0,
        "NDD_Date": "",
        "NDD_Capital_Left": 0,
        "Win_Rate_%": win_rate,
        "Sharpe_Ratio": sharpe,
        "Total_Trades": total_trades,
        "Tier": "V2_EXPLORER",
        "Optimal_Mult": 0,
        "Optimal_Len": 0,
        "OOS_Daily_ROI_%": round(oos_roi, 3),
        "OOS_Gross_DD_%": round(oos_dd, 2),
        "OOS_Sharpe": oos_sharpe,
    }


def load_ohlcv(symbol: str, timeframe: str) -> pd.DataFrame | None:
    # Look for files matching the symbol and timeframe
    for pattern in (f"{symbol}_3y_{timeframe}.csv", f"{symbol}_{timeframe}.csv"):
        p = DATA_DIR / pattern
        if p.exists():
            df = pd.read_csv(p)
            if "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"])
            df.columns = [c.lower() for c in df.columns]
            return df
    return None


def format_params(params: dict) -> str:
    return ",".join(f"{k}={v}" for k, v in params.items())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--timeframe", default="15m")
    parser.add_argument("--min-roi", type=float, default=DEFAULT_MIN_ROI_FILTER)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    bars_per_day = BARS_PER_DAY_4H if args.timeframe == "4h" else BARS_PER_DAY_15M

    all_rows = []
    scanned = 0

    for symbol in symbols:
        df = load_ohlcv(symbol, args.timeframe)
        if df is None:
            if not args.quiet:
                print(f"SKIP {symbol}: no data file")
            continue

        if not args.quiet:
            print(f"Exploring {symbol} ({len(df)} rows)")

        for strat_name, strat_func in STRATEGY_REGISTRY.items():
            param_grids = DEFAULT_PARAM_GRIDS.get(strat_name, [{}])
            for params in param_grids:
                try:
                    sig = strat_func(df, **params)
                    if sig is None or len(sig) != len(df):
                        continue
                    metrics = backtest_signal(df, np.asarray(sig), bars_per_day)
                    scanned += 1
                    if metrics["Daily_ROI_%"] < args.min_roi:
                        continue
                    label = f"{strat_name}[{format_params(params)}]"
                    row = {
                        "Symbol": symbol,
                        "Strategy": label,
                        **metrics,
                    }
                    all_rows.append(row)
                except Exception as exc:
                    if not args.quiet:
                        print(f"  ERROR {strat_name}{params} on {symbol}: {exc}")

    if not all_rows:
        print("WARNING: explorer found 0 rows matching min-roi filter")
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame().to_csv(out_path, index=False)
        return 0

    out = pd.DataFrame(all_rows)
    out = out.sort_values("Daily_ROI_%", ascending=False)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)

    if not args.quiet:
        print()
        print(f"Scanned: {scanned} strategy/param combos across {len(symbols)} symbols")
        print(f"Above min-roi={args.min_roi}: {len(out)}")
        print(f"Written: {out_path}")
        print()
        print("Top 10 by Daily_ROI_%:")
        cols = ["Symbol", "Strategy", "Daily_ROI_%", "Gross_DD_%", "Win_Rate_%",
                "Total_Trades", "Sharpe_Ratio"]
        print(out[cols].head(10).to_string(index=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
