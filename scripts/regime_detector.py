#!/usr/bin/env python3
"""
Market Regime Detector
=======================
Classifies each OHLCV candle into one of 4 market regimes:

    BULL       : 30-bar close > 90-bar close AND MA slope positive
    BEAR       : 30-bar close < 90-bar close AND MA slope negative
    RANGING    : ADX < 20 (trendless)
    HIGH_VOL   : ATR% > 2x rolling median (volatility spike)

A strategy that is profitable in >=3 of 4 regimes is considered robust.
A strategy that only wins in BULL is a bull-market artifact.

Usage (standalone):
    python scripts/regime_detector.py --input storage/data/BTCUSDT_4h.csv \
        --output storage/reports/regime/BTCUSDT_4h_regimes.csv

Usage (as library):
    from regime_detector import classify_regimes
    df_with_regimes = classify_regimes(df)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd


REGIMES = ("BULL", "BEAR", "RANGING", "HIGH_VOL")


def _sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=1).mean()


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=1).mean()


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=1).mean()


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Classic Wilder ADX."""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm[plus_dm < 0] = 0.0
    minus_dm[minus_dm < 0] = 0.0
    # Suppress the lesser of the two when both are positive
    mask = plus_dm > minus_dm
    minus_dm[mask] = 0.0
    plus_dm[~mask] = 0.0

    tr = pd.concat(
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan)) * 100
    adx = dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    return adx.fillna(0)


def classify_regimes(
    df: pd.DataFrame,
    fast_ma: int = 30,
    slow_ma: int = 90,
    adx_thresh: float = 20.0,
    vol_multiplier: float = 2.0,
    vol_lookback: int = 100,
) -> pd.DataFrame:
    """Add a `regime` column to `df` classifying each row into one of REGIMES.

    Requires columns: open, high, low, close (volume optional).
    Preserves index.
    """
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"regime_detector: missing required columns: {sorted(missing)}")

    df["_ma_fast"] = _sma(df["close"], fast_ma)
    df["_ma_slow"] = _sma(df["close"], slow_ma)
    df["_ma_slope"] = df["_ma_fast"].diff(5)  # 5-bar slope
    df["_adx"] = _adx(df, 14)
    df["_atr"] = _atr(df, 14)
    df["_atr_pct"] = df["_atr"] / df["close"] * 100
    df["_atr_median"] = df["_atr_pct"].rolling(vol_lookback, min_periods=10).median()

    is_high_vol = df["_atr_pct"] > (vol_multiplier * df["_atr_median"])
    is_ranging = df["_adx"] < adx_thresh
    is_bull = (df["_ma_fast"] > df["_ma_slow"]) & (df["_ma_slope"] > 0)
    is_bear = (df["_ma_fast"] < df["_ma_slow"]) & (df["_ma_slope"] < 0)

    # Priority: HIGH_VOL > RANGING > BULL > BEAR > RANGING (fallback)
    regime = pd.Series(["RANGING"] * len(df), index=df.index, dtype=object)
    regime[is_bear] = "BEAR"
    regime[is_bull] = "BULL"
    regime[is_ranging] = "RANGING"
    regime[is_high_vol] = "HIGH_VOL"

    df["regime"] = regime
    return df


def regime_summary(df_with_regimes: pd.DataFrame) -> dict:
    """Return a distribution dict of regime -> % of bars."""
    if "regime" not in df_with_regimes.columns:
        raise ValueError("classify_regimes() must be called first")
    counts = df_with_regimes["regime"].value_counts(normalize=True) * 100
    return {regime: round(counts.get(regime, 0.0), 2) for regime in REGIMES}


def main():
    parser = argparse.ArgumentParser(description="Classify market regimes from OHLCV")
    parser.add_argument("--input", required=True, help="OHLCV CSV path")
    parser.add_argument("--output", help="Enriched CSV path (default: <input>_regimes.csv)")
    parser.add_argument("--summary-only", action="store_true",
                        help="Print regime distribution summary only")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: input not found: {input_path}", file=sys.stderr)
        return 1

    df = pd.read_csv(input_path)
    if df.empty:
        print(f"ERROR: empty CSV: {input_path}", file=sys.stderr)
        return 1

    df_r = classify_regimes(df)
    summary = regime_summary(df_r)

    print(f"Input: {input_path}")
    print(f"  rows: {len(df_r)}")
    print(f"  regime distribution:")
    for regime, pct in summary.items():
        bar = "#" * int(pct / 2)
        print(f"    {regime:<10}  {pct:>5.1f}%  {bar}")

    if args.summary_only:
        return 0

    out_path = Path(args.output) if args.output else input_path.with_suffix(".regimes.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df_r.to_csv(out_path, index=False)
    print(f"Written: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
