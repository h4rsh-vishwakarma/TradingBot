"""
Gate 1 OOS Validation — auto_alpha_discoveries candidates
==========================================================
Governance standard (matches Pine script commission, Harsh manifest notes):
  - Fixed $500 notional per trade
  - 0.15% commission per side (0.30% round-trip)
  - 70% IS / 30% OOS time-series split (no shuffling)
  - IS/OOS ratio hard gate: <=4x
  - OOS PF hard gate: >1.0
  - OOS n hard gate: >=50 trades

Candidates: Donchian breakout from auto_alpha_discoveries.json
  1. Donchian_40 / BTC / 4H
  2. Donchian_40 / ETH / 4H
  3. Donchian_60 / ETH / 4H
  4. Donchian_40 / SOL / 4H

Output: storage/gate1_results/gate1_oos_<timestamp>.json
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/home/ubuntu/tradingview_webhook_bot")
sys.path.insert(0, str(ROOT))

# ── Governance constants ──────────────────────────────────────────
FIXED_NOTIONAL_USD = 500.0       # $500 per trade — governance standard
COMMISSION_PER_SIDE = 0.0015     # 0.15% — matches Pine script setting
OOS_SPLIT = 0.30                 # last 30% of bars held out
IS_OOS_RATIO_HARD_GATE = 4.0    # reject if is_pf / oos_pf > 4x
OOS_PF_MIN = 1.0                 # OOS must be profitable
OOS_TRADES_MIN = 50              # minimum OOS trade count
INITIAL_CAPITAL = 10_000.0       # starting equity for equity curve

DATA_DIR = Path("/home/ubuntu/Garima/storage/historical_data")
OUTPUT_DIR = ROOT / "storage" / "gate1_results"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Candidates from auto_alpha_discoveries.json ───────────────────
CANDIDATES = [
    {"hash": "dc40_SOLUSDT_4h", "strategy": "Donchian_40", "asset": "SOLUSDT", "tf": "4h", "window": 40},
    {"hash": "dc40_BTCUSDT_4h", "strategy": "Donchian_40", "asset": "BTCUSDT", "tf": "4h", "window": 40},
    {"hash": "dc40_BNBUSDT_4h", "strategy": "Donchian_40", "asset": "BNBUSDT", "tf": "4h", "window": 40},
    {"hash": "dc40_XRPUSDT_4h", "strategy": "Donchian_40", "asset": "XRPUSDT", "tf": "4h", "window": 40},
]


def load_parquet(asset: str, tf: str) -> pd.DataFrame | None:
    """Load 4H parquet data for an asset."""
    pattern = f"{asset}_{tf}_*.parquet"
    matches = sorted(DATA_DIR.glob(pattern))
    if not matches:
        print(f"  [SKIP] No parquet found for {asset} {tf} in {DATA_DIR}")
        return None
    path = matches[0]
    df = pd.read_parquet(path)
    df.columns = [c.lower() for c in df.columns]
    # Ensure we have OHLCV columns
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(set(df.columns)):
        print(f"  [SKIP] {path.name} missing columns: {required - set(df.columns)}")
        return None
    if "timestamp" not in df.columns and df.index.dtype != object:
        df = df.reset_index()
        df.rename(columns={"index": "timestamp", "datetime": "timestamp",
                            "date": "timestamp", "time": "timestamp"}, inplace=True, errors="ignore")
    df = df.sort_values("timestamp").reset_index(drop=True)
    print(f"  Loaded {path.name}: {len(df)} bars  ({str(df['timestamp'].iloc[0])[:10]} → {str(df['timestamp'].iloc[-1])[:10]})")
    return df


def donchian_signals(df: pd.DataFrame, window: int) -> pd.DataFrame:
    """
    Donchian channel breakout signals.
    Long  entry: close crosses above N-bar high (use shift(1) — no lookahead).
    Short entry: close crosses below N-bar low.
    Exit long:   close crosses below N//2-bar low.
    Exit short:  close crosses above N//2-bar high.
    """
    df = df.copy()
    w = window
    w2 = max(window // 2, 5)

    upper = df["high"].rolling(w).max().shift(1)
    lower = df["low"].rolling(w).min().shift(1)
    exit_upper = df["high"].rolling(w2).max().shift(1)
    exit_lower = df["low"].rolling(w2).min().shift(1)

    # Trend filter: EMA200
    ema200 = df["close"].ewm(span=200, adjust=False).mean()

    # ADX filter
    tr = np.maximum(
        df["high"] - df["low"],
        np.maximum(
            (df["high"] - df["close"].shift(1)).abs(),
            (df["low"] - df["close"].shift(1)).abs()
        )
    )
    atr14 = tr.rolling(14).mean()
    up_move = (df["high"] - df["high"].shift(1)).clip(lower=0)
    dn_move = (df["low"].shift(1) - df["low"]).clip(lower=0)
    pdi = 100 * up_move.rolling(14).mean() / atr14
    mdi = 100 * dn_move.rolling(14).mean() / atr14
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    adx = dx.rolling(14).mean().fillna(0)

    trend_up   = (df["close"] > ema200) & (adx > 20)
    trend_down = (df["close"] < ema200) & (adx > 20)

    long_entry  = (df["close"] > upper) & trend_up
    short_entry = (df["close"] < lower) & trend_down
    long_exit   = df["close"] < exit_lower
    short_exit  = df["close"] > exit_upper

    df["long_entry"]  = long_entry.astype(int)
    df["short_entry"] = short_entry.astype(int)
    df["long_exit"]   = long_exit.astype(int)
    df["short_exit"]  = short_exit.astype(int)
    return df


def run_backtest(df: pd.DataFrame, notional: float, commission: float) -> dict:
    """
    Explicit trade-loop backtest with fixed notional and per-side commission.
    Returns dict with: pf, roi_pct, sharpe, mdd_pct, win_rate, n_trades,
                       gross_profit, gross_loss, equity_curve.
    """
    capital = INITIAL_CAPITAL
    equity_curve = [capital]
    trades = []
    position = 0   # 0=flat, 1=long, -1=short
    entry_price = 0.0

    close = df["close"].values
    long_entry  = df["long_entry"].values
    short_entry = df["short_entry"].values
    long_exit   = df["long_exit"].values
    short_exit  = df["short_exit"].values

    for i in range(1, len(df)):
        c = close[i]

        if position == 1:
            if long_exit[i] or short_entry[i]:
                size = notional / entry_price
                pnl = (c - entry_price) * size
                pnl -= (commission * notional)          # exit commission
                capital += pnl
                trades.append(pnl)
                position = 0
                equity_curve.append(capital)
                if short_entry[i] and capital > 0:
                    entry_price = c
                    capital -= commission * notional    # entry commission
                    position = -1

        elif position == -1:
            if short_exit[i] or long_entry[i]:
                size = notional / entry_price
                pnl = (entry_price - c) * size
                pnl -= (commission * notional)          # exit commission
                capital += pnl
                trades.append(pnl)
                position = 0
                equity_curve.append(capital)
                if long_entry[i] and capital > 0:
                    entry_price = c
                    capital -= commission * notional    # entry commission
                    position = 1

        else:  # flat
            if long_entry[i] and capital > 0:
                entry_price = c
                capital -= commission * notional
                position = 1
            elif short_entry[i] and capital > 0:
                entry_price = c
                capital -= commission * notional
                position = -1

        equity_curve.append(capital)

    # Close any open position at last bar
    if position != 0 and entry_price > 0:
        c = close[-1]
        size = notional / entry_price
        if position == 1:
            pnl = (c - entry_price) * size - commission * notional
        else:
            pnl = (entry_price - c) * size - commission * notional
        capital += pnl
        trades.append(pnl)
        equity_curve.append(capital)

    if not trades:
        return {"pf": 0.0, "roi_pct": 0.0, "sharpe": 0.0, "mdd_pct": 0.0,
                "win_rate": 0.0, "n_trades": 0, "gross_profit": 0.0, "gross_loss": 0.0}

    gross_profit = sum(t for t in trades if t > 0)
    gross_loss   = abs(sum(t for t in trades if t < 0))
    pf = gross_profit / gross_loss if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

    winners = sum(1 for t in trades if t > 0)
    win_rate = winners / len(trades) * 100 if trades else 0.0

    roi_pct = (capital - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    # Sharpe on trade returns (annualized approximation)
    t_arr = np.array(trades, dtype=float) / INITIAL_CAPITAL
    sharpe = (t_arr.mean() / t_arr.std() * np.sqrt(len(trades))) if t_arr.std() > 0 else 0.0

    # MDD on equity curve
    eq = np.array(equity_curve, dtype=float)
    roll_max = np.maximum.accumulate(eq)
    drawdowns = (eq - roll_max) / roll_max * 100
    mdd_pct = float(drawdowns.min())

    return {
        "pf": round(float(pf), 4),
        "roi_pct": round(float(roi_pct), 3),
        "sharpe": round(float(sharpe), 3),
        "mdd_pct": round(float(mdd_pct), 3),
        "win_rate": round(float(win_rate), 2),
        "n_trades": len(trades),
        "gross_profit": round(float(gross_profit), 2),
        "gross_loss": round(float(gross_loss), 2),
    }


def gate1_check(is_pf: float, oos_pf: float, oos_n: int) -> tuple[bool, list[str]]:
    """Apply all Gate 1 hard gates. Returns (passes, list_of_failures)."""
    failures = []
    if oos_pf < OOS_PF_MIN:
        failures.append(f"OOS PF={oos_pf:.4f} < {OOS_PF_MIN} (hard fail)")
    if oos_n < OOS_TRADES_MIN:
        failures.append(f"OOS n={oos_n} < {OOS_TRADES_MIN} minimum trades")
    if is_pf > 0 and oos_pf > 0:
        ratio = is_pf / oos_pf
        if ratio > IS_OOS_RATIO_HARD_GATE:
            failures.append(f"IS/OOS ratio={ratio:.2f}x > {IS_OOS_RATIO_HARD_GATE}x (hard fail)")
    elif oos_pf <= 0:
        failures.append("OOS PF<=0 — no profitable trades in OOS period")
    return len(failures) == 0, failures


def run_gate1():
    results = []
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    print("=" * 70)
    print("GATE 1 OOS VALIDATION — auto_alpha_discoveries candidates")
    print(f"Notional: ${FIXED_NOTIONAL_USD}  Commission: {COMMISSION_PER_SIDE*100:.2f}%/side  OOS split: {int(OOS_SPLIT*100)}%")
    print(f"Gates: OOS PF>{OOS_PF_MIN}  OOS n>={OOS_TRADES_MIN}  IS/OOS ratio<={IS_OOS_RATIO_HARD_GATE}x")
    print("=" * 70)

    for cand in CANDIDATES:
        print(f"\n{'─'*60}")
        print(f"Candidate: {cand['strategy']} | {cand['asset']} | {cand['tf']} | window={cand['window']}")

        df = load_parquet(cand["asset"], cand["tf"])
        if df is None:
            continue

        df = donchian_signals(df, cand["window"])
        df = df.dropna(subset=["long_entry", "short_entry"]).reset_index(drop=True)

        # 70/30 time-series split
        split_idx = int(len(df) * (1 - OOS_SPLIT))
        df_is  = df.iloc[:split_idx].reset_index(drop=True)
        df_oos = df.iloc[split_idx:].reset_index(drop=True)

        is_start  = str(df_is["timestamp"].iloc[0])[:10]
        is_end    = str(df_is["timestamp"].iloc[-1])[:10]
        oos_start = str(df_oos["timestamp"].iloc[0])[:10]
        oos_end   = str(df_oos["timestamp"].iloc[-1])[:10]

        print(f"  IS  period: {is_start} → {is_end}  ({len(df_is)} bars)")
        print(f"  OOS period: {oos_start} → {oos_end}  ({len(df_oos)} bars)")

        is_result  = run_backtest(df_is,  FIXED_NOTIONAL_USD, COMMISSION_PER_SIDE)
        oos_result = run_backtest(df_oos, FIXED_NOTIONAL_USD, COMMISSION_PER_SIDE)

        is_pf    = is_result["pf"]
        oos_pf   = oos_result["pf"]
        oos_n    = oos_result["n_trades"]
        ratio    = round(is_pf / oos_pf, 3) if oos_pf > 0 else 999.0
        passes, failures = gate1_check(is_pf, oos_pf, oos_n)

        print(f"\n  IS  Results:  PF={is_pf:.4f}  ROI={is_result['roi_pct']:+.2f}%  WR={is_result['win_rate']:.1f}%  MDD={is_result['mdd_pct']:.2f}%  n={is_result['n_trades']}")
        print(f"  OOS Results:  PF={oos_pf:.4f}  ROI={oos_result['roi_pct']:+.2f}%  WR={oos_result['win_rate']:.1f}%  MDD={oos_result['mdd_pct']:.2f}%  n={oos_n}")
        print(f"  IS/OOS ratio: {ratio}x")

        if passes:
            print(f"  Gate 1: *** PASS ***")
        else:
            print(f"  Gate 1: FAIL")
            for f in failures:
                print(f"    - {f}")

        rec = {
            "hash":        cand["hash"],
            "strategy":    cand["strategy"],
            "asset":       cand["asset"],
            "timeframe":   cand["tf"],
            "window":      cand["window"],
            "is_period":   {"start": is_start, "end": is_end, "bars": len(df_is)},
            "oos_period":  {"start": oos_start, "end": oos_end, "bars": len(df_oos)},
            "is":          is_result,
            "oos":         oos_result,
            "is_oos_ratio": ratio,
            "gate1_pass":  passes,
            "gate1_failures": failures,
            "governance": {
                "fixed_notional_usd": FIXED_NOTIONAL_USD,
                "commission_per_side_pct": COMMISSION_PER_SIDE * 100,
                "oos_split_pct": OOS_SPLIT * 100,
                "run_at": timestamp,
            },
        }
        results.append(rec)

    # Summary
    passed  = [r for r in results if r["gate1_pass"]]
    failed  = [r for r in results if not r["gate1_pass"]]

    print(f"\n{'='*70}")
    print(f"GATE 1 SUMMARY: {len(passed)} PASS / {len(failed)} FAIL / {len(results)} total")
    print(f"{'='*70}")

    if passed:
        print("\nPASSED — eligible for P-07 paper window nomination:")
        for r in passed:
            print(f"  *** {r['strategy']} {r['asset']} — OOS PF={r['oos']['pf']:.4f}  IS/OOS={r['is_oos_ratio']}x  OOS n={r['oos']['n_trades']}")

    if failed:
        print("\nFAILED — not eligible:")
        for r in failed:
            print(f"  --- {r['strategy']} {r['asset']}")
            for fail in r["gate1_failures"]:
                print(f"        {fail}")

    # Write output
    out_file = OUTPUT_DIR / f"gate1_oos_{timestamp}.json"
    with open(out_file, "w") as f:
        json.dump({
            "run_at": timestamp,
            "governance_standard": {
                "fixed_notional_usd": FIXED_NOTIONAL_USD,
                "commission_per_side_pct": COMMISSION_PER_SIDE * 100,
                "oos_split_pct": OOS_SPLIT * 100,
                "is_oos_ratio_gate": IS_OOS_RATIO_HARD_GATE,
                "oos_pf_min": OOS_PF_MIN,
                "oos_trades_min": OOS_TRADES_MIN,
            },
            "summary": {
                "total": len(results),
                "passed": len(passed),
                "failed": len(failed),
                "passed_ids": [f"{r['strategy']}_{r['asset']}" for r in passed],
            },
            "results": results,
        }, f, indent=2)

    print(f"\nResults saved: {out_file}")
    return results


if __name__ == "__main__":
    run_gate1()
