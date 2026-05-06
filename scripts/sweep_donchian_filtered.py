#!/usr/bin/env python3
"""
sweep_donchian_filtered.py
==========================
Takes the ONLY proven strategy (Donchian_40 on ETHUSDT 4H, OOS PF=1.73 PASS)
and tests 6 confirmation filters on top of it. Original Donchian entry/exit
logic is preserved — only an extra "allow trade" gate is added.

Filters tested (each on top of baseline Donchian):
  1. EMA_21_55 bullish / bearish agreement
  2. EMA_9_21 agreement
  3. MACD agreement
  4. RSI_50 agreement (RSI>50 for longs, <50 for shorts)
  5. ADX > 20 (trend strength)
  6. Supertrend agreement
  7. Vortex agreement
  8. MACD + EMA_21_55 (both must agree)
  9. MACD + Supertrend
 10. EMA_21_55 + Supertrend
 11. EMA_21_55 + Vortex
 12. MACD + RSI_50
 + baseline (no filter) as reference

Donchian original logic:
  Entry: close > DC_upper(40)[1] → long | close < DC_lower(40)[1] → short
  Exit:  SL=2%  |  TP=4%  |  opposite channel breakout (close < DC_lower[1] for long)

Gate 1: OOS PF >= 1.5, OOS n >= 50, IS/OOS <= 4.0, OOS MDD >= -15%

Run:
  cd /home/ubuntu/tradingview_webhook_bot
  python3 scripts/sweep_donchian_filtered.py
"""

from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

FIXED_NOTIONAL_USD  = 500.0
COMMISSION_PER_SIDE = 0.0015
OOS_SPLIT           = 0.30
SL_PCT              = 0.020
TP_PCT              = 0.040
DC_PERIOD           = 40   # Donchian channel period

OOS_PF_MIN       = 1.5
OOS_TRADES_MIN   = 50
IS_OOS_RATIO_MAX = 4.0
OOS_MDD_MAX      = -15.0

DATA_FILE   = Path("/home/ubuntu/tradingview_webhook_bot/storage/backtest_data/ETHUSDT_5y_4h.csv")
RESULTS_DIR = Path("/home/ubuntu/tradingview_webhook_bot/storage/gate1_results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


# ─── Indicator helpers ────────────────────────────────────────────────────────

def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    loss  = (-delta).clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    return 100 - 100 / (1 + gain / (loss + 1e-9))


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    hi, lo, cl = df["high"], df["low"], df["close"]
    tr = pd.concat([(hi-lo), (hi-cl.shift()).abs(), (lo-cl.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()


def _supertrend(df: pd.DataFrame, period: int = 10, mult: float = 3.0) -> pd.Series:
    closes  = df["close"].values
    atr     = _atr(df, period)
    hl2     = (df["high"] + df["low"]) / 2
    upper_b = (hl2 + mult * atr).values
    lower_b = (hl2 - mult * atr).values
    n = len(closes)
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    trend = np.zeros(n)
    for i in range(1, n):
        if np.isnan(upper_b[i]):
            continue
        if np.isnan(upper[i-1]):
            upper[i] = upper_b[i]; lower[i] = lower_b[i]
        else:
            upper[i] = upper_b[i] if (upper_b[i] < upper[i-1] or closes[i-1] > upper[i-1]) else upper[i-1]
            lower[i] = lower_b[i] if (lower_b[i] > lower[i-1] or closes[i-1] < lower[i-1]) else lower[i-1]
        if trend[i-1] == 1:
            trend[i] = -1 if closes[i] < lower[i] else 1
        else:
            trend[i] = 1 if closes[i] > upper[i] else -1
    return pd.Series(trend.astype(int), index=df.index)


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    hi, lo = df["high"], df["low"]
    plus_dm  = np.where((hi - hi.shift(1)) > (lo.shift(1) - lo), np.maximum(hi - hi.shift(1), 0), 0)
    minus_dm = np.where((lo.shift(1) - lo) > (hi - hi.shift(1)), np.maximum(lo.shift(1) - lo, 0), 0)
    atr_s    = _atr(df, period)
    pdi  = 100 * pd.Series(plus_dm,  index=df.index).ewm(alpha=1/period, adjust=False).mean() / (atr_s + 1e-9)
    mdi  = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1/period, adjust=False).mean() / (atr_s + 1e-9)
    dx   = 100 * (pdi - mdi).abs() / (pdi + mdi + 1e-9)
    return dx.ewm(alpha=1/period, adjust=False).mean(), pdi, mdi


def _vortex(df: pd.DataFrame, period: int = 14) -> tuple[pd.Series, pd.Series]:
    tr = pd.concat([(df["high"]-df["low"]),
                    (df["high"]-df["close"].shift()).abs(),
                    (df["low"] -df["close"].shift()).abs()], axis=1).max(axis=1)
    vp = (df["high"]-df["low"].shift()).abs().rolling(period).sum()
    vm = (df["low"] -df["high"].shift()).abs().rolling(period).sum()
    ts = tr.rolling(period).sum()
    return vp / (ts + 1e-9), vm / (ts + 1e-9)


# ─── Precompute all filters ───────────────────────────────────────────────────

def compute_filters(df: pd.DataFrame) -> dict[str, np.ndarray]:
    """Returns a dict of filter arrays: +1=allow-long, -1=allow-short, 0=block."""
    f = {}

    # Donchian channels (entry & exit)
    f["dc_upper"] = df["high"].rolling(DC_PERIOD).max().shift(1).values
    f["dc_lower"] = df["low"].rolling(DC_PERIOD).min().shift(1).values

    # EMA 21/55
    ema21 = df["close"].ewm(span=21, adjust=False).mean()
    ema55 = df["close"].ewm(span=55, adjust=False).mean()
    f["EMA_21_55"] = np.where(ema21 > ema55, 1, -1).astype(int)

    # EMA 9/21
    ema9 = df["close"].ewm(span=9, adjust=False).mean()
    f["EMA_9_21"] = np.where(ema9 > ema21, 1, -1).astype(int)

    # MACD
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    macd  = ema12 - ema26
    sig   = macd.ewm(span=9, adjust=False).mean()
    f["MACD"] = np.where(macd > sig, 1, -1).astype(int)

    # RSI_50
    rsi = _rsi(df["close"], 14)
    f["RSI_50"] = np.where(rsi > 50, 1, -1).astype(int)

    # ADX > 20 (allows BOTH directions when trending)
    adx, pdi, mdi = _adx(df, 14)
    adx_ok = adx > 20
    f["ADX_20"] = np.where(adx_ok & (pdi > mdi), 1,
                  np.where(adx_ok & (mdi > pdi), -1, 0)).astype(int)

    # Supertrend
    f["Supertrend"] = _supertrend(df, 10, 3.0).values

    # Vortex
    vi_plus, vi_minus = _vortex(df, 14)
    f["Vortex"] = np.where(vi_plus > vi_minus, 1, -1).astype(int)

    return f


# ─── Backtest engine — Donchian with optional filter ─────────────────────────

def backtest_dc(df: pd.DataFrame, filters: dict, allowed_filter: np.ndarray | None) -> list[dict]:
    """
    Donchian breakout backtest.

    allowed_filter: per-bar np.ndarray of +1 (allow long) / -1 (allow short) / 0 (block)
                    None = no filter (baseline).

    Entry : close breaks above dc_upper[1] AND (filter == +1 or no filter)  → long
            close breaks below dc_lower[1] AND (filter == -1 or no filter)  → short
    Exit  : SL=2% | TP=4% | close breaks opposite channel
    """
    closes    = df["close"].values
    highs     = df["high"].values
    lows      = df["low"].values
    dc_upper  = filters["dc_upper"]
    dc_lower  = filters["dc_lower"]
    allow     = allowed_filter  # None → no filter

    trades    = []
    position  = 0
    entry_price = 0.0
    entry_idx   = 0

    for i in range(1, len(df)):
        close = closes[i]
        af    = int(allow[i]) if allow is not None else None

        if position == 0:
            # Long entry: breakout above upper channel
            long_ok  = (close > dc_upper[i]) and (not np.isnan(dc_upper[i]))
            short_ok = (close < dc_lower[i]) and (not np.isnan(dc_lower[i]))

            if long_ok and (af is None or af == 1):
                position = 1; entry_price = close; entry_idx = i
            elif short_ok and (af is None or af == -1):
                position = -1; entry_price = close; entry_idx = i
            continue

        # In position — check exits
        sl = entry_price * (1 - SL_PCT) if position == 1 else entry_price * (1 + SL_PCT)
        tp = entry_price * (1 + TP_PCT) if position == 1 else entry_price * (1 - TP_PCT)

        exit_price = None
        if position == 1:
            if lows[i]  <= sl:           exit_price = sl
            elif highs[i] >= tp:         exit_price = tp
            elif close < dc_lower[i]:    exit_price = close  # channel reversal
        else:
            if highs[i] >= sl:           exit_price = sl
            elif lows[i]  <= tp:         exit_price = tp
            elif close > dc_upper[i]:    exit_price = close  # channel reversal

        if exit_price is not None:
            mult  = 1 if position == 1 else -1
            gross = FIXED_NOTIONAL_USD * (exit_price - entry_price) / entry_price * mult
            cost  = FIXED_NOTIONAL_USD * COMMISSION_PER_SIDE * 2
            trades.append({
                "entry_idx": entry_idx,
                "exit_idx":  i,
                "side":      "long" if position == 1 else "short",
                "pnl":       gross - cost,
            })
            position = 0

    return trades


def compute_metrics(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0, "pf": 0.0, "mdd_pct": 0.0, "roi_day": 0.0, "wr": 0.0}

    gross_w = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gross_l = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
    pf      = gross_w / gross_l if gross_l > 0 else float("inf")

    equity = peak = 0.0
    min_dd = 0.0
    for t in trades:
        equity += t["pnl"]
        if equity > peak: peak = equity
        dd = (equity - peak) / FIXED_NOTIONAL_USD * 100
        if dd < min_dd: min_dd = dd

    total_pnl = sum(t["pnl"] for t in trades)
    n_bars    = trades[-1]["exit_idx"] - trades[0]["entry_idx"] if len(trades) > 1 else 1
    n_days    = n_bars * 4 / 24
    roi_day   = (total_pnl / FIXED_NOTIONAL_USD / max(n_days, 1)) * 100
    winners   = sum(1 for t in trades if t["pnl"] > 0)

    return {
        "n":       len(trades),
        "pf":      round(pf, 3),
        "mdd_pct": round(min_dd, 2),
        "roi_day": round(roi_day, 4),
        "wr":      round(winners / len(trades) * 100, 1),
    }


def _j(obj):
    if isinstance(obj, dict):        return {k: _j(v) for k, v in obj.items()}
    if isinstance(obj, list):        return [_j(v) for v in obj]
    if isinstance(obj, np.bool_):    return bool(obj)
    if isinstance(obj, np.integer):  return int(obj)
    if isinstance(obj, np.floating): return float(obj)
    return obj


# ─── Main ────────────────────────────────────────────────────────────────────

def run():
    if not DATA_FILE.exists():
        print(f"[ERROR] Data file not found: {DATA_FILE}"); sys.exit(1)

    df = pd.read_csv(DATA_FILE)
    df.columns = [c.lower() for c in df.columns]
    for col in ("open","high","low","close","volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.dropna(subset=["open","high","low","close"], inplace=True)
    df.reset_index(drop=True, inplace=True)

    split  = int(len(df) * (1 - OOS_SPLIT))
    df_is  = df.iloc[:split].reset_index(drop=True)
    df_oos = df.iloc[split:].reset_index(drop=True)

    print(f"[dc-filtered] ETHUSDT 4H — IS={len(df_is)} bars | OOS={len(df_oos)} bars")
    print(f"[dc-filtered] Donchian_40 baseline + 12 filter combinations")
    print(f"[dc-filtered] SL={SL_PCT*100:.1f}%  TP={TP_PCT*100:.1f}%")
    print(f"[dc-filtered] Gate 1: PF>={OOS_PF_MIN} n>={OOS_TRADES_MIN} ratio<={IS_OOS_RATIO_MAX} MDD>={OOS_MDD_MAX}%\n")

    filt_is  = compute_filters(df_is)
    filt_oos = compute_filters(df_oos)

    # Build combined filter arrays for multi-filter combinations
    def combine(names_is, names_oos):
        """AND of multiple filter signals: +1 only if all +1, -1 only if all -1, else 0."""
        is_arr  = np.stack([filt_is[n]  for n in names_is],  axis=1)
        oos_arr = np.stack([filt_oos[n] for n in names_oos], axis=1)
        is_comb  = np.where(np.all(is_arr  == 1, axis=1), 1, np.where(np.all(is_arr  == -1, axis=1), -1, 0)).astype(int)
        oos_comb = np.where(np.all(oos_arr == 1, axis=1), 1, np.where(np.all(oos_arr == -1, axis=1), -1, 0)).astype(int)
        return is_comb, oos_comb

    # All filter variants to test
    filter_variants: list[tuple[str, np.ndarray | None, np.ndarray | None]] = [
        ("Baseline (no filter)", None, None),
        ("+ EMA_21_55",         filt_is["EMA_21_55"],  filt_oos["EMA_21_55"]),
        ("+ EMA_9_21",          filt_is["EMA_9_21"],   filt_oos["EMA_9_21"]),
        ("+ MACD",              filt_is["MACD"],       filt_oos["MACD"]),
        ("+ RSI_50",            filt_is["RSI_50"],     filt_oos["RSI_50"]),
        ("+ ADX_20",            filt_is["ADX_20"],     filt_oos["ADX_20"]),
        ("+ Supertrend",        filt_is["Supertrend"], filt_oos["Supertrend"]),
        ("+ Vortex",            filt_is["Vortex"],     filt_oos["Vortex"]),
        *[
            (
                f"+ {a} + {b}",
                *combine([a, b], [a, b]),
            )
            for a, b in [
                ("EMA_21_55", "MACD"),
                ("EMA_21_55", "Supertrend"),
                ("EMA_21_55", "Vortex"),
                ("EMA_21_55", "RSI_50"),
                ("MACD", "Supertrend"),
                ("MACD", "RSI_50"),
                ("MACD", "Vortex"),
                ("Supertrend", "Vortex"),
                ("Supertrend", "RSI_50"),
                ("EMA_9_21", "MACD"),
                ("EMA_9_21", "Supertrend"),
                ("EMA_9_21", "Vortex"),
            ]
        ],
        *[
            (
                f"+ {a} + {b} + {c}",
                *combine([a, b, c], [a, b, c]),
            )
            for a, b, c in [
                ("EMA_21_55", "MACD", "Supertrend"),
                ("EMA_21_55", "MACD", "RSI_50"),
                ("EMA_21_55", "MACD", "Vortex"),
                ("EMA_21_55", "Supertrend", "RSI_50"),
                ("MACD", "Supertrend", "RSI_50"),
                ("EMA_9_21", "MACD", "Supertrend"),
            ]
        ],
    ]

    results = []
    passes  = []

    for label, f_is, f_oos in filter_variants:
        is_trades  = backtest_dc(df_is,  filt_is,  f_is)
        oos_trades = backtest_dc(df_oos, filt_oos, f_oos)

        is_m  = compute_metrics(is_trades)
        oos_m = compute_metrics(oos_trades)

        ratio = round(is_m["pf"] / oos_m["pf"], 2) if oos_m["pf"] > 0 else 99.0

        gate_pf    = oos_m["pf"]      >= OOS_PF_MIN
        gate_n     = oos_m["n"]       >= OOS_TRADES_MIN
        gate_ratio = ratio             <= IS_OOS_RATIO_MAX
        gate_mdd   = oos_m["mdd_pct"] >= OOS_MDD_MAX
        passed     = all([gate_pf, gate_n, gate_ratio, gate_mdd])

        gates_fail = []
        if not gate_pf:    gates_fail.append("PF")
        if not gate_n:     gates_fail.append("n")
        if not gate_ratio: gates_fail.append("ratio")
        if not gate_mdd:   gates_fail.append("MDD")

        status = "PASS ✓" if passed else f"FAIL [{', '.join(gates_fail)}]"

        row = {
            "filter":       label,
            "is_n":         is_m["n"],   "is_pf":      is_m["pf"],
            "oos_n":        oos_m["n"],  "oos_pf":     oos_m["pf"],
            "oos_mdd":      oos_m["mdd_pct"],
            "oos_roi_day":  oos_m["roi_day"],
            "oos_wr":       oos_m["wr"],
            "ratio":        ratio,
            "gate_pf":      gate_pf, "gate_n": gate_n,
            "gate_ratio":   gate_ratio, "gate_mdd": gate_mdd,
            "PASS":         passed,
        }
        results.append(row)
        if passed:
            passes.append(row)

        print(
            f"  {status:30s} | IS n={is_m['n']:3d} PF={is_m['pf']:.3f}"
            f" | OOS n={oos_m['n']:3d} PF={oos_m['pf']:.3f}"
            f" MDD={oos_m['mdd_pct']:6.1f}% ROI/d={oos_m['roi_day']:.4f}%"
            f" WR={oos_m['wr']:.1f}%"
            f" | ratio={ratio:.2f}"
            f"  ← {label}"
        )

    results.sort(key=lambda r: r["oos_pf"], reverse=True)

    ts       = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_DIR / f"sweep_dc_filtered_ethusdt4h_{ts}.json"
    with open(out_path, "w") as f:
        json.dump(_j({
            "run_ts": ts, "symbol": "ETHUSDT", "tf": "4h",
            "dc_period": DC_PERIOD,
            "sl_pct": SL_PCT*100, "tp_pct": TP_PCT*100,
            "n_variants": len(results), "n_passes": len(passes),
            "results": results,
        }), f, indent=2)

    print()
    print("=" * 80)
    print(f"[dc-filtered] SUMMARY — {len(passes)}/{len(results)} filter variants passed Gate 1")
    print("=" * 80)

    if passes:
        print("\n  PASSING FILTERS:")
        for r in passes:
            print(
                f"  {r['filter']:40s} OOS PF={r['oos_pf']:.3f} n={r['oos_n']:3d}"
                f" MDD={r['oos_mdd']:.1f}% ROI/d={r['oos_roi_day']:.4f}%"
            )

    print(f"\n[dc-filtered] Full results → {out_path}")


if __name__ == "__main__":
    run()
