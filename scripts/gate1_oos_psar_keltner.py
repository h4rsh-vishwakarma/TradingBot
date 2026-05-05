"""
gate1_oos_psar_keltner.py
=========================
Gate 1 OOS validation for PSAR Volume Surge and Keltner Breakout strategies.

Governance (identical to gate1_oos_discovery.py):
  - $500 fixed notional per trade
  - 0.15%/side commission
  - 70/30 IS/OOS split (last 30% = OOS)
  - Hard gates: OOS PF > 1.0, OOS n >= 50, IS/OOS ratio <= 4x

Candidates:
  - PSAR Volume Surge ("44 psar volume surge 4h") on DOTUSDT/LINKUSDT/AVAXUSDT/XRPUSDT
  - Keltner Breakout  ("24 keltner breakout")     on XRPUSDT/DOTUSDT/LINKUSDT/AVAXUSDT

Run on EC2:  cd /home/ubuntu/tradingview_webhook_bot && python3 scripts/gate1_oos_psar_keltner.py
"""

import json
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from my_strategies_v2 import apply_strategy, calculate_adx

# ── Governance constants ──────────────────────────────────────────────────────
FIXED_NOTIONAL_USD  = 500
COMMISSION_PER_SIDE = 0.0015   # 0.15%
OOS_SPLIT           = 0.30     # last 30% = OOS
ADX_THRESHOLD       = 20

# Per-strategy SL/TP (matching tournament optimization)
PSAR_SL  = 0.015   # 1.5%
PSAR_TP  = 0.060   # 6.0%
KELT_SL  = 0.010   # 1.0%  (Keltner pine default)
KELT_TP  = 0.030   # 3.0%

# Hard gates
OOS_PF_MIN          = 1.0
OOS_TRADES_MIN      = 50
IS_OOS_RATIO_MAX    = 4.0

# Data search paths (in priority order)
DATA_DIRS = [
    "/home/ubuntu/Garima/storage/historical_data/4h",
    "/home/ubuntu/tradingview_webhook_bot/storage/backtest_data",
]

# Candidates: (strategy_id, symbol, mult, length, sl, tp)
# mult/length = tournament-optimal defaults
CANDIDATES = [
    ("44 psar volume surge 4h", "DOTUSDT",  3.54, 22, PSAR_SL, PSAR_TP),
    ("44 psar volume surge 4h", "LINKUSDT", 3.54, 22, PSAR_SL, PSAR_TP),
    ("44 psar volume surge 4h", "AVAXUSDT", 3.54, 22, PSAR_SL, PSAR_TP),
    ("44 psar volume surge 4h", "XRPUSDT",  3.54, 22, PSAR_SL, PSAR_TP),
    ("44 psar volume surge 4h", "SOLUSDT",  3.54, 22, PSAR_SL, PSAR_TP),
    ("24 keltner breakout",     "XRPUSDT",  2.57, 15, KELT_SL, KELT_TP),
    ("24 keltner breakout",     "DOTUSDT",  2.57, 15, KELT_SL, KELT_TP),
    ("24 keltner breakout",     "LINKUSDT", 2.57, 15, KELT_SL, KELT_TP),
    ("24 keltner breakout",     "AVAXUSDT", 2.57, 15, KELT_SL, KELT_TP),
]

RESULTS_DIR = "/home/ubuntu/tradingview_webhook_bot/storage/gate1_results"


# ── Data loading ──────────────────────────────────────────────────────────────

def load_data(symbol: str) -> pd.DataFrame | None:
    """Try parquet then CSV; return OHLCV DataFrame or None."""
    for d in DATA_DIRS:
        for pat in (f"{symbol}_4h.parquet", f"{symbol}_3y_4h.csv", f"{symbol}_5y_4h.csv"):
            p = Path(d) / pat
            if p.exists() and p.stat().st_size > 0:
                try:
                    if pat.endswith(".parquet"):
                        df = pd.read_parquet(p)
                    else:
                        df = pd.read_csv(p, parse_dates=["timestamp"])
                        df = df.rename(columns={"timestamp": "open_time"})
                    df = df.sort_index() if isinstance(df.index, pd.DatetimeIndex) else df
                    # Normalise columns
                    df.columns = [c.lower() for c in df.columns]
                    for col in ("open", "high", "low", "close", "volume"):
                        if col not in df.columns:
                            raise KeyError(f"Missing column: {col}")
                    return df[["open", "high", "low", "close", "volume"]].dropna()
                except Exception as e:
                    print(f"  [warn] {p}: {e}")
    return None


# ── Signal generation ─────────────────────────────────────────────────────────

def generate_signals(df: pd.DataFrame, strat_id: str,
                     mult: float, length: int) -> pd.Series:
    """Strategy signal + ADX(14) > 20 filter. Returns Series of {-1,0,+1}."""
    raw = apply_strategy(df, strat_id, optimize=True, mult=mult, length=length)
    adx = calculate_adx(df, n=14)
    filtered = np.where(adx > ADX_THRESHOLD, raw, 0)
    return pd.Series(filtered, index=df.index, dtype=int)


# ── Simplified trade simulator ────────────────────────────────────────────────

def simulate_trades(df: pd.DataFrame, signals: pd.Series,
                    sl_pct: float, tp_pct: float) -> list[dict]:
    """
    Bar-close-fill simulator.
    Entry at close of signal bar; exit at close when:
      - opposite signal fires, OR
      - SL/TP breached intrabar (checked via high/low), OR
      - end-of-data
    Commission: 0.15%/side on $500 notional.
    """
    opens  = df["open"].values
    highs  = df["high"].values
    lows   = df["low"].values
    closes = df["close"].values
    sigs   = signals.values
    n      = len(sigs)

    trades = []
    in_trade   = False
    direction  = 0
    entry_px   = 0.0
    entry_bar  = -1
    comm_entry = FIXED_NOTIONAL_USD * COMMISSION_PER_SIDE

    for i in range(n):
        if not in_trade:
            if sigs[i] != 0:
                in_trade  = True
                direction = int(sigs[i])
                entry_px  = closes[i]
                entry_bar = i
        else:
            exit_px   = None
            exit_type = None

            # SL/TP intrabar check (pessimistic: assume worst fills)
            if direction == 1:
                sl_price = entry_px * (1 - sl_pct)
                tp_price = entry_px * (1 + tp_pct)
                if lows[i] <= sl_price:
                    exit_px, exit_type = sl_price, "SL"
                elif highs[i] >= tp_price:
                    exit_px, exit_type = tp_price, "TP"
            else:
                sl_price = entry_px * (1 + sl_pct)
                tp_price = entry_px * (1 - tp_pct)
                if highs[i] >= sl_price:
                    exit_px, exit_type = sl_price, "SL"
                elif lows[i] <= tp_price:
                    exit_px, exit_type = tp_price, "TP"

            # Opposite signal (exit at bar close)
            if exit_px is None and sigs[i] != 0 and int(sigs[i]) != direction:
                exit_px, exit_type = closes[i], "SIG"

            # End of data
            if exit_px is None and i == n - 1:
                exit_px, exit_type = closes[i], "EOD"

            if exit_px is not None:
                pnl_pct = direction * (exit_px - entry_px) / entry_px
                pnl_usd = FIXED_NOTIONAL_USD * pnl_pct - 2 * comm_entry
                trades.append({
                    "entry_bar": entry_bar,
                    "exit_bar":  i,
                    "direction": direction,
                    "entry_px":  entry_px,
                    "exit_px":   exit_px,
                    "pnl_usd":   pnl_usd,
                    "exit_type": exit_type,
                })
                in_trade  = False
                direction = 0

                # Immediate re-entry if this bar has a new opposite signal
                if sigs[i] != 0 and int(sigs[i]) != (trades[-1]["direction"] if trades else 0):
                    in_trade  = True
                    direction = int(sigs[i])
                    entry_px  = closes[i]
                    entry_bar = i

    return trades


# ── Metrics ───────────────────────────────────────────────────────────────────

def compute_metrics(trades: list[dict], df: pd.DataFrame) -> dict:
    if not trades:
        return {"n": 0, "pf": 0.0, "roi_pct": 0.0, "wr": 0.0, "mdd_pct": 0.0}

    pnls      = [t["pnl_usd"] for t in trades]
    gross_win = sum(p for p in pnls if p > 0)
    gross_los = abs(sum(p for p in pnls if p < 0))
    pf        = gross_win / gross_los if gross_los > 0 else float("inf")
    total_roi = sum(pnls) / FIXED_NOTIONAL_USD * 100
    wr        = sum(1 for p in pnls if p > 0) / len(pnls)

    # Max drawdown on cumulative PnL curve
    cum = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    dd   = (cum - peak) / FIXED_NOTIONAL_USD * 100
    mdd  = float(dd.min()) if len(dd) > 0 else 0.0

    return {
        "n":       len(trades),
        "pf":      round(pf, 4),
        "roi_pct": round(total_roi, 4),
        "wr":      round(wr * 100, 2),
        "mdd_pct": round(mdd, 4),
    }


# ── Gate 1 check ──────────────────────────────────────────────────────────────

def gate1_check(is_m: dict, oos_m: dict) -> tuple[bool, list[str]]:
    fails = []
    if oos_m["pf"] <= OOS_PF_MIN:
        fails.append(f"OOS PF={oos_m['pf']:.4f} <= {OOS_PF_MIN}")
    if oos_m["n"] < OOS_TRADES_MIN:
        fails.append(f"OOS n={oos_m['n']} < {OOS_TRADES_MIN}")
    ratio = is_m["pf"] / oos_m["pf"] if oos_m["pf"] > 0 else float("inf")
    if ratio > IS_OOS_RATIO_MAX:
        fails.append(f"IS/OOS ratio={ratio:.2f}x > {IS_OOS_RATIO_MAX}x")
    return (len(fails) == 0), fails


# ── Main ─────────────────────────────────────────────────────────────────────

def run_candidate(strat_id: str, symbol: str,
                  mult: float, length: int,
                  sl: float, tp: float) -> dict:
    short_name = strat_id.replace("44 psar volume surge 4h", "PSAR_VolSurge") \
                         .replace("24 keltner breakout", "Keltner_Break")
    label = f"{short_name}/{symbol}"
    print(f"\n{'─'*60}")
    print(f"  Candidate: {label}")
    print(f"  Params:    mult={mult}  length={length}  SL={sl*100:.1f}%  TP={tp*100:.1f}%")

    df = load_data(symbol)
    if df is None:
        print(f"  [SKIP] No data found for {symbol}")
        return {"label": label, "status": "NO_DATA"}

    if len(df) < 300:
        print(f"  [SKIP] Too few bars: {len(df)}")
        return {"label": label, "status": "TOO_FEW_BARS"}

    oos_cut = int(len(df) * (1 - OOS_SPLIT))
    df_is   = df.iloc[:oos_cut].copy()
    df_oos  = df.iloc[oos_cut:].copy()

    print(f"  Data:      {len(df)} bars total  |  "
          f"IS={len(df_is)} bars ({df_is.index[0] if hasattr(df_is.index, '__getitem__') else 'N/A'} to {df_is.index[-1] if hasattr(df_is.index, '__getitem__') else 'N/A'})  |  "
          f"OOS={len(df_oos)} bars")

    sig_is  = generate_signals(df_is,  strat_id, mult, length)
    sig_oos = generate_signals(df_oos, strat_id, mult, length)

    trades_is  = simulate_trades(df_is,  sig_is,  sl, tp)
    trades_oos = simulate_trades(df_oos, sig_oos, sl, tp)

    m_is  = compute_metrics(trades_is,  df_is)
    m_oos = compute_metrics(trades_oos, df_oos)

    passed, fails = gate1_check(m_is, m_oos)
    ratio = m_is["pf"] / m_oos["pf"] if m_oos["pf"] > 0 else float("inf")

    print(f"  IS:        PF={m_is['pf']:.4f}  n={m_is['n']}  "
          f"ROI={m_is['roi_pct']:+.2f}%  WR={m_is['wr']:.1f}%  MDD={m_is['mdd_pct']:.2f}%")
    print(f"  OOS:       PF={m_oos['pf']:.4f}  n={m_oos['n']}  "
          f"ROI={m_oos['roi_pct']:+.2f}%  WR={m_oos['wr']:.1f}%  MDD={m_oos['mdd_pct']:.2f}%")
    print(f"  IS/OOS:    {ratio:.3f}x")
    print(f"  Gate 1:    {'✅ PASS' if passed else '❌ FAIL'}")
    if fails:
        for f in fails:
            print(f"             → {f}")

    return {
        "label":          label,
        "strategy":       strat_id,
        "symbol":         symbol,
        "mult":           mult,
        "length":         length,
        "sl_pct":         sl,
        "tp_pct":         tp,
        "status":         "PASS" if passed else "FAIL",
        "fail_reasons":   fails,
        "is_pf":          m_is["pf"],
        "is_n":           m_is["n"],
        "is_roi_pct":     m_is["roi_pct"],
        "is_wr":          m_is["wr"],
        "is_mdd_pct":     m_is["mdd_pct"],
        "oos_pf":         m_oos["pf"],
        "oos_n":          m_oos["n"],
        "oos_roi_pct":    m_oos["roi_pct"],
        "oos_wr":         m_oos["wr"],
        "oos_mdd_pct":    m_oos["mdd_pct"],
        "is_oos_ratio":   round(ratio, 4),
        "governance":     {
            "notional_usd":    FIXED_NOTIONAL_USD,
            "commission_pct":  COMMISSION_PER_SIDE * 100,
            "oos_split":       OOS_SPLIT,
            "adx_threshold":   ADX_THRESHOLD,
        },
    }


def main():
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    print("=" * 60)
    print(f"  Gate 1 OOS — PSAR Volume Surge + Keltner Breakout")
    print(f"  {ts}")
    print(f"  Governance: ${FIXED_NOTIONAL_USD} fixed, {COMMISSION_PER_SIDE*100:.2f}%/side, "
          f"{int(OOS_SPLIT*100)}% OOS holdout")
    print(f"  Hard gates: OOS PF>{OOS_PF_MIN}, OOS n>={OOS_TRADES_MIN}, "
          f"IS/OOS<={IS_OOS_RATIO_MAX}x")
    print("=" * 60)

    results = []
    for strat_id, symbol, mult, length, sl, tp in CANDIDATES:
        r = run_candidate(strat_id, symbol, mult, length, sl, tp)
        results.append(r)

    passed = [r for r in results if r.get("status") == "PASS"]
    failed = [r for r in results if r.get("status") == "FAIL"]
    skipped = [r for r in results if r.get("status") not in ("PASS", "FAIL")]

    print(f"\n{'='*60}")
    print(f"  SUMMARY:  {len(passed)} PASS  /  {len(failed)} FAIL  /  {len(skipped)} SKIP")
    print("=" * 60)

    if passed:
        print("\n  ✅ GATE 1 PASSED:")
        for r in passed:
            print(f"     {r['label']:40s}  OOS PF={r['oos_pf']:.4f}  "
                  f"IS/OOS={r['is_oos_ratio']:.3f}x  n={r['oos_n']}")

    if failed:
        print("\n  ❌ GATE 1 FAILED:")
        for r in failed:
            print(f"     {r['label']:40s}  → {'; '.join(r['fail_reasons'])}")

    # Save JSON
    Path(RESULTS_DIR).mkdir(parents=True, exist_ok=True)
    out_path = Path(RESULTS_DIR) / f"gate1_psar_keltner_{ts}.json"
    payload = {
        "run_at":      ts,
        "governance":  {
            "notional_usd":    FIXED_NOTIONAL_USD,
            "commission_pct":  COMMISSION_PER_SIDE * 100,
            "oos_split":       OOS_SPLIT,
            "adx_threshold":   ADX_THRESHOLD,
            "gates":           {
                "oos_pf_min":       OOS_PF_MIN,
                "oos_trades_min":   OOS_TRADES_MIN,
                "is_oos_ratio_max": IS_OOS_RATIO_MAX,
            },
        },
        "passed":   passed,
        "failed":   [{"label": r["label"], "fail_reasons": r.get("fail_reasons", [])} for r in failed],
        "skipped":  [r["label"] for r in skipped],
        "all_results": results,
    }
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"\n  Results saved → {out_path}")
    if passed:
        print(f"\n  NEXT STEP: Nominate passing candidates to manifest v26")
        print(f"  Run:  python3 scripts/nominate_gate1_pass.py --results {out_path}")


if __name__ == "__main__":
    main()
