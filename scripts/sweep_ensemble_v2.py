#!/usr/bin/env python3
"""
sweep_ensemble_v2.py
====================
Smarter ensemble sweep on ETHUSDT 4H — fixes the "all must agree" problem
that produced 1-5 trades per combo in v1.

Signal categories:
  STATE  signals: always +1 or -1 (EMA cross, Supertrend, MACD, RSI50, PSAR, Vortex)
  ENTRY  signals: +1 / -1 / 0, fire only on condition  (Williams R, RSI reversal,
                  Donchian breakout, CCI, Bollinger, Stoch, ADX+DI)

Ensemble logic (smarter):
  ENTRY when ALL state signals agree  AND  ANY entry signal fires in same direction.
  EXIT  when ANY state signal in the combo flips to opposite direction  OR  SL/TP hit.

  Pure-state combos (no entry signals):  ALL must agree to enter; any flip exits.

Combinations tested:
  Pair   STATE×STATE          :  C(7,2)       = 21
  Pair   STATE×ENTRY          :  7×7          = 49
  Triple STATE×STATE×STATE    :  C(7,3)       = 35
  Triple STATE×STATE×ENTRY    :  C(7,2)×7    = 147
  Triple STATE×ENTRY×ENTRY    :  7×C(7,2)    = 147   (ANY-of-entries logic)
  ─────────────────────────────────────────────────────
  Total                       :              399

Gate 1 (same as single-strategy, n threshold relaxed for ensemble):
  OOS PF >= 1.5  |  OOS n >= 30  |  IS/OOS ratio <= 4.0  |  OOS MDD >= -15%

Run:
  cd /home/ubuntu/tradingview_webhook_bot
  python3 scripts/sweep_ensemble_v2.py
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
OOS_TRADES_MIN   = 30
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


def _adx_components(df: pd.DataFrame, period: int = 14):
    hi, lo = df["high"], df["low"]
    plus_dm  = np.where((hi - hi.shift(1)) > (lo.shift(1) - lo), np.maximum(hi - hi.shift(1), 0), 0)
    minus_dm = np.where((lo.shift(1) - lo) > (hi - hi.shift(1)), np.maximum(lo.shift(1) - lo, 0), 0)
    atr_s    = _atr(df, period)
    plus_di  = 100 * pd.Series(plus_dm,  index=df.index).ewm(alpha=1/period, adjust=False).mean() / (atr_s + 1e-9)
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1/period, adjust=False).mean() / (atr_s + 1e-9)
    dx       = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9)
    adx      = dx.ewm(alpha=1/period, adjust=False).mean()
    return plus_di, minus_di, adx


def _supertrend_dir(df: pd.DataFrame, period: int = 10, mult: float = 3.0) -> pd.Series:
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


def _psar_dir(df: pd.DataFrame, start: float = 0.02, inc: float = 0.02, max_: float = 0.2) -> pd.Series:
    highs = df["high"].values
    lows  = df["low"].values
    n     = len(highs)
    psar  = np.full(n, np.nan)
    bull  = True; ep = lows[0]; af = start
    psar[0] = highs[0]
    for i in range(1, n):
        p = psar[i-1]
        if bull:
            psar[i] = p + af * (ep - p)
            psar[i] = min(psar[i], lows[i-1], lows[max(i-2, 0)])
            if lows[i] < psar[i]:
                bull = False; psar[i] = ep; ep = lows[i]; af = start
            elif highs[i] > ep:
                ep = highs[i]; af = min(af + inc, max_)
        else:
            psar[i] = p + af * (ep - p)
            psar[i] = max(psar[i], highs[i-1], highs[max(i-2, 0)])
            if highs[i] > psar[i]:
                bull = True; psar[i] = ep; ep = highs[i]; af = start
            elif lows[i] < ep:
                ep = lows[i]; af = min(af + inc, max_)
    return pd.Series(np.where(df["close"].values > psar, 1, -1).astype(int), index=df.index)


# ─── Strategy registry ────────────────────────────────────────────────────────

STATE_STRATEGIES: dict[str, callable] = {}   # always +1 or -1
ENTRY_STRATEGIES: dict[str, callable] = {}   # +1 / -1 / 0


def state(name):
    def d(fn): STATE_STRATEGIES[name] = fn; return fn
    return d


def entry(name):
    def d(fn): ENTRY_STRATEGIES[name] = fn; return fn
    return d


# ── STATE: trend-direction signals ───────────────────────────────────────────

@state("EMA_21_55")
def sig_ema_21_55(df):
    f = df["close"].ewm(span=21, adjust=False).mean()
    s = df["close"].ewm(span=55, adjust=False).mean()
    return pd.Series(np.where(f > s, 1, -1).astype(int), index=df.index)


@state("EMA_9_21")
def sig_ema_9_21(df):
    f = df["close"].ewm(span=9,  adjust=False).mean()
    s = df["close"].ewm(span=21, adjust=False).mean()
    return pd.Series(np.where(f > s, 1, -1).astype(int), index=df.index)


@state("Supertrend")
def sig_supertrend(df):
    return _supertrend_dir(df, 10, 3.0)


@state("MACD")
def sig_macd(df):
    f  = df["close"].ewm(span=12, adjust=False).mean()
    s  = df["close"].ewm(span=26, adjust=False).mean()
    ml = (f - s).ewm(span=9, adjust=False).mean()
    return pd.Series(np.where((f-s) > ml, 1, -1).astype(int), index=df.index)


@state("RSI_50")
def sig_rsi_50(df):
    rsi = _rsi(df["close"], 14)
    return pd.Series(np.where(rsi > 50, 1, -1).astype(int), index=df.index)


@state("PSAR")
def sig_psar(df):
    return _psar_dir(df)


@state("Vortex")
def sig_vortex(df):
    period = 14
    tr = pd.concat([(df["high"]-df["low"]),
                    (df["high"]-df["close"].shift()).abs(),
                    (df["low"] -df["close"].shift()).abs()], axis=1).max(axis=1)
    vp = (df["high"]-df["low"].shift()).abs().rolling(period).sum()
    vm = (df["low"] -df["high"].shift()).abs().rolling(period).sum()
    ts = tr.rolling(period).sum()
    return pd.Series(np.where(vp/ts > vm/ts, 1, -1).astype(int), index=df.index)


# ── ENTRY: condition-triggered signals ───────────────────────────────────────

@entry("Williams_R")
def sig_williams_r(df):
    hh = df["high"].rolling(14).max()
    ll = df["low"].rolling(14).min()
    wr = -100 * (hh - df["close"]) / (hh - ll + 1e-9)
    return pd.Series(np.where(wr < -80, 1, np.where(wr > -20, -1, 0)).astype(int), index=df.index)


@entry("RSI_Rev")
def sig_rsi_rev(df):
    rsi = _rsi(df["close"], 14)
    return pd.Series(np.where(rsi < 35, 1, np.where(rsi > 65, -1, 0)).astype(int), index=df.index)


@entry("Donchian_40")
def sig_donchian(df):
    upper = df["high"].rolling(40).max().shift(1)
    lower = df["low"].rolling(40).min().shift(1)
    return pd.Series(
        np.where(df["close"] > upper, 1, np.where(df["close"] < lower, -1, 0)).astype(int),
        index=df.index
    )


@entry("CCI_20")
def sig_cci(df):
    tp  = (df["high"] + df["low"] + df["close"]) / 3
    sma = tp.rolling(20).mean()
    mad = tp.rolling(20).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    cci = (tp - sma) / (0.015 * mad + 1e-9)
    return pd.Series(np.where(cci > 100, 1, np.where(cci < -100, -1, 0)).astype(int), index=df.index)


@entry("BBands")
def sig_bbands(df):
    sma   = df["close"].rolling(20).mean()
    std   = df["close"].rolling(20).std()
    return pd.Series(
        np.where(df["close"] < sma - 2*std, 1, np.where(df["close"] > sma + 2*std, -1, 0)).astype(int),
        index=df.index
    )


@entry("Stoch")
def sig_stoch(df):
    ll = df["low"].rolling(14).min()
    hh = df["high"].rolling(14).max()
    k  = 100 * (df["close"] - ll) / (hh - ll + 1e-9)
    return pd.Series(np.where(k < 20, 1, np.where(k > 80, -1, 0)).astype(int), index=df.index)


@entry("ADX_DI")
def sig_adx_di(df):
    pdi, mdi, adx = _adx_components(df, 14)
    return pd.Series(
        np.where((pdi > mdi) & (adx > 20), 1, np.where((mdi > pdi) & (adx > 20), -1, 0)).astype(int),
        index=df.index
    )


# ─── Ensemble builder ─────────────────────────────────────────────────────────

def build_signals(
    state_names: list[str],
    entry_names: list[str],
    sigs_state: dict[str, np.ndarray],
    sigs_entry: dict[str, np.ndarray],
) -> tuple[np.ndarray, np.ndarray]:
    """
    Returns (entry_signal, exit_signal) arrays.

    entry_signal (+1/-1/0):
      +1 when ALL state signals == +1  AND  ANY entry signal == +1   (or pure-state: all state == +1)
      -1 when ALL state signals == -1  AND  ANY entry signal == -1
       0 otherwise

    exit_signal (+1/-1/0):
      Uses only state consensus — exit position when states flip to opposite direction.
    """
    n = len(next(iter({**sigs_state, **sigs_entry}.values())))

    # State consensus
    if state_names:
        st_stack   = np.stack([sigs_state[s] for s in state_names], axis=1)
        state_long  = np.all(st_stack == 1,  axis=1)
        state_short = np.all(st_stack == -1, axis=1)
        state_dir   = np.where(state_long, 1, np.where(state_short, -1, 0)).astype(int)
    else:
        state_dir = np.ones(n, dtype=int)

    # Entry trigger
    if entry_names:
        en_stack    = np.stack([sigs_entry[e] for e in entry_names], axis=1)
        entry_long  = np.any(en_stack == 1,  axis=1)   # ANY entry fires long
        entry_short = np.any(en_stack == -1, axis=1)   # ANY entry fires short
        entry_dir   = np.where(entry_long, 1, np.where(entry_short, -1, 0)).astype(int)
    else:
        entry_dir = state_dir.copy()

    entry_signal = np.where(
        (state_dir == 1)  & (entry_dir == 1),  1,
        np.where(
        (state_dir == -1) & (entry_dir == -1), -1, 0)
    ).astype(int)

    # Exit tracks only state direction (don't exit when entry trigger goes neutral)
    exit_signal = state_dir

    return entry_signal, exit_signal


# ─── Backtest engine ──────────────────────────────────────────────────────────

def backtest(df: pd.DataFrame, entry_sig: np.ndarray, exit_sig: np.ndarray) -> list[dict]:
    closes = df["close"].values
    highs  = df["high"].values
    lows   = df["low"].values
    trades = []
    position    = 0
    entry_price = 0.0
    entry_idx   = 0

    for i in range(1, len(df)):
        esig  = int(entry_sig[i])
        exsig = int(exit_sig[i])

        if position == 0:
            if esig == 1:
                position = 1; entry_price = closes[i]; entry_idx = i
            elif esig == -1:
                position = -1; entry_price = closes[i]; entry_idx = i
            continue

        sl = entry_price * (1 - SL_PCT) if position == 1 else entry_price * (1 + SL_PCT)
        tp = entry_price * (1 + TP_PCT) if position == 1 else entry_price * (1 - TP_PCT)

        exit_price = None
        if position == 1:
            if lows[i]  <= sl:      exit_price = sl
            elif highs[i] >= tp:    exit_price = tp
            elif exsig == -1:       exit_price = closes[i]  # state flipped bear
        else:
            if highs[i] >= sl:      exit_price = sl
            elif lows[i]  <= tp:    exit_price = tp
            elif exsig == 1:        exit_price = closes[i]  # state flipped bull

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
        # Use notional as denominator to avoid division-by-near-zero artifacts
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


# ─── JSON helper ─────────────────────────────────────────────────────────────

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
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.dropna(subset=["open", "high", "low", "close"], inplace=True)
    df.reset_index(drop=True, inplace=True)

    split  = int(len(df) * (1 - OOS_SPLIT))
    df_is  = df.iloc[:split].reset_index(drop=True)
    df_oos = df.iloc[split:].reset_index(drop=True)

    sn = list(STATE_STRATEGIES.keys())
    en = list(ENTRY_STRATEGIES.keys())

    print(f"[ensemble-v2] ETHUSDT 4H — IS={len(df_is)} bars | OOS={len(df_oos)} bars")
    print(f"[ensemble-v2] {len(sn)} state signals + {len(en)} entry signals")
    print(f"[ensemble-v2] SL={SL_PCT*100:.1f}%  TP={TP_PCT*100:.1f}%  notional=${FIXED_NOTIONAL_USD}")
    print(f"[ensemble-v2] Gate 1: OOS PF>={OOS_PF_MIN} n>={OOS_TRADES_MIN} ratio<={IS_OOS_RATIO_MAX} MDD>={OOS_MDD_MAX}%")
    print()
    print("[ensemble-v2] Computing signals...")

    # Pre-compute on IS and OOS
    ss_is  = {n: STATE_STRATEGIES[n](df_is).values  for n in sn}
    ss_oos = {n: STATE_STRATEGIES[n](df_oos).values for n in sn}
    se_is  = {n: ENTRY_STRATEGIES[n](df_is).values  for n in en}
    se_oos = {n: ENTRY_STRATEGIES[n](df_oos).values for n in en}

    # Build combination list
    combos: list[tuple[list[str], list[str]]] = []

    # 2-way: STATE×STATE
    for s1, s2 in combinations(sn, 2):
        combos.append(([s1, s2], []))

    # 2-way: STATE×ENTRY
    for s in sn:
        for e in en:
            combos.append(([s], [e]))

    # 3-way: STATE×STATE×STATE
    for s1, s2, s3 in combinations(sn, 3):
        combos.append(([s1, s2, s3], []))

    # 3-way: STATE×STATE×ENTRY
    for s1, s2 in combinations(sn, 2):
        for e in en:
            combos.append(([s1, s2], [e]))

    # 3-way: STATE×ENTRY×ENTRY  (ANY-of-entries logic)
    for s in sn:
        for e1, e2 in combinations(en, 2):
            combos.append(([s], [e1, e2]))

    print(f"[ensemble-v2] {len(combos)} combos to test. Starting sweep...\n")

    results = []
    passes  = []

    for done, (state_names, entry_names) in enumerate(combos, 1):
        combo_label = " + ".join(state_names + (["[" + " | ".join(entry_names) + "]"] if entry_names else []))

        ens_is_e,  ens_is_x  = build_signals(state_names, entry_names, ss_is,  se_is)
        ens_oos_e, ens_oos_x = build_signals(state_names, entry_names, ss_oos, se_oos)

        is_trades  = backtest(df_is,  ens_is_e,  ens_is_x)
        oos_trades = backtest(df_oos, ens_oos_e, ens_oos_x)

        is_m  = compute_metrics(is_trades)
        oos_m = compute_metrics(oos_trades)

        ratio = round(is_m["pf"] / oos_m["pf"], 2) if oos_m["pf"] > 0 else 99.0

        gate_pf    = oos_m["pf"]      >= OOS_PF_MIN
        gate_n     = oos_m["n"]       >= OOS_TRADES_MIN
        gate_ratio = ratio             <= IS_OOS_RATIO_MAX
        gate_mdd   = oos_m["mdd_pct"] >= OOS_MDD_MAX
        passed     = all([gate_pf, gate_n, gate_ratio, gate_mdd])

        row = {
            "combo":        combo_label,
            "state":        state_names,
            "entry":        entry_names,
            "n_components": len(state_names) + len(entry_names),
            "is_n":         is_m["n"],    "is_pf":      is_m["pf"],
            "oos_n":        oos_m["n"],   "oos_pf":     oos_m["pf"],
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
                f"  PASS | OOS PF={oos_m['pf']:.3f} n={oos_m['n']:3d} "
                f"MDD={oos_m['mdd_pct']:6.1f}% ROI/d={oos_m['roi_day']:.4f}% WR={oos_m['wr']:.1f}%"
                f"\n         {combo_label}"
            )

        if done % 50 == 0:
            pct = done / len(combos) * 100
            print(f"  ... {done}/{len(combos)} ({pct:.0f}%) — {len(passes)} passing so far")

    results.sort(key=lambda r: r["oos_pf"], reverse=True)
    passes.sort(key=lambda r: r["oos_pf"],  reverse=True)

    ts       = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_DIR / f"sweep_ensemble_v2_ethusdt4h_{ts}.json"
    with open(out_path, "w") as f:
        json.dump(_j({
            "run_ts": ts, "symbol": "ETHUSDT", "tf": "4h",
            "sl_pct": SL_PCT*100, "tp_pct": TP_PCT*100,
            "state_strategies": sn, "entry_strategies": en,
            "n_combos": len(results), "n_passes": len(passes),
            "gate_config": {
                "oos_pf_min": OOS_PF_MIN, "oos_n_min": OOS_TRADES_MIN,
                "is_oos_max": IS_OOS_RATIO_MAX, "mdd_max": OOS_MDD_MAX,
            },
            "top_50":    results[:50],
            "all_passes": passes,
        }), f, indent=2)

    # ── Summary ──────────────────────────────────────────────────────────────
    print()
    print("=" * 72)
    print(f"[ensemble-v2] RESULTS — ETHUSDT 4H")
    print("=" * 72)
    print(f"  Combos tested : {len(results)}")
    print(f"  Gate 1 PASSES : {len(passes)}")
    print()

    if passes:
        print("  ALL PASSING COMBOS (sorted by OOS PF):")
        print(f"  {'Rank':<4} {'OOS PF':<8} {'n':<5} {'MDD%':<9} {'ROI/d%':<9} {'WR%':<7}  Combo")
        print("  " + "-" * 68)
        for rank, r in enumerate(passes, 1):
            print(
                f"  {rank:<4} {r['oos_pf']:<8.3f} {r['oos_n']:<5} "
                f"{r['oos_mdd']:<9.1f} {r['oos_roi_day']:<9.4f} {r['oos_wr']:<7.1f}  {r['combo']}"
            )
        print()
        best = passes[0]
        print(f"  BEST COMBO: {best['combo']}")
        print(f"  OOS PF={best['oos_pf']}  n={best['oos_n']}  MDD={best['oos_mdd']}%  ROI/day={best['oos_roi_day']}%")
    else:
        print("  No combos passed Gate 1.\n")
        print("  TOP 25 by OOS PF (gate fail reasons shown):")
        print(f"  {'Rank':<4} {'OOS PF':<8} {'n':<5} {'MDD%':<9} {'ROI/d%':<9} {'WR%':<7}  Combo")
        print("  " + "-" * 68)
        for rank, r in enumerate(results[:25], 1):
            gates = []
            if not r["gate_pf"]:    gates.append("PF")
            if not r["gate_n"]:     gates.append("n")
            if not r["gate_ratio"]: gates.append("ratio")
            if not r["gate_mdd"]:   gates.append("MDD")
            print(
                f"  {rank:<4} {r['oos_pf']:<8.3f} {r['oos_n']:<5} "
                f"{r['oos_mdd']:<9.1f} {r['oos_roi_day']:<9.4f} {r['oos_wr']:<7.1f}  "
                f"{r['combo']}  [FAIL: {', '.join(gates)}]"
            )

    print()
    print(f"[ensemble-v2] Full results → {out_path}")


if __name__ == "__main__":
    run()
