#!/usr/bin/env python3
"""
Ensemble Strategy Builder
==========================
Combines pairs and triples of existing v2 strategies into ensemble variants
and backtests each combination. Three aggregation modes:

  - AND       : all strategies must agree (most conservative, fewer trades, higher WR)
  - OR        : any one strategy firing triggers entry (aggressive, more trades)
  - MAJORITY  : >=50% of strategies agree (middle ground)

Why ensembles matter:
  A single RSI strategy may produce noisy signals. An RSI AND MACD ensemble
  only enters when both indicators agree, dramatically cutting false positives
  at the cost of some missed trades. If the increase in WR outweighs the
  reduced trade count, the ensemble Calmar > either individual strategy.

Output: storage/reports/ensemble_winners.csv in tournament CSV format, so
advanced_metrics.py and composite_ranker.py consume it transparently.
"""
from __future__ import annotations

import argparse
import sys
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from strategy_library_v2 import STRATEGY_REGISTRY, DEFAULT_PARAM_GRIDS  # noqa: E402
from strategy_explorer import backtest_signal, load_ohlcv  # noqa: E402

DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT"]
DEFAULT_OUTPUT = PROJECT_ROOT / "storage" / "reports" / "ensemble_winners.csv"
BARS_PER_DAY_15M = 96
BARS_PER_DAY_4H = 6

# Ensembles are expensive (combinatorial); cap the breadth
MAX_PAIRS = 50
MAX_TRIPLES = 30
MIN_ROI_FILTER = 0.0


def select_base_strategies(top_k_per_strategy: int = 1) -> list[tuple]:
    """Pick the default parameter combo for each registered strategy.

    Returns list of (label, func, params) tuples.
    """
    result = []
    for name, func in STRATEGY_REGISTRY.items():
        grids = DEFAULT_PARAM_GRIDS.get(name, [{}])[:top_k_per_strategy]
        for params in grids:
            label = name
            result.append((label, func, params))
    return result


def combine_and(signals: list[np.ndarray]) -> np.ndarray:
    """All agree — returns 1 if all say 1, -1 if all say -1, 0 otherwise."""
    stacked = np.stack(signals)
    all_long = (stacked == 1).all(axis=0)
    all_short = (stacked == -1).all(axis=0)
    out = np.zeros(stacked.shape[1], dtype=int)
    out[all_long] = 1
    out[all_short] = -1
    return out


def combine_or(signals: list[np.ndarray]) -> np.ndarray:
    """Any agree — first non-zero wins, ties go to positive sum."""
    stacked = np.stack(signals)
    longs = (stacked == 1).sum(axis=0)
    shorts = (stacked == -1).sum(axis=0)
    out = np.zeros(stacked.shape[1], dtype=int)
    out[longs > shorts] = 1
    out[shorts > longs] = -1
    return out


def combine_majority(signals: list[np.ndarray]) -> np.ndarray:
    """Majority vote — strictly more than half must agree."""
    stacked = np.stack(signals)
    longs = (stacked == 1).sum(axis=0)
    shorts = (stacked == -1).sum(axis=0)
    n = stacked.shape[0]
    threshold = n / 2
    out = np.zeros(stacked.shape[1], dtype=int)
    out[longs > threshold] = 1
    out[shorts > threshold] = -1
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--timeframe", default="4h",
                        help="OHLCV timeframe (15m or 4h)")
    parser.add_argument("--min-roi", type=float, default=MIN_ROI_FILTER)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--triples", action="store_true",
                        help="Include triple-strategy ensembles (slower)")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    bars_per_day = BARS_PER_DAY_4H if args.timeframe == "4h" else BARS_PER_DAY_15M

    base_strategies = select_base_strategies(top_k_per_strategy=1)
    if not args.quiet:
        print(f"Base strategies: {len(base_strategies)}")
        print(f"Symbols: {symbols}")

    all_rows = []

    for symbol in symbols:
        df = load_ohlcv(symbol, args.timeframe)
        if df is None:
            if not args.quiet:
                print(f"SKIP {symbol}: no data file")
            continue

        # Precompute all base signals once per symbol
        base_signals = {}
        for label, func, params in base_strategies:
            try:
                sig = np.asarray(func(df, **params))
                if sig is not None and len(sig) == len(df):
                    base_signals[label] = sig
            except Exception as exc:
                if not args.quiet:
                    print(f"  base sig error {label}: {exc}")

        if len(base_signals) < 2:
            continue

        names = list(base_signals.keys())

        # --- Pair ensembles ---
        pair_count = 0
        for a, b in combinations(names, 2):
            if pair_count >= MAX_PAIRS:
                break
            for mode, combiner in (
                ("AND", combine_and),
                ("OR", combine_or),
                ("MAJORITY", combine_majority),
            ):
                try:
                    combined = combiner([base_signals[a], base_signals[b]])
                    metrics = backtest_signal(df, combined, bars_per_day)
                    if metrics["Daily_ROI_%"] < args.min_roi:
                        continue
                    label = f"ENSEMBLE[{mode}]:{a}+{b}"
                    all_rows.append({
                        "Symbol": symbol,
                        "Strategy": label,
                        **metrics,
                    })
                except Exception:
                    pass
            pair_count += 1

        # --- Triple ensembles (optional, more expensive) ---
        if args.triples:
            triple_count = 0
            for a, b, c in combinations(names, 3):
                if triple_count >= MAX_TRIPLES:
                    break
                for mode, combiner in (
                    ("AND", combine_and),
                    ("MAJORITY", combine_majority),
                ):
                    try:
                        combined = combiner([
                            base_signals[a], base_signals[b], base_signals[c]
                        ])
                        metrics = backtest_signal(df, combined, bars_per_day)
                        if metrics["Daily_ROI_%"] < args.min_roi:
                            continue
                        label = f"ENSEMBLE3[{mode}]:{a}+{b}+{c}"
                        all_rows.append({
                            "Symbol": symbol,
                            "Strategy": label,
                            **metrics,
                        })
                    except Exception:
                        pass
                triple_count += 1

        if not args.quiet:
            print(f"  {symbol}: {len(base_signals)} base × combinations done")

    if not all_rows:
        print("WARNING: no ensembles met min-roi filter")
        pd.DataFrame().to_csv(args.output, index=False)
        return 0

    out = pd.DataFrame(all_rows)
    out["Tier"] = "V2_ENSEMBLE"
    out = out.sort_values("Daily_ROI_%", ascending=False)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)

    if not args.quiet:
        print()
        print(f"Ensembles discovered: {len(out)}")
        print(f"Written: {out_path}")
        print()
        print("Top 10 by Daily_ROI_%:")
        cols = ["Symbol", "Strategy", "Daily_ROI_%", "Gross_DD_%",
                "Win_Rate_%", "Total_Trades", "Sharpe_Ratio"]
        print(out[cols].head(10).to_string(index=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
