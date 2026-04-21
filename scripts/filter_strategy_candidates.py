#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


DEFAULT_CANDIDATES = [
    Path("storage/reports/tournament_winners.csv"),
    Path("tournament_winners.csv"),
]


def _first_existing(paths: list[Path]) -> Path:
    for path in paths:
        if path.exists():
            return path
    return paths[0]


def _num(series):
    return pd.to_numeric(series, errors="coerce")


def _tier_clean(value: object) -> str:
    text = str(value or "")
    return text.encode("ascii", "ignore").decode("ascii").strip() or text


def _show(title: str, rows: pd.DataFrame, cols: list[str], limit: int) -> None:
    print()
    print(title)
    if rows.empty:
        print("NONE")
        return
    view = rows[cols].head(limit).copy()
    if "Tier" in view.columns:
        view["Tier"] = view["Tier"].map(_tier_clean)
    print(view.to_string(index=False))


def main() -> int:
    parser = argparse.ArgumentParser(description="Filter strategy leaderboard by ROI and drawdown.")
    parser.add_argument("--csv", default="", help="Leaderboard CSV path. Defaults to storage/reports/tournament_winners.csv, then tournament_winners.csv.")
    parser.add_argument("--min-roi", type=float, default=2.0, help="Minimum Daily_ROI_% threshold.")
    parser.add_argument("--max-dd", type=float, default=15.0, help="Maximum absolute drawdown percent. Example: 15 means Gross_DD_% and Net_DD_% must be >= -15.")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--symbols", default="", help="Optional comma-separated symbols, e.g. BTCUSDT,ETHUSDT,SOLUSDT.")
    parser.add_argument("--write", default="", help="Optional output CSV for strict matches.")
    args = parser.parse_args()

    path = Path(args.csv) if args.csv else _first_existing(DEFAULT_CANDIDATES)
    if not path.exists():
        print(f"Leaderboard not found: {path}")
        print("Generate it first with: ./venv/bin/python scripts/strategy_tournament.py")
        return 2

    df = pd.read_csv(path)
    daily_col = "Daily_ROI_%"
    gross_col = "Gross_DD_%"
    net_col = "Net_DD_%"
    oos_roi_col = "OOS_ROI_%" if "OOS_ROI_%" in df.columns else "OOS_Daily_ROI_%"
    oos_dd_col = "OOS_DD_%" if "OOS_DD_%" in df.columns else "OOS_Gross_DD_%"
    trades_col = "Trade_Count" if "Trade_Count" in df.columns else "Total_Trades"

    required = [daily_col, gross_col, net_col]
    missing = [col for col in required if col not in df.columns]
    if missing:
        print(f"Missing required columns in {path}: {', '.join(missing)}")
        return 2

    for col in [daily_col, gross_col, net_col, oos_roi_col, oos_dd_col, "Sharpe_Ratio", "Win_Rate_%"]:
        if col in df.columns:
            df[col] = _num(df[col])

    symbols = [symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()]
    if symbols and "Symbol" in df.columns:
        df = df[df["Symbol"].astype(str).str.upper().isin(symbols)].copy()

    strict = df[
        (df[daily_col] >= args.min_roi)
        & (df[gross_col] >= -args.max_dd)
        & (df[net_col] >= -args.max_dd)
    ].copy()
    strict = strict.sort_values([daily_col, "Sharpe_Ratio"], ascending=[False, False])

    cols = [
        "Symbol", "Strategy", daily_col, gross_col, net_col,
        "Win_Rate_%", "Sharpe_Ratio", trades_col, oos_roi_col, oos_dd_col, "Tier",
    ]
    cols = [col for col in cols if col in df.columns]

    print(f"source={path}")
    print(f"rows_scanned={len(df)}")
    print(f"strict_matches={len(strict)} | rule: {daily_col}>={args.min_roi} and abs DD<={args.max_dd}%")
    _show("TOP STRICT MATCHES", strict, cols, args.top)

    if args.write:
        out = Path(args.write)
        out.parent.mkdir(parents=True, exist_ok=True)
        strict.to_csv(out, index=False)
        print(f"\nstrict_csv={out}")

    if strict.empty:
        dd_ok = df[(df[gross_col] >= -args.max_dd) & (df[net_col] >= -args.max_dd)].copy()
        dd_ok = dd_ok.sort_values([daily_col, "Sharpe_Ratio"], ascending=[False, False])
        _show(f"BEST WITH DD <= {args.max_dd}% BUT ROI BELOW TARGET", dd_ok, cols, args.top)

        roi_ok = df[df[daily_col] >= args.min_roi].copy()
        if not roi_ok.empty:
            roi_ok["Worst_DD_%"] = roi_ok[[gross_col, net_col]].min(axis=1)
            roi_ok = roi_ok.sort_values(["Worst_DD_%", daily_col], ascending=[False, False])
        _show(f"BEST WITH ROI >= {args.min_roi}% BUT DD ABOVE TARGET", roi_ok, cols, args.top)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
