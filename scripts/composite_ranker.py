#!/usr/bin/env python3
"""
Composite Strategy Ranker
==========================
Combines base tournament metrics + advanced_metrics enrichment into a single
ranked candidate list for daily reporting and (eventually) promotion.

Pipeline:
  1. Read `tournament_winners_enriched.csv` (from advanced_metrics.py)
  2. Apply user's hard-filter floor gate:
        - Daily_ROI_% >= HARD_MIN_ROI
        - |Gross_DD_%| <= HARD_MAX_DD
        - Total_Trades >= HARD_MIN_TRADES
        - Win_Rate_% >= HARD_MIN_WR
  3. Rank survivors by Risk_Adjusted_Score (computed by advanced_metrics)
  4. Output `candidates_ranked.csv` (full ranked list)
  5. Output `candidates_top10.csv` (top 10 only)
  6. Print summary

Bypass mode:
  - If --no-filter is passed, skip the hard filter and just rank everything.
    Useful when current data is still on the buggy (pre-fix) metrics and you
    want to see what the scoring would pick.

Adaptive soft filter:
  - If strict filter yields <5 rows, automatically falls back to a softer
    filter (ROI>=0.3, DD<=25, trades>=50, WR>=40) so the daily report is
    never empty. Soft-filter rows are clearly marked in output.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = PROJECT_ROOT / "storage" / "reports" / "tournament_winners_enriched.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "storage" / "reports"
DEFAULT_TOP_N = 10

# Strict (user-stated) floors
HARD_MIN_ROI = 1.0
HARD_MAX_DD = 12.0
HARD_MIN_TRADES = 100
HARD_MIN_WR = 45.0

# Soft fallback floors (when <5 strict survivors)
SOFT_MIN_ROI = 0.3
SOFT_MAX_DD = 25.0
SOFT_MIN_TRADES = 50
SOFT_MIN_WR = 40.0


def _abs_dd(df: pd.DataFrame) -> pd.Series:
    for col in ("Gross_DD_%", "Max_DD_%"):
        if col in df.columns:
            return df[col].abs()
    return pd.Series([0.0] * len(df), index=df.index)


def apply_filter(df: pd.DataFrame, min_roi, max_dd, min_trades, min_wr) -> pd.DataFrame:
    abs_dd = _abs_dd(df)
    mask = (
        (df.get("Daily_ROI_%", 0) >= min_roi)
        & (abs_dd <= max_dd)
        & (df.get("Total_Trades", 0) >= min_trades)
        & (df.get("Win_Rate_%", 0) >= min_wr)
    )
    return df[mask].copy()


def rank_and_emit(
    input_path: Path,
    output_dir: Path,
    top_n: int,
    bypass_filter: bool,
    quiet: bool,
) -> int:
    if not input_path.exists():
        print(f"ERROR: enriched CSV not found: {input_path}", file=sys.stderr)
        print("       Run scripts/advanced_metrics.py first.", file=sys.stderr)
        return 1

    df = pd.read_csv(input_path)
    if df.empty:
        print(f"ERROR: enriched CSV is empty: {input_path}", file=sys.stderr)
        return 1

    if "Risk_Adjusted_Score" not in df.columns:
        print(
            "ERROR: input CSV is missing Risk_Adjusted_Score column — "
            "run advanced_metrics.py to enrich first.",
            file=sys.stderr,
        )
        return 1

    total_rows = len(df)
    filter_mode = "bypass"
    filtered = df

    if not bypass_filter:
        strict = apply_filter(df, HARD_MIN_ROI, HARD_MAX_DD, HARD_MIN_TRADES, HARD_MIN_WR)
        if len(strict) >= 5:
            filtered = strict
            filter_mode = "strict"
        else:
            soft = apply_filter(df, SOFT_MIN_ROI, SOFT_MAX_DD, SOFT_MIN_TRADES, SOFT_MIN_WR)
            if len(soft) > 0:
                filtered = soft
                filter_mode = "soft"
            else:
                # As a last resort, take top N by score regardless of filter
                filtered = df
                filter_mode = "unfiltered_fallback"

    filtered = filtered.sort_values("Risk_Adjusted_Score", ascending=False)
    filtered["Rank"] = range(1, len(filtered) + 1)
    filtered["Filter_Mode"] = filter_mode

    # Emit outputs
    output_dir.mkdir(parents=True, exist_ok=True)
    ranked_path = output_dir / "candidates_ranked.csv"
    top_path = output_dir / "candidates_top10.csv"

    filtered.to_csv(ranked_path, index=False)
    filtered.head(top_n).to_csv(top_path, index=False)

    if not quiet:
        print(f"Input: {input_path}  ({total_rows} rows)")
        print(f"Filter mode: {filter_mode}")
        print(f"Survivors: {len(filtered)}")
        print(f"Ranked: {ranked_path}")
        print(f"Top {top_n}: {top_path}")
        print()
        if len(filtered):
            cols = [
                "Rank", "Strategy", "Symbol",
                "Daily_ROI_%", "Gross_DD_%", "Win_Rate_%",
                "Risk_Adjusted_Score", "Calmar_Ratio", "WFA_Consistency",
            ]
            cols = [c for c in cols if c in filtered.columns]
            print(f"Top {top_n}:")
            print(filtered[cols].head(top_n).to_string(index=False))

    return 0


def main():
    parser = argparse.ArgumentParser(description="Composite strategy ranker")
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--top", type=int, default=DEFAULT_TOP_N)
    parser.add_argument("--no-filter", action="store_true",
                        help="Skip hard filter, rank everything")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    return rank_and_emit(
        input_path=Path(args.input),
        output_dir=Path(args.output_dir),
        top_n=args.top,
        bypass_filter=args.no_filter,
        quiet=args.quiet,
    )


if __name__ == "__main__":
    raise SystemExit(main())
