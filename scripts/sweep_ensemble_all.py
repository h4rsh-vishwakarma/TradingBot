#!/usr/bin/env python3
"""
sweep_ensemble_all.py
=====================
Exhaustive ensemble sweep: every 2-way and 3-way combination of 14 indicators
on ETHUSDT 4H data.

Each indicator generates +1 (long) / -1 (short) / 0 (flat) per bar.
Ensemble entry: ALL component signals must agree on direction.
Hold until: SL hit | TP hit | ensemble flips to opposite direction.

14 strategies → 91 pairs + 364 triples = 455 combinations tested.

Gate 1 thresholds:
  OOS PF >= 1.5  |  OOS n >= 30 (relaxed for ensemble)
  IS/OOS ratio <= 4.0  |  OOS MDD >= -15%

Run:
  cd /home/ubuntu/tradingview_webhook_bot
  python3 scripts/sweep_ensemble_all.py
"""

from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from itertools import combinations
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

OOS_PF_MIN       = 1.5
OOS_TRADES_MIN   = 30      # relaxed vs single-strategy 50 — ensemble reduces frequency
IS_OOS_RATIO_MAX = 4.0
OOS_MDD_MAX      = -15.0

DATA_FILE   = Path("/home/ubuntu/tradingview_webhook_bot/storage/backtest_data/ETHUSDT_5y_4h.csv")
RESULTS_DIR = Path("/home/ubuntu/tradingview_webhook_bot/storage/gate1_results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


# ─── Indicator helpers ────────────────────────────────────────────────────────

def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta).clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / (loss + 1e-9)
    return 100 - 100 / (1 + rs)


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    hi, lo, cl = df["high"], df["low"], df["close"]
    tr = pd.concat(
        [(hi - lo), (hi - cl.shift()).abs(), (lo - cl.shift()).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def _adx_components(df: pd.DataFrame, period: int = 14):
    hi, lo = df["high"], df["low"]
    plus_dm  = np.where((hi - hi.shift(1)) > (lo.shift(1) - lo), np.maximum(hi - hi.shift(1), 0), 0)
    minus_dm = np.where((lo.shift(1) - lo) > (hi - hi.shift(1)), np.maximum(lo.shift(1) - lo, 0), 0)
    atr_s    = _atr(df, period)
    plus_di  = 100 * pd.Series(plus_dm,  index=df.index).ewm(alpha=1/period, adjust=False).mean() / (atr_s + 1e-9)
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1/period, adjust=False).mean() / (atr_s + 1e-9)
    dx       = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9)
    adx      = dx.ewm(alpha=1 / period, adjust=False).mean()
    return plus_di, minus_di, adx


def _supertrend_direction(df: pd.DataFrame, period: int = 10, mult: float = 3.0) -> pd.Series:
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
        if np.isnan(upper[i - 1]):
            upper[i] = upper_b[i]
            lower[i] = lower_b[i]
        else:
            upper[i] = upper_b[i] if (upper_b[i] < upper[i-1] or closes[i-1] > upper[i-1]) else upper[i-1]
            lower[i] = lower_b[i] if (lower_b[i] > lower[i-1] or closes[i-1] < lower[i-1]) else lower[i-1]
        if trend[i-1] == 1:
            trend[i] = -1 if closes[i] < lower[i] else 1
        else:
            trend[i] = 1 if closes[i] > upper[i] else -1
    return pd.Series(trend.astype(int), index=df.index)


def _psar_direction(df: pd.DataFrame, start: float = 0.02, inc: float = 0.02, max_: float = 0.2) -> pd.Series:
    highs = df["high"].values
    lows  = df["low"].values
    n     = len(highs)
    psar  = np.full(n, np.nan)
    bull  = True
    ep    = lows[0]
    af    = start
    psar[0] = highs[0]
    for i in range(1, n):
        p = psar[i - 1]
        if bull:
            psar[i] = p + af * (ep - p)
            psar[i] = min(psar[i], lows[i - 1], lows[max(i - 2, 0)])
            if lows[i] < psar[i]:
                bull = False; psar[i] = ep; ep = lows[i]; af = start
            else:
                if highs[i] > ep:
                    ep = highs[i]; af = min(af + inc, max_)
        else:
            psar[i] = p + af * (ep - p)
            psar[i] = max(psar[i], highs[i - 1], highs[max(i - 2, 0)])
            if highs[i] > psar[i]:
                bull = True; psar[i] = ep; ep = highs[i]; af = start
            else:
                if lows[i] < ep:
                    ep = lows[i]; af = min(af + inc, max_)
    sig = np.where(df["close"].values > psar, 1, -1)
    return pd.Series(sig.astype(int), index=df.index)


# ─── Strategy registry ────────────────────────────────────────────────────────

STRATEGIES: dict[str, callable] = {}


def register(name: str):
    def decorator(fn):
        STRATEGIES[name] = fn
        return fn
    return decorator


# ── Trend / state signals (always +1 or -1) ──────────────────────────────────

@register("EMA_21_55")
def sig_ema_21_55(df):
    ema_f = df["close"].ewm(span=21, adjust=False).mean()
    ema_s = df["close"].ewm(span=55, adjust=False).mean()
    return pd.Series(np.where(ema_f > ema_s, 1, -1).astype(int), index=df.index)


@register("EMA_9_21")
def sig_ema_9_21(df):
    ema_f = df["close"].ewm(span=9,  adjust=False).mean()
    ema_s = df["close"].ewm(span=21, adjust=False).mean()
    return pd.Series(np.where(ema_f > ema_s, 1, -1).astype(int), index=df.index)


@register("Supertrend_10_3")
def sig_supertrend(df):
    return _supertrend_direction(df, period=10, mult=3.0)


@register("MACD_12_26_9")
def sig_macd(df):
    ema_f   = df["close"].ewm(span=12, adjust=False).mean()
    ema_s   = df["close"].ewm(span=26, adjust=False).mean()
    macd    = ema_f - ema_s
    sig_ln  = macd.ewm(span=9, adjust=False).mean()
    return pd.Series(np.where(macd > sig_ln, 1, -1).astype(int), index=df.index)


@register("RSI_Trend_50")
def sig_rsi_trend(df):
    rsi = _rsi(df["close"], 14)
    return pd.Series(np.where(rsi > 50, 1, -1).astype(int), index=df.index)


@register("PSAR")
def sig_psar(df):
    return _psar_direction(df)


@register("Vortex_14")
def sig_vortex(df):
    period = 14
    tr = pd.concat(
        [(df["high"] - df["low"]),
         (df["high"] - df["close"].shift()).abs(),
         (df["low"]  - df["close"].shift()).abs()], axis=1
    ).max(axis=1)
    vm_plus  = (df["high"] - df["low"].shift()).abs()
    vm_minus = (df["low"]  - df["high"].shift()).abs()
    tr_sum   = tr.rolling(period).sum()
    vi_plus  = vm_plus.rolling(period).sum()  / (tr_sum + 1e-9)
    vi_minus = vm_minus.rolling(period).sum() / (tr_sum + 1e-9)
    return pd.Series(np.where(vi_plus > vi_minus, 1, -1).astype(int), index=df.index)


# ── Entry / trigger signals (often 0 — fire only on condition) ───────────────

@register("RSI_Rev_30_70")
def sig_rsi_reversal(df):
    rsi = _rsi(df["close"], 14)
    sig = np.where(rsi < 30, 1, np.where(rsi > 70, -1, 0))
    return pd.Series(sig.astype(int), index=df.index)


@register("Williams_R_14")
def sig_williams_r(df):
    hh  = df["high"].rolling(14).max()
    ll  = df["low"].rolling(14).min()
    wr  = -100 * (hh - df["close"]) / (hh - ll + 1e-9)
    sig = np.where(wr < -80, 1, np.where(wr > -20, -1, 0))
    return pd.Series(sig.astype(int), index=df.index)


@register("Donchian_40")
def sig_donchian(df):
    upper = df["high"].rolling(40).max().shift(1)
    lower = df["low"].rolling(40).min().shift(1)
    sig   = np.where(df["close"] > upper, 1, np.where(df["close"] < lower, -1, 0))
    return pd.Series(sig.astype(int), index=df.index)


@register("CCI_20")
def sig_cci(df):
    tp  = (df["high"] + df["low"] + df["close"]) / 3
    sma = tp.rolling(20).mean()
    mad = tp.rolling(20).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    cci = (tp - sma) / (0.015 * mad + 1e-9)
    sig = np.where(cci > 100, 1, np.where(cci < -100, -1, 0))
    return pd.Series(sig.astype(int), index=df.index)


@register("BBands_Rev_20")
def sig_bbands(df):
    sma   = df["close"].rolling(20).mean()
    std   = df["close"].rolling(20).std()
    upper = sma + 2 * std
    lower = sma - 2 * std
    sig   = np.where(df["close"] < lower, 1, np.where(df["close"] > upper, -1, 0))
    return pd.Series(sig.astype(int), index=df.index)


@register("Stoch_14")
def sig_stoch(df):
    ll  = df["low"].rolling(14).min()
    hh  = df["high"].rolling(14).max()
    k   = 100 * (df["close"] - ll) / (hh - ll + 1e-9)
    sig = np.where(k < 20, 1, np.where(k > 80, -1, 0))
    return pd.Series(sig.astype(int), index=df.index)


@register("ADX_DI_14")
def sig_adx_di(df):
    plus_di, minus_di, adx = _adx_components(df, 14)
    sig = np.where(
        (plus_di > minus_di) & (adx > 20),  1,
        np.where((minus_di > plus_di) & (adx > 20), -1, 0)
    )
    return pd.Series(sig.astype(int), index=df.index)


# ─── Backtest engine ──────────────────────────────────────────────────────────

def backtest(df: pd.DataFrame, ensemble_sig: np.ndarray) -> list[dict]:
    """
    Enter when ensemble_sig == +1 or -1.
    Exit when: SL hit | TP hit | ensemble flips to OPPOSITE direction.
    Neutral (0) keeps the position open — only a full reversal exits.
    """
    closes = df["close"].values
    highs  = df["high"].values
    lows   = df["low"].values
    trades = []
    position    = 0
    entry_price = 0.0
    entry_idx   = 0

    for i in range(1, len(df)):
        sig = int(ensemble_sig[i])

        if position == 0:
            if sig == 1:
                position = 1; entry_price = closes[i]; entry_idx = i
            elif sig == -1:
                position = -1; entry_price = closes[i]; entry_idx = i
            continue

        sl = entry_price * (1 - SL_PCT) if position == 1 else entry_price * (1 + SL_PCT)
        tp = entry_price * (1 + TP_PCT) if position == 1 else entry_price * (1 - TP_PCT)

        exit_price = None
        if position == 1:
            if lows[i]  <= sl: exit_price = sl
            elif highs[i] >= tp: exit_price = tp
            elif sig == -1:      exit_price = closes[i]
        else:
            if highs[i] >= sl: exit_price = sl
            elif lows[i]  <= tp: exit_price = tp
            elif sig == 1:       exit_price = closes[i]

        if exit_price is not None:
            mult      = 1 if position == 1 else -1
            gross_pnl = FIXED_NOTIONAL_USD * (exit_price - entry_price) / entry_price * mult
            cost      = FIXED_NOTIONAL_USD * COMMISSION_PER_SIDE * 2
            trades.append({
                "entry_idx": entry_idx,
                "exit_idx":  i,
                "side":      "long" if position == 1 else "short",
                "pnl":       gross_pnl - cost,
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
        dd = (equity - peak) / max(abs(peak), 1) * 100
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


# ─── Ensemble signal combiner ─────────────────────────────────────────────────

def make_ensemble(signal_arrays: list[np.ndarray]) -> np.ndarray:
    """
    +1  when ALL component signals == +1  (unanimous long)
    -1  when ALL component signals == -1  (unanimous short)
     0  otherwise (disagreement or any neutral)
    """
    stacked    = np.stack(signal_arrays, axis=1)
    long_mask  = np.all(stacked == 1,  axis=1)
    short_mask = np.all(stacked == -1, axis=1)
    return np.where(long_mask, 1, np.where(short_mask, -1, 0)).astype(int)


# ─── JSON serialiser (handles numpy types) ────────────────────────────────────

def _j(obj):
    if isinstance(obj, dict):          return {k: _j(v) for k, v in obj.items()}
    if isinstance(obj, list):          return [_j(v) for v in obj]
    if isinstance(obj, np.bool_):      return bool(obj)
    if isinstance(obj, np.integer):    return int(obj)
    if isinstance(obj, np.floating):   return float(obj)
    return obj


# ─── Main sweep ───────────────────────────────────────────────────────────────

def run():
    if not DATA_FILE.exists():
        print(f"[ERROR] Data file not found: {DATA_FILE}")
        sys.exit(1)

    df = pd.read_csv(DATA_FILE)
    df.columns = [c.lower() for c in df.columns]
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.dropna(subset=["open", "high", "low", "close"], inplace=True)
    df.reset_index(drop=True, inplace=True)

    split  = int(len(df) * (1 - OOS_SPLIT))
    df_is  = df.iloc[:split].reset_index(drop=True)
    df_oos = df.iloc[split:].reset_index(drop=True)

    names = list(STRATEGIES.keys())
    n_strats = len(names)

    combos_2 = list(combinations(range(n_strats), 2))
    combos_3 = list(combinations(range(n_strats), 3))
    total    = len(combos_2) + len(combos_3)

    print(f"[ensemble] ETHUSDT 4H — IS={len(df_is)} bars | OOS={len(df_oos)} bars")
    print(f"[ensemble] {n_strats} strategies → {len(combos_2)} pairs + {len(combos_3)} triples = {total} combos")
    print(f"[ensemble] SL={SL_PCT*100:.1f}%  TP={TP_PCT*100:.1f}%  notional=${FIXED_NOTIONAL_USD}")
    print(f"[ensemble] Gate 1: OOS PF>={OOS_PF_MIN}  n>={OOS_TRADES_MIN}  ratio<={IS_OOS_RATIO_MAX}  MDD>={OOS_MDD_MAX}%")
    print()

    # Pre-compute all signals once
    print("[ensemble] Computing signals for all strategies...")
    sigs_is  = {n: STRATEGIES[n](df_is).values  for n in names}
    sigs_oos = {n: STRATEGIES[n](df_oos).values for n in names}
    print("[ensemble] Signals ready. Starting combo sweep...\n")

    results = []
    passes  = []
    done    = 0

    for combo_idx in (combos_2 + combos_3):
        combo_names = [names[i] for i in combo_idx]

        ens_is  = make_ensemble([sigs_is[n]  for n in combo_names])
        ens_oos = make_ensemble([sigs_oos[n] for n in combo_names])

        is_trades  = backtest(df_is,  ens_is)
        oos_trades = backtest(df_oos, ens_oos)

        is_m  = compute_metrics(is_trades)
        oos_m = compute_metrics(oos_trades)

        ratio = round(is_m["pf"] / oos_m["pf"], 2) if oos_m["pf"] > 0 else 99.0

        gate_pf    = oos_m["pf"]      >= OOS_PF_MIN
        gate_n     = oos_m["n"]       >= OOS_TRADES_MIN
        gate_ratio = ratio             <= IS_OOS_RATIO_MAX
        gate_mdd   = oos_m["mdd_pct"] >= OOS_MDD_MAX
        passed     = all([gate_pf, gate_n, gate_ratio, gate_mdd])

        row = {
            "combo":       " + ".join(combo_names),
            "n_strats":    len(combo_idx),
            "is_n":        is_m["n"],    "is_pf":      is_m["pf"],
            "oos_n":       oos_m["n"],   "oos_pf":     oos_m["pf"],
            "oos_mdd":     oos_m["mdd_pct"],
            "oos_roi_day": oos_m["roi_day"],
            "oos_wr":      oos_m["wr"],
            "ratio":       ratio,
            "gate_pf":     gate_pf, "gate_n": gate_n,
            "gate_ratio":  gate_ratio, "gate_mdd": gate_mdd,
            "PASS":        passed,
        }
        results.append(row)

        if passed:
            passes.append(row)
            print(
                f"  PASS | {len(combo_idx)}-way | OOS PF={oos_m['pf']:.3f} "
                f"n={oos_m['n']:3d} MDD={oos_m['mdd_pct']:6.1f}% "
                f"ROI/d={oos_m['roi_day']:.4f}% WR={oos_m['wr']:.1f}%\n"
                f"         {' + '.join(combo_names)}"
            )

        done += 1
        if done % 100 == 0:
            pct = done / total * 100
            print(f"  ... {done}/{total} ({pct:.0f}%) — {len(passes)} passing so far")

    # Sort by OOS PF descending
    results.sort(key=lambda r: r["oos_pf"], reverse=True)
    passes.sort(key=lambda r: r["oos_pf"],  reverse=True)

    # Save JSON
    ts       = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_DIR / f"sweep_ensemble_all_ethusdt4h_{ts}.json"
    with open(out_path, "w") as f:
        json.dump(_j({
            "run_ts":       ts,
            "symbol":       "ETHUSDT",
            "tf":           "4h",
            "sl_pct":       SL_PCT  * 100,
            "tp_pct":       TP_PCT  * 100,
            "notional_usd": FIXED_NOTIONAL_USD,
            "strategies":   names,
            "n_combos":     total,
            "n_passes":     len(passes),
            "gate_1_config": {
                "oos_pf_min":       OOS_PF_MIN,
                "oos_trades_min":   OOS_TRADES_MIN,
                "is_oos_ratio_max": IS_OOS_RATIO_MAX,
                "oos_mdd_max":      OOS_MDD_MAX,
            },
            "top_50":      results[:50],
            "all_passes":  passes,
        }), f, indent=2)

    # ── Summary ─────────────────────────────────────────────────────────────────
    print()
    print("=" * 70)
    print(f"[ensemble] RESULTS SUMMARY — ETHUSDT 4H")
    print("=" * 70)
    print(f"  Total combos tested : {total}")
    print(f"  Gate 1 passes       : {len(passes)}")
    print()

    if passes:
        print("  TOP PASSES (sorted by OOS PF):")
        print(f"  {'Rank':<4} {'Ways':<5} {'OOS PF':<8} {'n':<5} {'MDD%':<8} {'ROI/d%':<9} {'WR%':<6}  Combo")
        print("  " + "-" * 66)
        for rank, r in enumerate(passes[:20], 1):
            print(
                f"  {rank:<4} {r['n_strats']:<5} {r['oos_pf']:<8.3f} "
                f"{r['oos_n']:<5} {r['oos_mdd']:<8.1f} {r['oos_roi_day']:<9.4f} "
                f"{r['oos_wr']:<6.1f}  {r['combo']}"
            )
    else:
        print("  No combos passed Gate 1.")
        print()
        print("  TOP 20 by OOS PF (regardless of gate):")
        print(f"  {'Rank':<4} {'Ways':<5} {'OOS PF':<8} {'n':<5} {'MDD%':<8} {'ROI/d%':<9} {'WR%':<6}  Combo")
        print("  " + "-" * 66)
        for rank, r in enumerate(results[:20], 1):
            gates = ""
            if not r["gate_pf"]:    gates += "PF "
            if not r["gate_n"]:     gates += "n "
            if not r["gate_ratio"]: gates += "ratio "
            if not r["gate_mdd"]:   gates += "MDD"
            print(
                f"  {rank:<4} {r['n_strats']:<5} {r['oos_pf']:<8.3f} "
                f"{r['oos_n']:<5} {r['oos_mdd']:<8.1f} {r['oos_roi_day']:<9.4f} "
                f"{r['oos_wr']:<6.1f}  {r['combo']}  [FAIL:{gates.strip()}]"
            )

    print()
    print(f"[ensemble] Full results → {out_path}")


if __name__ == "__main__":
    run()
