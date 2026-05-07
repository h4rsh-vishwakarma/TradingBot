#!/usr/bin/env python3
"""
sweep_donchian_correct.py
=========================
Correct Python implementation of Donchian Trend [Webhook] strategy, matching
the actual Pine Script parameters from backtesting/pine/Donchian_Trend_Fixed.pine

Correct parameters (NOT the ones used in sweep_donchian_filtered.py):
  Entry channel : DC(20) — 20-bar high/low
  Exit channel  : DC(10) — 10-bar high/low (shorter)
  TP            : 12%
  SL            : 2%
  Trail         : 4% from HWM (trailing stop, activates immediately)
  EMA filter    : close > EMA(50) for longs, close < EMA(50) for shorts
  ADX filter    : ADX(14) > 20 — required for all entries

Baseline target: OOS PF ≈ 1.73, n ≈ 51 (matching leaderboard)

Then tests 12 additional filters on top of the correct baseline to find
combinations that push PF higher while keeping n >= 30.

Gate 1: OOS PF >= 1.5, OOS n >= 30 (relaxed for filtered variants),
        IS/OOS ratio <= 4.0, OOS MDD >= -15%

Run:
  cd /home/ubuntu/tradingview_webhook_bot
  python3 scripts/sweep_donchian_correct.py
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
COMMISSION_PER_SIDE = 0.0015   # 0.15%/side (our standard; TV uses 0.06%)
OOS_SPLIT           = 0.30

# --- Correct Donchian parameters (from Pine Script) ---
DC_ENTRY  = 20     # entry channel period
DC_EXIT   = 10     # exit channel period (shorter = faster exit)
SL_PCT    = 0.020  # 2%
TP_PCT    = 0.120  # 12%   ← KEY difference from v1/v2 sweep
TRAIL_PCT = 0.040  # 4% trailing from HWM

# Gate 1 thresholds
OOS_PF_MIN       = 1.5
OOS_TRADES_MIN   = 30   # relaxed; baseline should give ~51
IS_OOS_RATIO_MAX = 4.0
OOS_MDD_MAX      = -15.0

DATA_FILE   = Path("/home/ubuntu/tradingview_webhook_bot/storage/backtest_data/ETHUSDT_5y_4h.csv")
RESULTS_DIR = Path("/home/ubuntu/tradingview_webhook_bot/storage/gate1_results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    hi, lo, cl = df["high"], df["low"], df["close"]
    tr = pd.concat([(hi-lo), (hi-cl.shift()).abs(), (lo-cl.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()


def _adx_val(df: pd.DataFrame, period: int = 14) -> pd.Series:
    hi, lo = df["high"], df["low"]
    plus_dm  = np.where((hi-hi.shift(1)) > (lo.shift(1)-lo), np.maximum(hi-hi.shift(1), 0), 0)
    minus_dm = np.where((lo.shift(1)-lo) > (hi-hi.shift(1)), np.maximum(lo.shift(1)-lo, 0), 0)
    atr_s    = _atr(df, period)
    pdi  = 100 * pd.Series(plus_dm,  index=df.index).ewm(alpha=1/period, adjust=False).mean() / (atr_s+1e-9)
    mdi  = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1/period, adjust=False).mean() / (atr_s+1e-9)
    dx   = 100 * (pdi-mdi).abs() / (pdi+mdi+1e-9)
    adx  = dx.ewm(alpha=1/period, adjust=False).mean()
    return adx, pdi, mdi


def _supertrend(df: pd.DataFrame, period: int = 10, mult: float = 3.0) -> pd.Series:
    closes  = df["close"].values
    atr     = _atr(df, period)
    hl2     = (df["high"] + df["low"]) / 2
    upper_b = (hl2 + mult * atr).values
    lower_b = (hl2 - mult * atr).values
    n = len(closes)
    upper = np.full(n, np.nan); lower = np.full(n, np.nan); trend = np.zeros(n)
    for i in range(1, n):
        if np.isnan(upper_b[i]): continue
        if np.isnan(upper[i-1]):
            upper[i] = upper_b[i]; lower[i] = lower_b[i]
        else:
            upper[i] = upper_b[i] if (upper_b[i] < upper[i-1] or closes[i-1] > upper[i-1]) else upper[i-1]
            lower[i] = lower_b[i] if (lower_b[i] > lower[i-1] or closes[i-1] < lower[i-1]) else lower[i-1]
        trend[i] = (-1 if closes[i] < lower[i] else 1) if trend[i-1] == 1 else (1 if closes[i] > upper[i] else -1)
    return pd.Series(trend.astype(int), index=df.index)


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    d = close.diff()
    g = d.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    l = (-d).clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    return 100 - 100 / (1 + g / (l+1e-9))


def _vortex(df: pd.DataFrame, period: int = 14):
    tr = pd.concat([(df["high"]-df["low"]),
                    (df["high"]-df["close"].shift()).abs(),
                    (df["low"] -df["close"].shift()).abs()], axis=1).max(axis=1)
    vp = (df["high"]-df["low"].shift()).abs().rolling(period).sum()
    vm = (df["low"] -df["high"].shift()).abs().rolling(period).sum()
    ts = tr.rolling(period).sum()
    return vp/(ts+1e-9), vm/(ts+1e-9)


# ─── Precompute all filter signals ───────────────────────────────────────────

def compute_all(df: pd.DataFrame) -> dict:
    c = {}

    # Core Donchian channels (built into the strategy)
    c["dc_entry_upper"] = df["high"].rolling(DC_ENTRY).max().shift(1).values
    c["dc_entry_lower"] = df["low"].rolling(DC_ENTRY).min().shift(1).values
    c["dc_exit_upper"]  = df["high"].rolling(DC_EXIT).max().shift(1).values
    c["dc_exit_lower"]  = df["low"].rolling(DC_EXIT).min().shift(1).values
    c["close"]          = df["close"].values
    c["high"]           = df["high"].values
    c["low"]            = df["low"].values

    # Built-in filters (always active in baseline)
    ema50 = df["close"].ewm(span=50, adjust=False).mean().values
    c["ema50"] = ema50

    adx_s, pdi, mdi = _adx_val(df, 14)
    c["adx"]  = adx_s.values
    c["pdi"]  = pdi.values
    c["mdi"]  = mdi.values

    # Extra filters for combination testing
    ema21 = df["close"].ewm(span=21, adjust=False).mean()
    ema55 = df["close"].ewm(span=55, adjust=False).mean()
    ema9  = df["close"].ewm(span=9,  adjust=False).mean()
    macd  = (df["close"].ewm(span=12, adjust=False).mean() -
             df["close"].ewm(span=26, adjust=False).mean())
    sig   = macd.ewm(span=9, adjust=False).mean()
    rsi   = _rsi(df["close"], 14)
    st    = _supertrend(df, 10, 3.0)
    vip, vim = _vortex(df, 14)

    # Each extra filter: +1 = allow long, -1 = allow short, 0 = block
    c["x_EMA_21_55"]   = np.where(ema21 > ema55, 1, -1).astype(int)
    c["x_EMA_9_21"]    = np.where(ema9  > ema21, 1, -1).astype(int)
    c["x_MACD"]        = np.where(macd  > sig,   1, -1).astype(int)
    c["x_RSI_50"]      = np.where(rsi   > 50,    1, -1).astype(int)
    c["x_Supertrend"]  = st.values
    c["x_Vortex"]      = np.where(vip   > vim,   1, -1).astype(int)
    c["x_RSI_40_60"]   = np.where(rsi < 40, 1, np.where(rsi > 60, -1, 0)).astype(int)  # wider reversal
    c["x_ADX_25"]      = np.where(
        (adx_s > 25) & (pdi > mdi), 1,
        np.where((adx_s > 25) & (mdi > pdi), -1, 0)
    ).astype(int)

    return c


# ─── Backtest engine — correct Donchian + optional extra filter ───────────────

def backtest_correct(pre: dict, extra_filter: np.ndarray | None = None) -> list[dict]:
    """
    Exact Donchian Trend logic:
    - Entry: close > dc_entry_upper[1] AND close > ema50 AND adx > 20 → long
    - Entry: close < dc_entry_lower[1] AND close < ema50 AND adx > 20 → short
    - Exit long:  close < dc_exit_lower[1]  OR  SL  OR  TP  OR  Trail
    - Exit short: close > dc_exit_upper[1]  OR  SL  OR  TP  OR  Trail
    - extra_filter: if provided, also require +1 for long entries, -1 for shorts
    """
    n_bars     = len(pre["close"])
    closes     = pre["close"]
    highs      = pre["high"]
    lows       = pre["low"]
    eu         = pre["dc_entry_upper"]
    el         = pre["dc_entry_lower"]
    xu         = pre["dc_exit_upper"]
    xl         = pre["dc_exit_lower"]
    ema50      = pre["ema50"]
    adx        = pre["adx"]
    ef         = extra_filter

    trades    = []
    position  = 0
    entry_px  = 0.0
    entry_idx = 0
    trail_stop = 0.0
    hwm        = 0.0

    for i in range(1, n_bars):
        c = closes[i]
        h = highs[i]
        lo = lows[i]

        if position == 0:
            long_ok  = (c > eu[i]) and not np.isnan(eu[i]) and (c > ema50[i]) and (adx[i] > 20)
            short_ok = (c < el[i]) and not np.isnan(el[i]) and (c < ema50[i]) and (adx[i] > 20)

            if ef is not None:
                long_ok  = long_ok  and (ef[i] == 1)
                short_ok = short_ok and (ef[i] == -1)

            if long_ok:
                position = 1; entry_px = c; entry_idx = i
                hwm = c; trail_stop = c * (1 - TRAIL_PCT)
            elif short_ok:
                position = -1; entry_px = c; entry_idx = i
                hwm = c; trail_stop = c * (1 + TRAIL_PCT)
            continue

        # Update trailing stop
        if position == 1:
            if h > hwm:
                hwm = h
                trail_stop = hwm * (1 - TRAIL_PCT)
        else:
            if lo < hwm:
                hwm = lo
                trail_stop = hwm * (1 + TRAIL_PCT)

        sl = entry_px * (1 - SL_PCT) if position == 1 else entry_px * (1 + SL_PCT)
        tp = entry_px * (1 + TP_PCT) if position == 1 else entry_px * (1 - TP_PCT)

        exit_px = None
        if position == 1:
            if lo <= sl:            exit_px = sl
            elif h >= tp:           exit_px = tp
            elif lo <= trail_stop:  exit_px = trail_stop
            elif c < xl[i]:         exit_px = c   # exit channel reversal
        else:
            if h >= sl:             exit_px = sl
            elif lo <= tp:          exit_px = tp
            elif h >= trail_stop:   exit_px = trail_stop
            elif c > xu[i]:         exit_px = c   # exit channel reversal

        if exit_px is not None:
            mult  = 1 if position == 1 else -1
            gross = FIXED_NOTIONAL_USD * (exit_px - entry_px) / entry_px * mult
            cost  = FIXED_NOTIONAL_USD * COMMISSION_PER_SIDE * 2
            trades.append({
                "entry_idx": entry_idx, "exit_idx": i,
                "side": "long" if position == 1 else "short",
                "pnl": gross - cost,
            })
            position = 0

    return trades


def metrics(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0, "pf": 0.0, "mdd_pct": 0.0, "roi_day": 0.0, "wr": 0.0}
    gw = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gl = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
    pf = gw / gl if gl > 0 else float("inf")
    eq = pk = 0.0; mdd = 0.0
    for t in trades:
        eq += t["pnl"]
        if eq > pk: pk = eq
        dd = (eq - pk) / FIXED_NOTIONAL_USD * 100
        if dd < mdd: mdd = dd
    total = sum(t["pnl"] for t in trades)
    n_bars = trades[-1]["exit_idx"] - trades[0]["entry_idx"] if len(trades) > 1 else 1
    n_days = n_bars * 4 / 24
    roi_d  = total / FIXED_NOTIONAL_USD / max(n_days, 1) * 100
    wins   = sum(1 for t in trades if t["pnl"] > 0)
    return {
        "n": len(trades), "pf": round(pf, 3),
        "mdd_pct": round(mdd, 2), "roi_day": round(roi_d, 4),
        "wr": round(wins/len(trades)*100, 1),
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
        print(f"[ERROR] {DATA_FILE}"); sys.exit(1)

    df = pd.read_csv(DATA_FILE)
    df.columns = [c.lower() for c in df.columns]
    for col in ("open","high","low","close","volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.dropna(subset=["open","high","low","close"], inplace=True)
    df.reset_index(drop=True, inplace=True)

    split  = int(len(df) * (1 - OOS_SPLIT))
    df_is  = df.iloc[:split].reset_index(drop=True)
    df_oos = df.iloc[split:].reset_index(drop=True)

    pre_is  = compute_all(df_is)
    pre_oos = compute_all(df_oos)

    extra_keys = [k for k in pre_is if k.startswith("x_")]

    print(f"[dc-correct] ETHUSDT 4H — IS={len(df_is)} bars | OOS={len(df_oos)} bars")
    print(f"[dc-correct] Donchian: DC{DC_ENTRY}/DC{DC_EXIT} | SL={SL_PCT*100:.0f}% TP={TP_PCT*100:.0f}% Trail={TRAIL_PCT*100:.0f}%")
    print(f"[dc-correct] Built-in: EMA50 + ADX>20 (always active)")
    print(f"[dc-correct] Testing baseline + {len(extra_keys)} single filters + multi-filter combos\n")

    # Build filter variants: (label, filter_is, filter_oos)
    variants = [("Baseline (EMA50+ADX only)", None, None)]

    for k in extra_keys:
        label = f"+ {k[2:]}"
        # AND combine with state: +1 if extra==+1, -1 if extra==-1, else block
        variants.append((label, pre_is[k], pre_oos[k]))

    # 2-filter combos
    for i in range(len(extra_keys)):
        for j in range(i+1, len(extra_keys)):
            ka, kb = extra_keys[i], extra_keys[j]
            a_is  = pre_is[ka];  b_is  = pre_is[kb]
            a_oos = pre_oos[ka]; b_oos = pre_oos[kb]
            comb_is  = np.where((a_is  == 1)  & (b_is  == 1),  1,
                        np.where((a_is  == -1) & (b_is  == -1), -1, 0)).astype(int)
            comb_oos = np.where((a_oos == 1)  & (b_oos == 1),  1,
                        np.where((a_oos == -1) & (b_oos == -1), -1, 0)).astype(int)
            variants.append((f"+ {ka[2:]} + {kb[2:]}", comb_is, comb_oos))

    results = []
    passes  = []

    print(f"  {'Filter':<45} {'IS n':>5} {'IS PF':>7} | {'OOS n':>5} {'OOS PF':>7} {'MDD%':>7} {'ROI/d%':>8} {'WR%':>6} {'ratio':>6}  Status")
    print("  " + "-" * 120)

    for label, f_is, f_oos in variants:
        is_t  = backtest_correct(pre_is,  f_is)
        oos_t = backtest_correct(pre_oos, f_oos)

        im = metrics(is_t)
        om = metrics(oos_t)

        ratio = round(im["pf"] / om["pf"], 2) if om["pf"] > 0 else 99.0
        gp  = om["pf"]      >= OOS_PF_MIN
        gn  = om["n"]       >= OOS_TRADES_MIN
        gr  = ratio          <= IS_OOS_RATIO_MAX
        gm  = om["mdd_pct"] >= OOS_MDD_MAX
        ok  = all([gp, gn, gr, gm])

        fails = []
        if not gp: fails.append("PF")
        if not gn: fails.append("n")
        if not gr: fails.append("ratio")
        if not gm: fails.append("MDD")
        status = "PASS ✓" if ok else f"FAIL [{','.join(fails)}]"

        row = {
            "filter": label,
            "is_n": im["n"], "is_pf": im["pf"],
            "oos_n": om["n"], "oos_pf": om["pf"],
            "oos_mdd": om["mdd_pct"], "oos_roi_day": om["roi_day"], "oos_wr": om["wr"],
            "ratio": ratio, "PASS": ok,
            "gate_pf": gp, "gate_n": gn, "gate_ratio": gr, "gate_mdd": gm,
        }
        results.append(row)
        if ok: passes.append(row)

        print(
            f"  {label:<45} {im['n']:>5} {im['pf']:>7.3f} | {om['n']:>5} {om['pf']:>7.3f}"
            f" {om['mdd_pct']:>7.1f} {om['roi_day']:>8.4f} {om['wr']:>6.1f} {ratio:>6.2f}"
            f"  {status}"
        )

    results.sort(key=lambda r: r["oos_pf"], reverse=True)
    passes.sort(key=lambda r: r["oos_pf"], reverse=True)

    ts       = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_DIR / f"sweep_dc_correct_ethusdt4h_{ts}.json"
    with open(out_path, "w") as f:
        json.dump(_j({
            "run_ts": ts, "symbol": "ETHUSDT", "tf": "4h",
            "dc_entry": DC_ENTRY, "dc_exit": DC_EXIT,
            "sl_pct": SL_PCT*100, "tp_pct": TP_PCT*100, "trail_pct": TRAIL_PCT*100,
            "n_variants": len(results), "n_passes": len(passes),
            "all_results": results, "passes": passes,
        }), f, indent=2)

    print()
    print("=" * 80)
    print(f"[dc-correct] SUMMARY — {len(passes)}/{len(results)} variants passed Gate 1")
    if passes:
        print("\n  PASSES (sorted by OOS PF):")
        for r in passes:
            print(f"  OOS PF={r['oos_pf']:.3f} n={r['oos_n']} MDD={r['oos_mdd']:.1f}% ROI/d={r['oos_roi_day']:.4f}%  ← {r['filter']}")
    else:
        print("\n  TOP 5 by OOS PF:")
        for r in results[:5]:
            print(f"  OOS PF={r['oos_pf']:.3f} n={r['oos_n']} MDD={r['oos_mdd']:.1f}% ROI/d={r['oos_roi_day']:.4f}%  ← {r['filter']}")
    print(f"\n[dc-correct] Results → {out_path}")


if __name__ == "__main__":
    run()
