"""
gate1_oos_supertrend_adx.py
===========================
Gate 1 OOS validation for Supertrend + ADX strategy family.

Governance (identical to gate1_oos_psar_keltner.py):
  - $500 fixed notional per trade
  - 0.15%/side commission
  - 70/30 IS/OOS split (last 30% = OOS)
  - Hard gates: OOS PF > 1.5, OOS n >= 50, IS/OOS ratio <= 4x, OOS MDD <= 15%

Strategy logic:
  - Supertrend(period, mult): bullish when close > upper band, bearish when close < lower band
  - ADX(14) > 20 filter on every entry
  - SL: 2.0%, TP: 6.0% (Donchian-equivalent conservative defaults)

Candidates:
  G4-01: Supertrend_ADX / ETHUSDT / 1H
  G4-02: Supertrend_ADX / DOTUSDT / 4H
  G4-03: Supertrend_ADX / LINKUSDT / 4H
  G4-04: Supertrend_ADX / ETHUSDT / 4H  (bonus run)

Run:  cd /home/ubuntu/tradingview_webhook_bot && python3 scripts/gate1_oos_supertrend_adx.py
"""

import json
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Governance constants
FIXED_NOTIONAL_USD  = 500
COMMISSION_PER_SIDE = 0.0015   # 0.15%
OOS_SPLIT           = 0.30     # last 30% = OOS
ADX_PERIOD          = 14
ADX_THRESHOLD       = 20

# Default Supertrend params (standard values)
ST_PERIOD = 10
ST_MULT   = 3.0

# SL/TP
SL_PCT = 0.020   # 2.0%
TP_PCT = 0.060   # 6.0%

# Hard gates
OOS_PF_MIN       = 1.5
OOS_TRADES_MIN   = 50
IS_OOS_RATIO_MAX = 4.0
OOS_MDD_MAX      = -15.0   # max allowed drawdown (%)

DATA_DIR   = Path("/home/ubuntu/tradingview_webhook_bot/storage/backtest_data")
RESULTS_DIR = Path("/home/ubuntu/tradingview_webhook_bot/storage/gate1_results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

CANDIDATES = [
    ("Supertrend_ADX", "ETHUSDT",  "1h",  "ETHUSDT_3y_1h.csv"),
    ("Supertrend_ADX", "DOTUSDT",  "4h",  "DOTUSDT_3y_4h.csv"),
    ("Supertrend_ADX", "LINKUSDT", "4h",  "LINKUSDT_3y_4h.csv"),
    ("Supertrend_ADX", "ETHUSDT",  "4h",  "ETHUSDT_5y_4h.csv"),
]


def load_data(filename: str) -> pd.DataFrame | None:
    p = DATA_DIR / filename
    if not p.exists():
        print(f"  [SKIP] File not found: {p}")
        return None
    try:
        df = pd.read_csv(p)
        df.columns = [c.lower() for c in df.columns]
        for col in ("open", "high", "low", "close", "volume"):
            if col not in df.columns:
                raise KeyError(f"Missing column: {col}")
        return df[["open", "high", "low", "close", "volume"]].dropna().reset_index(drop=True)
    except Exception as e:
        print(f"  [ERROR] {p}: {e}")
        return None


def calculate_atr(df: pd.DataFrame, period: int) -> pd.Series:
    high = df["high"]
    low  = df["low"]
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def calculate_supertrend(df: pd.DataFrame, period: int = ST_PERIOD, mult: float = ST_MULT):
    """Returns (signal_series, upper_band, lower_band). Signal: +1=bullish, -1=bearish, 0=neutral."""
    hl2 = (df["high"] + df["low"]) / 2.0
    atr = calculate_atr(df, period)

    upper_basic = hl2 + mult * atr
    lower_basic = hl2 - mult * atr

    n = len(df)
    upper = upper_basic.copy().values
    lower = lower_basic.copy().values
    closes = df["close"].values

    # Dynamic band calculation
    for i in range(1, n):
        if np.isnan(upper_basic.iloc[i]):
            continue
        upper[i] = upper_basic.iloc[i] if (upper_basic.iloc[i] < upper[i-1] or closes[i-1] > upper[i-1]) else upper[i-1]
        lower[i] = lower_basic.iloc[i] if (lower_basic.iloc[i] > lower[i-1] or closes[i-1] < lower[i-1]) else lower[i-1]

    # Direction
    direction = np.zeros(n, dtype=int)
    for i in range(1, n):
        if closes[i] > upper[i]:
            direction[i] = 1
        elif closes[i] < lower[i]:
            direction[i] = -1
        else:
            direction[i] = direction[i-1]

    return pd.Series(direction, index=df.index)


def calculate_adx(df: pd.DataFrame, period: int = ADX_PERIOD) -> pd.Series:
    high  = df["high"]
    low   = df["low"]
    close = df["close"]

    up   = high.diff()
    down = -low.diff()
    plus_dm  = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)

    atr = calculate_atr(df, period)
    plus_di  = pd.Series(plus_dm,  index=df.index).rolling(period).sum() / atr / period * 100
    minus_di = pd.Series(minus_dm, index=df.index).rolling(period).sum() / atr / period * 100

    dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)) * 100
    adx = dx.rolling(period).mean()
    return adx.fillna(0)


def generate_signals(df: pd.DataFrame) -> pd.Series:
    st  = calculate_supertrend(df)
    adx = calculate_adx(df)
    filtered = np.where(adx > ADX_THRESHOLD, st, 0)
    return pd.Series(filtered, index=df.index, dtype=int)


def simulate_trades(df: pd.DataFrame, signals: pd.Series) -> list[dict]:
    opens  = df["open"].values
    highs  = df["high"].values
    lows   = df["low"].values
    closes = df["close"].values
    sigs   = signals.values
    n      = len(sigs)

    trades    = []
    in_trade  = False
    direction = 0
    entry_px  = 0.0
    entry_bar = -1
    comm      = FIXED_NOTIONAL_USD * COMMISSION_PER_SIDE

    for i in range(n):
        if not in_trade:
            if sigs[i] != 0:
                in_trade  = True
                direction = int(sigs[i])
                entry_px  = closes[i]
                entry_bar = i
        else:
            exit_px = exit_type = None

            if direction == 1:
                sl_px = entry_px * (1 - SL_PCT)
                tp_px = entry_px * (1 + TP_PCT)
                if lows[i] <= sl_px:
                    exit_px, exit_type = sl_px, "SL"
                elif highs[i] >= tp_px:
                    exit_px, exit_type = tp_px, "TP"
            else:
                sl_px = entry_px * (1 + SL_PCT)
                tp_px = entry_px * (1 - TP_PCT)
                if highs[i] >= sl_px:
                    exit_px, exit_type = sl_px, "SL"
                elif lows[i] <= tp_px:
                    exit_px, exit_type = tp_px, "TP"

            if exit_px is None and sigs[i] != 0 and int(sigs[i]) != direction:
                exit_px, exit_type = closes[i], "SIG"

            if exit_px is None and i == n - 1:
                exit_px, exit_type = closes[i], "EOD"

            if exit_px is not None:
                pnl = direction * (exit_px - entry_px) / entry_px * FIXED_NOTIONAL_USD - 2 * comm
                trades.append({"entry_bar": entry_bar, "exit_bar": i,
                               "direction": direction, "entry_px": entry_px,
                               "exit_px": exit_px, "pnl_usd": pnl, "exit_type": exit_type})
                in_trade = False

                if sigs[i] != 0 and int(sigs[i]) != direction:
                    in_trade  = True
                    direction = int(sigs[i])
                    entry_px  = closes[i]
                    entry_bar = i

    return trades


def compute_metrics(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0, "pf": 0.0, "roi_pct": 0.0, "wr": 0.0, "mdd_pct": 0.0, "roi_per_day": 0.0}

    pnls = [t["pnl_usd"] for t in trades]
    wins = sum(p for p in pnls if p > 0)
    loss = abs(sum(p for p in pnls if p < 0))
    pf   = wins / loss if loss > 0 else float("inf")
    roi  = sum(pnls) / FIXED_NOTIONAL_USD * 100
    wr   = sum(1 for p in pnls if p > 0) / len(pnls) * 100

    cum  = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    mdd  = float(((cum - peak) / FIXED_NOTIONAL_USD * 100).min())

    bars_span = (trades[-1]["exit_bar"] - trades[0]["entry_bar"]) if len(trades) > 1 else 1
    return {"n": len(trades), "pf": round(pf, 4), "roi_pct": round(roi, 4),
            "wr": round(wr, 2), "mdd_pct": round(mdd, 4)}


def gate1_check(is_m: dict, oos_m: dict) -> tuple[bool, list[str]]:
    fails = []
    if oos_m["pf"] <= OOS_PF_MIN:
        fails.append(f"OOS PF={oos_m['pf']:.4f} <= {OOS_PF_MIN}")
    if oos_m["n"] < OOS_TRADES_MIN:
        fails.append(f"OOS n={oos_m['n']} < {OOS_TRADES_MIN}")
    ratio = is_m["pf"] / oos_m["pf"] if oos_m["pf"] > 0 else float("inf")
    if ratio > IS_OOS_RATIO_MAX:
        fails.append(f"IS/OOS ratio={ratio:.2f}x > {IS_OOS_RATIO_MAX}x")
    if oos_m["mdd_pct"] < OOS_MDD_MAX:
        fails.append(f"OOS MDD={oos_m['mdd_pct']:.2f}% < {OOS_MDD_MAX}%")
    return len(fails) == 0, fails


def run_candidate(strategy, symbol, timeframe, filename) -> dict:
    label = f"{strategy}/{symbol}/{timeframe}"
    print(f"\n{'='*60}")
    print(f"  Candidate: {label}")

    df = load_data(filename)
    if df is None:
        return {"label": label, "status": "NO_DATA"}
    if len(df) < 300:
        print(f"  [SKIP] Too few bars: {len(df)}")
        return {"label": label, "status": "TOO_FEW_BARS"}

    oos_cut = int(len(df) * (1 - OOS_SPLIT))
    df_is   = df.iloc[:oos_cut].copy().reset_index(drop=True)
    df_oos  = df.iloc[oos_cut:].copy().reset_index(drop=True)

    print(f"  Bars:      {len(df)} total  |  IS={len(df_is)}  OOS={len(df_oos)}")
    print(f"  Params:    ST({ST_PERIOD},{ST_MULT}) ADX>{ADX_THRESHOLD}  SL={SL_PCT*100:.1f}%  TP={TP_PCT*100:.1f}%")

    sig_is  = generate_signals(df_is)
    sig_oos = generate_signals(df_oos)

    trades_is  = simulate_trades(df_is,  sig_is)
    trades_oos = simulate_trades(df_oos, sig_oos)

    m_is  = compute_metrics(trades_is)
    m_oos = compute_metrics(trades_oos)

    passed, fails = gate1_check(m_is, m_oos)
    ratio = m_is["pf"] / m_oos["pf"] if m_oos["pf"] > 0 else float("inf")

    print(f"  IS:        PF={m_is['pf']:.4f}  n={m_is['n']}  ROI={m_is['roi_pct']:+.2f}%  WR={m_is['wr']:.1f}%  MDD={m_is['mdd_pct']:.2f}%")
    print(f"  OOS:       PF={m_oos['pf']:.4f}  n={m_oos['n']}  ROI={m_oos['roi_pct']:+.2f}%  WR={m_oos['wr']:.1f}%  MDD={m_oos['mdd_pct']:.2f}%")
    print(f"  IS/OOS:    {ratio:.3f}x")
    print(f"  Gate 1:    {'PASS' if passed else 'FAIL'}")
    for f in fails:
        print(f"             -> {f}")

    result = {
        "label": label, "strategy": strategy, "symbol": symbol, "timeframe": timeframe,
        "st_period": ST_PERIOD, "st_mult": ST_MULT, "adx_threshold": ADX_THRESHOLD,
        "sl_pct": SL_PCT, "tp_pct": TP_PCT,
        "status": "PASS" if passed else "FAIL", "fail_reasons": fails,
        "is_pf": m_is["pf"], "is_n": m_is["n"], "is_roi_pct": m_is["roi_pct"],
        "is_wr": m_is["wr"], "is_mdd_pct": m_is["mdd_pct"],
        "oos_pf": m_oos["pf"], "oos_n": m_oos["n"], "oos_roi_pct": m_oos["roi_pct"],
        "oos_wr": m_oos["wr"], "oos_mdd_pct": m_oos["mdd_pct"],
        "is_oos_ratio": round(ratio, 4),
    }
    return result


def main():
    ts      = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    results = []

    for args in CANDIDATES:
        r = run_candidate(*args)
        results.append(r)

    passes = [r for r in results if r.get("status") == "PASS"]
    fails  = [r for r in results if r.get("status") == "FAIL"]
    skips  = [r for r in results if r.get("status") not in ("PASS", "FAIL")]

    print(f"\n{'='*60}")
    print(f"  SUMMARY: {len(passes)} PASS / {len(fails)} FAIL / {len(skips)} SKIP")
    for r in passes:
        print(f"    PASS  {r['label']}  OOS PF={r['oos_pf']}  n={r['oos_n']}  IS/OOS={r['is_oos_ratio']}x")
    for r in fails:
        print(f"    FAIL  {r['label']}  -> {'; '.join(r.get('fail_reasons', []))}")

    out = RESULTS_DIR / f"gate1_supertrend_adx_{ts}.json"
    with open(out, "w") as f:
        json.dump({"run_ts": ts, "governance": {
            "fixed_notional": FIXED_NOTIONAL_USD, "commission_per_side": COMMISSION_PER_SIDE,
            "oos_split": OOS_SPLIT, "oos_pf_min": OOS_PF_MIN,
            "oos_trades_min": OOS_TRADES_MIN, "is_oos_ratio_max": IS_OOS_RATIO_MAX,
            "oos_mdd_max": OOS_MDD_MAX,
        }, "results": results}, f, indent=2)
    print(f"\n  Results -> {out}")


if __name__ == "__main__":
    main()
