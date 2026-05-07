#!/usr/bin/env python3
"""
sweep_supertrend_adx.py
=======================
Parameter sweep for Supertrend + ADX strategy on ETHUSDT 4H.

Grid:
  ST period : [7, 10, 14, 20]
  ST mult   : [1.5, 2.0, 2.5, 3.0, 3.5, 4.0]

Gate 1 hard gates (same as gate1_oos_supertrend_adx.py):
  OOS PF > 1.5, OOS n >= 50, IS/OOS <= 4x, OOS MDD >= -15%

Run: cd /home/ubuntu/tradingview_webhook_bot && python3 scripts/sweep_supertrend_adx.py
"""

from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from itertools import product

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

FIXED_NOTIONAL_USD  = 500
COMMISSION_PER_SIDE = 0.0015
OOS_SPLIT           = 0.30
ADX_PERIOD          = 14
ADX_THRESHOLD       = 20
SL_PCT  = 0.020
TP_PCT  = 0.060

OOS_PF_MIN       = 1.5
OOS_TRADES_MIN   = 50
IS_OOS_RATIO_MAX = 4.0
OOS_MDD_MAX      = -15.0

DATA_FILE   = Path("/home/ubuntu/tradingview_webhook_bot/storage/backtest_data/ETHUSDT_5y_4h.csv")
RESULTS_DIR = Path("/home/ubuntu/tradingview_webhook_bot/storage/gate1_results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

PERIOD_GRID = [7, 10, 14, 20]
MULT_GRID   = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0]


# ─── Indicators ────────────────────────────────────────────────────────────────

def compute_atr(df: pd.DataFrame, period: int) -> pd.Series:
    hi, lo, cl = df["high"], df["low"], df["close"]
    tr = pd.concat([
        hi - lo,
        (hi - cl.shift(1)).abs(),
        (lo - cl.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def compute_supertrend(df: pd.DataFrame, period: int, mult: float):
    closes = df["close"].values
    atr = compute_atr(df, period)
    hl2 = (df["high"] + df["low"]) / 2
    upper_basic = (hl2 + mult * atr).values
    lower_basic = (hl2 - mult * atr).values

    n = len(closes)
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    trend = np.zeros(n)  # 1=bull, -1=bear

    for i in range(1, n):
        if np.isnan(upper_basic[i]):
            continue
        if np.isnan(upper[i - 1]):
            upper[i] = upper_basic[i]
            lower[i] = lower_basic[i]
        else:
            upper[i] = upper_basic[i] if (upper_basic[i] < upper[i - 1] or closes[i - 1] > upper[i - 1]) else upper[i - 1]
            lower[i] = lower_basic[i] if (lower_basic[i] > lower[i - 1] or closes[i - 1] < lower[i - 1]) else lower[i - 1]

        if np.isnan(trend[i - 1]):
            trend[i] = 1 if closes[i] > upper[i] else -1
        elif trend[i - 1] == 1:
            trend[i] = -1 if closes[i] < lower[i] else 1
        else:
            trend[i] = 1 if closes[i] > upper[i] else -1

    return pd.Series(trend, index=df.index), pd.Series(upper, index=df.index), pd.Series(lower, index=df.index)


def compute_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    hi, lo, cl = df["high"], df["low"], df["close"].shift(1)
    plus_dm  = np.where((hi - hi.shift(1)) > (lo.shift(1) - lo), np.maximum(hi - hi.shift(1), 0), 0)
    minus_dm = np.where((lo.shift(1) - lo) > (hi - hi.shift(1)), np.maximum(lo.shift(1) - lo, 0), 0)
    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - df["close"].shift(1)).abs(),
                    (df["low"]  - df["close"].shift(1)).abs()], axis=1).max(axis=1)

    atr_s   = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di  = 100 * pd.Series(plus_dm,  index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr_s
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr_s
    dx       = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9)
    return dx.ewm(alpha=1 / period, adjust=False).mean()


# ─── Backtest engine ───────────────────────────────────────────────────────────

def backtest(df: pd.DataFrame, st_trend: pd.Series) -> list[dict]:
    adx = compute_adx(df, ADX_PERIOD)
    closes = df["close"].values
    highs  = df["high"].values
    lows   = df["low"].values
    trend  = st_trend.values
    adx_v  = adx.values

    trades = []
    position = 0  # 0=flat, 1=long, -1=short
    entry_price = 0.0
    entry_idx = 0

    for i in range(1, len(df)):
        if np.isnan(trend[i]) or np.isnan(adx_v[i]):
            continue

        if position == 0:
            if trend[i] == 1 and adx_v[i] > ADX_THRESHOLD:
                position = 1; entry_price = closes[i]; entry_idx = i
            elif trend[i] == -1 and adx_v[i] > ADX_THRESHOLD:
                position = -1; entry_price = closes[i]; entry_idx = i
            continue

        # Exit conditions
        sl = entry_price * (1 - SL_PCT) if position == 1 else entry_price * (1 + SL_PCT)
        tp = entry_price * (1 + TP_PCT) if position == 1 else entry_price * (1 - TP_PCT)

        exit_price = None
        if position == 1:
            if lows[i] <= sl:
                exit_price = sl
            elif highs[i] >= tp:
                exit_price = tp
            elif trend[i] == -1:
                exit_price = closes[i]
        else:
            if highs[i] >= sl:
                exit_price = sl
            elif lows[i] <= tp:
                exit_price = tp
            elif trend[i] == 1:
                exit_price = closes[i]

        if exit_price is not None:
            multiplier = 1 if position == 1 else -1
            gross_pnl = FIXED_NOTIONAL_USD * (exit_price - entry_price) / entry_price * multiplier
            cost = FIXED_NOTIONAL_USD * COMMISSION_PER_SIDE * 2
            net_pnl = gross_pnl - cost
            trades.append({
                "entry_idx": entry_idx,
                "exit_idx": i,
                "side": "long" if position == 1 else "short",
                "entry": entry_price,
                "exit": exit_price,
                "pnl": net_pnl,
            })
            position = 0


    return trades


def compute_metrics(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0, "pf": 0.0, "mdd_pct": 0.0, "roi_day": 0.0, "wr": 0.0}

    gross_w = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gross_l = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
    pf = gross_w / gross_l if gross_l > 0 else float("inf")

    equity = 0.0
    peak = 0.0
    min_dd = 0.0
    for t in trades:
        equity += t["pnl"]
        if equity > peak:
            peak = equity
        dd = (equity - peak) / max(abs(peak), 1) * 100
        if dd < min_dd:
            min_dd = dd

    total_pnl = sum(t["pnl"] for t in trades)
    n_bars = trades[-1]["exit_idx"] - trades[0]["entry_idx"] if len(trades) > 1 else 1
    n_days = n_bars * 4 / 24  # 4h candles
    roi_day = (total_pnl / FIXED_NOTIONAL_USD / max(n_days, 1)) * 100

    winners = sum(1 for t in trades if t["pnl"] > 0)
    return {
        "n":       len(trades),
        "pf":      round(pf, 3),
        "mdd_pct": round(min_dd, 2),
        "roi_day": round(roi_day, 4),
        "wr":      round(winners / len(trades) * 100, 1),
    }


# ─── Main sweep ────────────────────────────────────────────────────────────────

def run_sweep():
    if not DATA_FILE.exists():
        print(f"[ERROR] Data file not found: {DATA_FILE}")
        sys.exit(1)

    df = pd.read_csv(DATA_FILE)
    df.columns = [c.lower() for c in df.columns]
    for col in ("open", "high", "low", "close", "volume"):
        if col not in df.columns:
            raise ValueError(f"Missing column: {col}")
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.dropna(subset=["open", "high", "low", "close"], inplace=True)
    df.reset_index(drop=True, inplace=True)

    split_idx = int(len(df) * (1 - OOS_SPLIT))
    df_is  = df.iloc[:split_idx].reset_index(drop=True)
    df_oos = df.iloc[split_idx:].reset_index(drop=True)

    print(f"[sweep] ETHUSDT 4H — IS bars={len(df_is)}, OOS bars={len(df_oos)}")
    print(f"[sweep] Grid: {len(PERIOD_GRID)}×{len(MULT_GRID)}={len(PERIOD_GRID)*len(MULT_GRID)} combos")
    print()

    results = []
    for period, mult in product(PERIOD_GRID, MULT_GRID):
        st_trend_is,  _, _ = compute_supertrend(df_is,  period, mult)
        st_trend_oos, _, _ = compute_supertrend(df_oos, period, mult)

        is_trades  = backtest(df_is,  st_trend_is)
        oos_trades = backtest(df_oos, st_trend_oos)

        is_m  = compute_metrics(is_trades)
        oos_m = compute_metrics(oos_trades)

        ratio = round(is_m["pf"] / oos_m["pf"], 2) if oos_m["pf"] > 0 else 99.0

        gate_pf    = oos_m["pf"] >= OOS_PF_MIN
        gate_n     = oos_m["n"]  >= OOS_TRADES_MIN
        gate_ratio = ratio        <= IS_OOS_RATIO_MAX
        gate_mdd   = oos_m["mdd_pct"] >= OOS_MDD_MAX
        passed     = all([gate_pf, gate_n, gate_ratio, gate_mdd])

        row = {
            "period": period, "mult": mult,
            "is_n": is_m["n"],   "is_pf": is_m["pf"],   "is_mdd": is_m["mdd_pct"],
            "oos_n": oos_m["n"], "oos_pf": oos_m["pf"], "oos_mdd": oos_m["mdd_pct"],
            "oos_roi_day": oos_m["roi_day"], "oos_wr": oos_m["wr"],
            "ratio": ratio,
            "gate_pf": gate_pf, "gate_n": gate_n, "gate_ratio": gate_ratio, "gate_mdd": gate_mdd,
            "PASS": passed,
        }
        results.append(row)

        status = "PASS ✓" if passed else "FAIL"
        print(f"  period={period:2d} mult={mult:.1f} | OOS n={oos_m['n']:3d} PF={oos_m['pf']:.3f} MDD={oos_m['mdd_pct']:.1f}% ratio={ratio:.2f} | {status}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_DIR / f"sweep_supertrend_adx_ethusdt4h_{ts}.json"
    def _jsonify(obj):
        if isinstance(obj, dict):
            return {k: _jsonify(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_jsonify(v) for v in obj]
        if isinstance(obj, (np.bool_, np.integer)):
            return obj.item()
        if isinstance(obj, np.floating):
            return float(obj)
        return obj

    with open(out_path, "w") as f:
        json.dump(_jsonify({"run_ts": ts, "symbol": "ETHUSDT", "timeframe": "4h",
                   "sl_pct": SL_PCT*100, "tp_pct": TP_PCT*100,
                   "results": results}), f, indent=2)

    passes = [r for r in results if r["PASS"]]
    print()
    print(f"[sweep] {len(passes)}/{len(results)} combos passed Gate 1")
    if passes:
        best = max(passes, key=lambda r: r["oos_pf"])
        print(f"[sweep] Best PASS: period={best['period']} mult={best['mult']} OOS_PF={best['oos_pf']} ROI/day={best['oos_roi_day']}%")
    print(f"[sweep] Results saved → {out_path}")


if __name__ == "__main__":
    run_sweep()
