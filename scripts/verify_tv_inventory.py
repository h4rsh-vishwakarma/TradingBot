#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text).lower())


def _load_manifest(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("approvals", []) if isinstance(data, dict) else []


def _inspect_pine(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return {"has_buy": "NO", "has_sell": "NO", "has_secret": "NO"}
    return {
        "has_buy": "YES" if "Webhook BUY" in text else "NO",
        "has_sell": "YES" if "Webhook SELL" in text else "NO",
        "has_secret": "YES" if '"secret"' in text else "NO",
    }


def _find_matching_scripts(search_dirs: list[Path], strategy: str, symbol: str, timeframe: str) -> list[Path]:
    strategy_key = _normalize(strategy)
    symbol_key = _normalize(symbol)
    timeframe_key = _normalize(timeframe) if timeframe else ""
    matches: list[tuple[int, Path]] = []

    for base in search_dirs:
        if not base.exists():
            continue
        for path in base.glob("*.pine"):
            name_key = _normalize(path.stem)
            score = 0
            if strategy_key and strategy_key in name_key:
                score += 10
            if symbol_key and symbol_key in name_key:
                score += 5
            if timeframe_key and timeframe_key in name_key:
                score += 3
            if score > 0:
                matches.append((score, path))

    matches.sort(key=lambda item: (-item[0], len(item[1].name)))
    return [path for _, path in matches]


def build_inventory_report(manifest_path: Path, strategies_dir: Path, generated_dir: Path) -> pd.DataFrame:
    approvals = _load_manifest(manifest_path)
    rows = []
    search_dirs = [generated_dir, strategies_dir]

    for approval in approvals:
        strategy = str(approval.get("strategy", ""))
        exchange = str(approval.get("exchange", ""))
        symbols = approval.get("symbols", ["*"])
        timeframes = approval.get("timeframes", ["*"])

        for symbol in symbols:
            for timeframe in timeframes:
                symbol_text = "" if symbol == "*" else str(symbol)
                timeframe_text = "" if timeframe == "*" else str(timeframe)
                candidates = _find_matching_scripts(search_dirs, strategy, symbol_text, timeframe_text)
                best = candidates[0] if candidates else None
                inspection = _inspect_pine(best) if best else {"has_buy": "NO", "has_sell": "NO", "has_secret": "NO"}
                status = "READY" if best and inspection["has_buy"] == "YES" and inspection["has_sell"] == "YES" else "MISSING"
                rows.append(
                    {
                        "Strategy": strategy,
                        "Exchange": exchange,
                        "Symbol": symbol,
                        "Timeframe": timeframe,
                        "Matched Script": str(best) if best else "",
                        "Webhook BUY": inspection["has_buy"],
                        "Webhook SELL": inspection["has_sell"],
                        "Embedded Secret": inspection["has_secret"],
                        "Status": status,
                    }
                )

    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify approved strategies against Pine deployment artifacts.")
    parser.add_argument("--manifest", default="config/approved_strategies.json")
    parser.add_argument("--strategies-dir", default="strategies")
    parser.add_argument("--generated-dir", default="storage/generated_alpha_scripts")
    parser.add_argument("--output", default="storage/reports/tv_inventory_report.csv")
    args = parser.parse_args()

    report = build_inventory_report(
        manifest_path=Path(args.manifest),
        strategies_dir=Path(args.strategies_dir),
        generated_dir=Path(args.generated_dir),
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(output_path, index=False)
    print(f"Inventory report written: {output_path}")
    if report.empty:
        print("No approvals found.")
        return 0
    ready = int((report["Status"] == "READY").sum())
    print(f"Approved rows: {len(report)} | Ready: {ready} | Missing: {len(report) - ready}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
