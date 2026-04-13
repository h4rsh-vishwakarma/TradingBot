#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
import sqlite3
from datetime import datetime, timedelta

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


def _check_signal_queue(db_path: Path, strategy: str, symbol: str, lookback_days: int = 7) -> dict:
    """Check if real signals from this strategy+symbol exist in the signal queue."""
    if not db_path.exists():
        return {"signal_count": 0, "last_signal": None, "live_verified": False}

    try:
        cutoff = (datetime.utcnow() - timedelta(days=lookback_days)).timestamp()
        with sqlite3.connect(str(db_path)) as conn:
            # Search in payload JSON for strategy name
            cursor = conn.execute(
                "SELECT COUNT(*), MAX(created_at) FROM signals WHERE created_at >= ? AND payload LIKE ?",
                (cutoff, f'%{strategy}%',),
            )
            count, last_ts = cursor.fetchone()

            # If strategy matched, also verify symbol
            if count and count > 0 and symbol and symbol != "*":
                cursor2 = conn.execute(
                    "SELECT COUNT(*), MAX(created_at) FROM signals WHERE created_at >= ? AND payload LIKE ? AND payload LIKE ?",
                    (cutoff, f'%{strategy}%', f'%{symbol}%'),
                )
                count, last_ts = cursor2.fetchone()

        if count and count > 0:
            last_signal = datetime.utcfromtimestamp(last_ts).strftime("%Y-%m-%d %H:%M UTC") if last_ts else "unknown"
            return {"signal_count": int(count), "last_signal": last_signal, "live_verified": True}
    except Exception:
        pass

    return {"signal_count": 0, "last_signal": None, "live_verified": False}


def build_inventory_report(manifest_path: Path, strategies_dir: Path, generated_dir: Path, signal_db_path: Path = None) -> pd.DataFrame:
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
                # Check local Pine file
                pine_ready = best and inspection["has_buy"] == "YES" and inspection["has_sell"] == "YES"

                # Check signal queue for live evidence (strategies configured directly in TradingView)
                signal_info = {"signal_count": 0, "last_signal": None, "live_verified": False}
                if signal_db_path:
                    signal_info = _check_signal_queue(signal_db_path, strategy, symbol_text)

                # READY if: local Pine file OK, OR live signals received from TradingView
                if pine_ready:
                    status = "READY"
                    source = f"Pine: {best.name}" if best else ""
                elif signal_info["live_verified"]:
                    status = "LIVE_VERIFIED"
                    source = f"{signal_info['signal_count']} signals (last: {signal_info['last_signal']})"
                else:
                    status = "MISSING"
                    source = ""

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
                        "Live Signals": signal_info["signal_count"],
                        "Last Signal": signal_info["last_signal"] or "",
                        "Source": source,
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

    # Signal queue DB for live verification
    signal_db = Path("tradingview_webhook_bot/storage/signal_queue.db")

    report = build_inventory_report(
        manifest_path=Path(args.manifest),
        strategies_dir=Path(args.strategies_dir),
        generated_dir=Path(args.generated_dir),
        signal_db_path=signal_db,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(output_path, index=False)
    print(f"Inventory report written: {output_path}")
    if report.empty:
        print("No approvals found.")
        return 0
    ready = int(((report["Status"] == "READY") | (report["Status"] == "LIVE_VERIFIED")).sum())
    print(f"Approved rows: {len(report)} | Ready: {ready} | Missing: {len(report) - ready}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
