#!/usr/bin/env python3
"""
gate1_oos_g27_cci_donchian.py
==============================
Gate 1 OOS validation for G27 CCI Donchian Wide.

Strategy (from backtesting/pine/G27 CCI Donchian Wide):
  Entry (EITHER trigger, not both required):
    Long:  (close > dc_upper[1] OR cci crosses above 100) AND close > EMA50 AND ADX > 18 AND vol_ok
    Short: (close < dc_lower[1] OR cci crosses below -100) AND close < EMA50 AND ADX > 18 AND vol_ok

  Exit:
    Long:  close < exit_lower[1] OR CCI crossunder 0 OR RSI > 80 → signal exit at close
           OR SL=1.5% / TP=15% / Trail=3.5% (activates after 3.5% favorable move)
    Short: close > exit_upper[1] OR CCI crossover 0 OR RSI < 20 → signal exit at close
           OR SL=1.5% / TP=15% / Trail=3.5%

  Anti-overtrading:
    - Max 3 closed trades per calendar day
    - Cooldown: 6 bars after 3 consecutive losses
    - Volatility filter: ATR(14) < SMA(ATR,100) * 2

Governance (Gate 1 standard):
  $500 fixed notional, 0.15%/side commission, 70/30 IS/OOS split
  Hard gates: OOS PF >= 1.5, OOS n >= 50, IS/OOS PF ratio <= 4x, OOS MDD >= -15%

Candidates (symbols with 4H data available):
  AVAXUSDT, LDOUSDT, LINKUSDT, SUIUSDT  (MAGICUSDT: no data file — skipped)
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

# ─── Governance constants ──────────────────────────────────────────────────────
FIXED_NOTIONAL   = 500.0
COMMISSION_SIDE  = 0.0015   # 0.15% per side
OOS_SPLIT        = 0.30
OOS_PF_MIN       = 1.5
OOS_N_MIN        = 50
IS_OOS_RATIO_MAX = 4.0
OOS_MDD_MAX      = -15.0    # %

# ─── Strategy parameters (from Pine script) ────────────────────────────────────
DC_LEN     = 20
DC_EXIT    = 10
CCI_LEN    = 20
EMA_LEN    = 50
ADX_LEN    = 14
ADX_THR    = 18
ATR_LEN    = 14
ATR_MA_LEN = 100
RSI_LEN    = 14
SL_PCT     = 0.015    # 1.5%
TP_PCT     = 0.150    # 15.0%
TRAIL_PCT  = 0.035    # 3.5%
MAX_TRADES_DAY  = 3
CONSEC_LOSS_MAX = 3
COOLDOWN_BARS   = 6

DATA_DIR    = Path("/home/ubuntu/tradingview_webhook_bot/storage/backtest_data")
RESULTS_DIR = Path("/home/ubuntu/tradingview_webhook_bot/storage/gate1_results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

CANDIDATES = [
    ("G27_CCI_Donchian_Wide", "AVAXUSDT",  "4h", "AVAXUSDT_5y_4h.csv"),
    ("G27_CCI_Donchian_Wide", "LDOUSDT",   "4h", "LDOUSDT_5y_4h.csv"),
    ("G27_CCI_Donchian_Wide", "LINKUSDT",  "4h", "LINKUSDT_5y_4h.csv"),
    ("G27_CCI_Donchian_Wide", "SUIUSDT",   "4h", "SUIUSDT_5y_4h.csv"),
]


# ─── Indicators ────────────────────────────────────────────────────────────────

def compute_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def compute_atr(df: pd.DataFrame, period: int) -> pd.Series:
    hi, lo, cl = df["high"], df["low"], df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - cl).abs(),
        (df["low"]  - cl).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def compute_rsi(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def compute_cci(df: pd.DataFrame, period: int) -> pd.Series:
    tp   = (df["high"] + df["low"] + df["close"]) / 3
    sma  = tp.rolling(period).mean()
    mad  = tp.rolling(period).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    return (tp - sma) / (0.015 * mad)


def compute_adx(df: pd.DataFrame, period: int) -> pd.Series:
    hi  = df["high"]
    lo  = df["low"]
    cl  = df["close"]
    tr  = pd.concat([
        hi - lo,
        (hi - cl.shift(1)).abs(),
        (lo - cl.shift(1)).abs(),
    ], axis=1).max(axis=1)
    plus_dm  = np.where((hi - hi.shift(1)) > (lo.shift(1) - lo), (hi - hi.shift(1)).clip(lower=0), 0)
    minus_dm = np.where((lo.shift(1) - lo) > (hi - hi.shift(1)), (lo.shift(1) - lo).clip(lower=0), 0)

    atr_s    = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di  = 100 * pd.Series(plus_dm,  index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr_s
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr_s
    dx       = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9)
    return dx.ewm(alpha=1 / period, adjust=False).mean()


def build_signals(df: pd.DataFrame) -> pd.DataFrame:
    ema50       = compute_ema(df["close"], EMA_LEN)
    atr14       = compute_atr(df, ATR_LEN)
    atr_ma      = atr14.rolling(ATR_MA_LEN).mean()
    cci         = compute_cci(df, CCI_LEN)
    adx         = compute_adx(df, ADX_LEN)
    rsi         = compute_rsi(df["close"], RSI_LEN)

    dc_upper    = df["high"].rolling(DC_LEN).max()
    dc_lower    = df["low"].rolling(DC_LEN).min()
    exit_upper  = df["high"].rolling(DC_EXIT).max()
    exit_lower  = df["low"].rolling(DC_EXIT).min()

    breakout_up   = df["close"] > dc_upper.shift(1)
    breakout_down = df["close"] < dc_lower.shift(1)

    cci_cross_up   = (cci >= 100)  & (cci.shift(1) < 100)
    cci_cross_down = (cci <= -100) & (cci.shift(1) > -100)
    cci_cross_zero_up   = (cci >= 0)  & (cci.shift(1) < 0)
    cci_cross_zero_down = (cci <= 0)  & (cci.shift(1) > 0)

    vol_ok = atr14 < atr_ma * 2

    long_trigger  = breakout_up   | cci_cross_up
    short_trigger = breakout_down | cci_cross_down

    long_entry   = long_trigger  & (df["close"] > ema50) & (adx > ADX_THR) & vol_ok
    short_entry  = short_trigger & (df["close"] < ema50) & (adx > ADX_THR) & vol_ok

    # Signal-based exits (close of bar)
    long_sig_exit  = (df["close"] < exit_lower.shift(1)) | cci_cross_zero_down | (rsi > 80)
    short_sig_exit = (df["close"] > exit_upper.shift(1)) | cci_cross_zero_up   | (rsi < 20)

    return pd.DataFrame({
        "close":          df["close"],
        "high":           df["high"],
        "low":            df["low"],
        "long_entry":     long_entry,
        "short_entry":    short_entry,
        "long_sig_exit":  long_sig_exit,
        "short_sig_exit": short_sig_exit,
        "vol_ok":         vol_ok,
        "cci":            cci,
        "adx":            adx,
        "rsi":            rsi,
    }, index=df.index)


# ─── Backtest ──────────────────────────────────────────────────────────────────

def backtest(sig: pd.DataFrame) -> list[dict]:
    n   = len(sig)
    pos = 0          # 0=flat, 1=long, -1=short
    entry_price = 0.0
    entry_idx   = 0
    hwm = 0.0        # high-water-mark (long)
    lwm = 0.0        # low-water-mark (short)
    trail_active = False

    trades_today  = 0
    consec_losses = 0
    cooldown      = 0
    last_day      = None

    trades = []

    close_arr = sig["close"].values
    high_arr  = sig["high"].values
    low_arr   = sig["low"].values
    dates     = sig.index

    for i in range(1, n):
        bar_date = pd.Timestamp(dates[i]).date()

        # Reset daily trade counter
        if bar_date != last_day:
            trades_today = 0
            last_day = bar_date

        if cooldown > 0:
            cooldown -= 1

        c = close_arr[i]
        h = high_arr[i]
        lo = low_arr[i]

        # ── Exit check ────────────────────────────────────────────────────────
        if pos != 0:
            exit_price  = None
            exit_reason = None

            if pos == 1:   # Long
                if h > hwm:
                    hwm = h
                trail_stop = None
                if hwm >= entry_price * (1 + TRAIL_PCT):
                    trail_active = True
                if trail_active:
                    trail_stop = hwm * (1 - TRAIL_PCT)

                sl = entry_price * (1 - SL_PCT)
                tp = entry_price * (1 + TP_PCT)

                if trail_active and trail_stop and lo <= trail_stop:
                    exit_price = trail_stop;  exit_reason = "TRAIL"
                elif not trail_active and lo <= sl:
                    exit_price = sl;          exit_reason = "SL"
                elif h >= tp:
                    exit_price = tp;          exit_reason = "TP"
                elif sig["long_sig_exit"].iloc[i]:
                    exit_price = c;           exit_reason = "SIGNAL"

            else:          # Short
                if lo < lwm:
                    lwm = lo
                trail_stop = None
                if lwm <= entry_price * (1 - TRAIL_PCT):
                    trail_active = True
                if trail_active:
                    trail_stop = lwm * (1 + TRAIL_PCT)

                sl = entry_price * (1 + SL_PCT)
                tp = entry_price * (1 - TP_PCT)

                if trail_active and trail_stop and h >= trail_stop:
                    exit_price = trail_stop;  exit_reason = "TRAIL"
                elif not trail_active and h >= sl:
                    exit_price = sl;          exit_reason = "SL"
                elif lo <= tp:
                    exit_price = tp;          exit_reason = "TP"
                elif sig["short_sig_exit"].iloc[i]:
                    exit_price = c;           exit_reason = "SIGNAL"

            if exit_price is not None:
                mult    = 1 if pos == 1 else -1
                gross   = FIXED_NOTIONAL * (exit_price - entry_price) / entry_price * mult
                cost    = FIXED_NOTIONAL * COMMISSION_SIDE * 2
                net_pnl = gross - cost
                trades.append({
                    "entry_idx": entry_idx, "exit_idx": i,
                    "side": "long" if pos == 1 else "short",
                    "entry": entry_price, "exit": exit_price,
                    "reason": exit_reason, "pnl": net_pnl,
                })
                trades_today += 1
                if net_pnl < 0:
                    consec_losses += 1
                    if consec_losses >= CONSEC_LOSS_MAX:
                        cooldown = COOLDOWN_BARS
                        consec_losses = 0
                else:
                    consec_losses = 0
                pos = 0
                trail_active = False

        # ── Entry check ───────────────────────────────────────────────────────
        if pos == 0 and cooldown == 0 and trades_today < MAX_TRADES_DAY:
            if sig["long_entry"].iloc[i]:
                pos = 1;  entry_price = c;  entry_idx = i;  hwm = c;  trail_active = False
            elif sig["short_entry"].iloc[i]:
                pos = -1; entry_price = c;  entry_idx = i;  lwm = c;  trail_active = False

    return trades


# ─── Metrics ───────────────────────────────────────────────────────────────────

def metrics(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0, "pf": 0.0, "mdd_pct": 0.0, "roi_day": 0.0, "wr": 0.0}

    pnls    = [t["pnl"] for t in trades]
    gross_w = sum(p for p in pnls if p > 0)
    gross_l = abs(sum(p for p in pnls if p < 0))
    pf      = gross_w / gross_l if gross_l > 0 else float("inf")

    eq = 0.0; peak = 0.0; min_dd = 0.0
    for p in pnls:
        eq += p
        if eq > peak:
            peak = eq
        if peak > 0:
            dd = (eq - peak) / peak * 100
            if dd < min_dd:
                min_dd = dd

    n_bars  = trades[-1]["exit_idx"] - trades[0]["entry_idx"] if len(trades) > 1 else 1
    n_days  = n_bars * 4 / 24   # 4h candles
    roi_day = (sum(pnls) / FIXED_NOTIONAL / max(n_days, 1)) * 100
    winners = sum(1 for p in pnls if p > 0)

    return {
        "n":       len(trades),
        "pf":      round(pf,      3),
        "mdd_pct": round(min_dd,  2),
        "roi_day": round(roi_day, 4),
        "wr":      round(winners / len(trades) * 100, 1),
    }


# ─── Main ──────────────────────────────────────────────────────────────────────

def run():
    results = []
    ts      = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    print(f"Gate 1 OOS — G27 CCI Donchian Wide")
    print(f"SL={SL_PCT*100:.1f}%  TP={TP_PCT*100:.1f}%  Trail={TRAIL_PCT*100:.1f}%")
    print(f"Governance: ${FIXED_NOTIONAL} fixed, {COMMISSION_SIDE*100:.2f}%/side, {int((1-OOS_SPLIT)*100)}/{int(OOS_SPLIT*100)} IS/OOS")
    print(f"Hard gates: OOS PF≥{OOS_PF_MIN}  n≥{OOS_N_MIN}  IS/OOS≤{IS_OOS_RATIO_MAX}x  MDD≥{OOS_MDD_MAX}%")
    print()

    for strat, symbol, tf, fname in CANDIDATES:
        fpath = DATA_DIR / fname
        if not fpath.exists():
            print(f"[SKIP] {symbol}: {fpath} not found")
            continue

        df = pd.read_csv(fpath)
        df.columns = [c.lower() for c in df.columns]
        for col in ("open", "high", "low", "close", "volume"):
            if col not in df.columns:
                print(f"[SKIP] {symbol}: missing column {col}")
                break
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            df.dropna(subset=["open","high","low","close"], inplace=True)
            df.reset_index(drop=True, inplace=True)

            # Parse date for day-based anti-overtrading
            date_col = next((c for c in df.columns if "time" in c or "date" in c), None)
            if date_col:
                df.index = pd.to_datetime(df[date_col], unit="ms", errors="coerce")
            else:
                df.index = pd.RangeIndex(len(df))

            split_idx = int(len(df) * (1 - OOS_SPLIT))
            df_is  = df.iloc[:split_idx].copy()
            df_oos = df.iloc[split_idx:].copy()

            sig_is  = build_signals(df_is)
            sig_oos = build_signals(df_oos)

            is_trades  = backtest(sig_is)
            oos_trades = backtest(sig_oos)

            is_m  = metrics(is_trades)
            oos_m = metrics(oos_trades)

            ratio = round(is_m["pf"] / oos_m["pf"], 2) if oos_m["pf"] > 0 else 99.0

            gate_pf    = oos_m["pf"]      >= OOS_PF_MIN
            gate_n     = oos_m["n"]        >= OOS_N_MIN
            gate_ratio = ratio             <= IS_OOS_RATIO_MAX
            gate_mdd   = oos_m["mdd_pct"] >= OOS_MDD_MAX
            passed     = all([gate_pf, gate_n, gate_ratio, gate_mdd])

            gates = []
            if not gate_pf:    gates.append(f"OOS_PF={oos_m['pf']} <{OOS_PF_MIN}")
            if not gate_n:     gates.append(f"n={oos_m['n']} <{OOS_N_MIN}")
            if not gate_ratio: gates.append(f"ratio={ratio} >{IS_OOS_RATIO_MAX}x")
            if not gate_mdd:   gates.append(f"MDD={oos_m['mdd_pct']}% <{OOS_MDD_MAX}%")

            verdict = "PASS ✓" if passed else f"FAIL ({'; '.join(gates)})"

            print(f"  [{symbol}]  IS bars={len(df_is)}  OOS bars={len(df_oos)}")
            print(f"    IS:  n={is_m['n']:3d}  PF={is_m['pf']:.3f}  MDD={is_m['mdd_pct']:.1f}%  ROI={is_m['roi_day']:.4f}%/d  WR={is_m['wr']:.1f}%")
            print(f"    OOS: n={oos_m['n']:3d}  PF={oos_m['pf']:.3f}  MDD={oos_m['mdd_pct']:.1f}%  ROI={oos_m['roi_day']:.4f}%/d  WR={oos_m['wr']:.1f}%")
            print(f"    IS/OOS ratio={ratio:.2f}x  |  {verdict}")
            print()

            results.append({
                "symbol": symbol, "timeframe": tf,
                "is_bars": int(len(df_is)), "oos_bars": int(len(df_oos)),
                "is_n": is_m["n"],   "is_pf": is_m["pf"],   "is_mdd": is_m["mdd_pct"],
                "is_roi_day": is_m["roi_day"],   "is_wr": is_m["wr"],
                "oos_n": oos_m["n"], "oos_pf": oos_m["pf"], "oos_mdd": oos_m["mdd_pct"],
                "oos_roi_day": oos_m["roi_day"], "oos_wr": oos_m["wr"],
                "is_oos_ratio": ratio,
                "gate_pf": gate_pf, "gate_n": gate_n, "gate_ratio": gate_ratio, "gate_mdd": gate_mdd,
                "PASS": passed, "fail_reasons": gates,
            })

    passes = [r for r in results if r["PASS"]]
    print(f"{'='*60}")
    print(f"RESULT: {len(passes)}/{len(results)} symbols passed Gate 1")
    if passes:
        print(f"PASS list:")
        for r in passes:
            print(f"  {r['symbol']}: OOS PF={r['oos_pf']}  n={r['oos_n']}  MDD={r['oos_mdd']}%  ROI={r['oos_roi_day']}%/d  WR={r['oos_wr']}%")
    print(f"{'='*60}")

    def _j(obj):
        if isinstance(obj, dict):  return {k: _j(v) for k, v in obj.items()}
        if isinstance(obj, list):  return [_j(v) for v in obj]
        if isinstance(obj, (np.bool_,)):   return bool(obj)
        if isinstance(obj, (np.integer,)): return int(obj)
        if isinstance(obj, (np.floating,)): return float(obj)
        return obj

    out = RESULTS_DIR / f"gate1_oos_g27_cci_donchian_{ts}.json"
    with open(out, "w") as f:
        json.dump(_j({
            "strategy": "G27 CCI Donchian Wide",
            "run_ts": ts,
            "governance": {
                "notional": FIXED_NOTIONAL, "commission_side_pct": COMMISSION_SIDE*100,
                "oos_split": OOS_SPLIT, "sl_pct": SL_PCT*100, "tp_pct": TP_PCT*100,
                "trail_pct": TRAIL_PCT*100,
            },
            "results": results,
        }), f, indent=2)
    print(f"Results → {out}")


if __name__ == "__main__":
    run()
