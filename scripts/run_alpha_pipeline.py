#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

ENV_VARS_PATH = "/etc/tradingbot/env_vars"
if os.path.exists(ENV_VARS_PATH):
    load_dotenv(dotenv_path=ENV_VARS_PATH, override=True)

from tradingview_webhook_bot.alerts.telegram_alerts import TelegramAlert
from tradingview_webhook_bot.alpha_engine import (
    AlphaCriteria,
    build_alpha_shortlist,
    build_alpha_reports,
    generate_alpha_pine_scripts,
    notify_alpha_candidates,
    write_pipeline_status,
)


DEFAULT_INPUT_DIR = PROJECT_ROOT / "storage" / "backtest_results"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "storage" / "reports"
DEFAULT_STRATEGIES_DIR = PROJECT_ROOT / "strategies"
DEFAULT_ALPHA_SCRIPTS_DIR = PROJECT_ROOT / "storage" / "generated_alpha_scripts"


def _run_batch_backtest(args: argparse.Namespace) -> None:
    command = [sys.executable, str(PROJECT_ROOT / "scripts" / "batch_backtest.py"), "--output", str(DEFAULT_INPUT_DIR)]
    if args.symbols:
        command.extend(["--symbols", args.symbols])
    if args.timeframe:
        command.extend(["--timeframe", args.timeframe])
    if args.strategies:
        command.extend(["--strategies", args.strategies])

    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the separate alpha backtest pipeline.")
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR), help="Directory containing TradingView-format trade CSVs.")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR), help="Directory where alpha reports are written.")
    parser.add_argument("--strategies-dir", default=str(DEFAULT_STRATEGIES_DIR), help="Directory containing base Pine scripts.")
    parser.add_argument("--alpha-scripts-dir", default=str(DEFAULT_ALPHA_SCRIPTS_DIR), help="Directory where generated alpha Pine scripts are written.")
    parser.add_argument("--initial-capital", type=float, default=10_000.0)
    parser.add_argument("--fees-exchange", default="0.06%")
    parser.add_argument("--data-source", default="tv_backtester_jan_2024")
    parser.add_argument("--min-roi-day", type=float, default=1.0, help="Alpha threshold: ROI per day must be strictly above this percent.")
    parser.add_argument("--max-gross-dd", type=float, default=20.0)
    parser.add_argument("--max-net-dd", type=float, default=20.0)
    parser.add_argument("--shortlist-limit", type=int, default=5, help="Number of shortlisted paper-trade candidates.")
    parser.add_argument("--skip-batch-backtest", action="store_true", help="Only analyze the existing CSVs in --input-dir.")
    parser.add_argument("--skip-script-generation", action="store_true", help="Do not generate webhook-ready Pine copies.")
    parser.add_argument("--notify-telegram", action="store_true", help="Send alpha report and generated scripts to Telegram.")
    parser.add_argument("--symbols", default="", help="Optional comma-separated symbol filter passed to batch_backtest.")
    parser.add_argument("--timeframe", default="", help="Optional timeframe filter passed to batch_backtest.")
    parser.add_argument("--strategies", default="", help="Optional comma-separated strategy filter passed to batch_backtest.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_dir = Path(args.input_dir)
    report_dir = Path(args.report_dir)
    strategies_dir = Path(args.strategies_dir)
    alpha_scripts_dir = Path(args.alpha_scripts_dir)

    if not args.skip_batch_backtest:
        _run_batch_backtest(args)

    criteria = AlphaCriteria(
        min_roi_per_day_pct=args.min_roi_day,
        max_gross_drawdown_pct=args.max_gross_dd,
        max_net_drawdown_pct=args.max_net_dd,
    )
    reports = build_alpha_reports(
        input_folder=input_dir,
        report_dir=report_dir,
        initial_capital=args.initial_capital,
        fees_exchange=args.fees_exchange,
        data_source=args.data_source,
        criteria=criteria,
        summary_csv=input_dir / "SUMMARY.csv",
    )

    alpha_candidates = reports["alpha"]
    if not args.skip_script_generation and not alpha_candidates.empty:
        webhook_secret = os.getenv("WEBHOOK_SECRET", "").strip()
        if webhook_secret:
            alpha_candidates = generate_alpha_pine_scripts(
                alpha_candidates=alpha_candidates,
                strategies_dir=strategies_dir,
                output_dir=alpha_scripts_dir,
                webhook_secret=webhook_secret,
            )
            alpha_candidates.to_csv(report_dir / "alpha_candidates.csv", index=False)
        else:
            alpha_candidates = alpha_candidates.copy()
            alpha_candidates["Webhook_Ready"] = "NO"
            alpha_candidates["Webhook_Reason"] = "WEBHOOK_SECRET not configured"
            alpha_candidates.to_csv(report_dir / "alpha_candidates.csv", index=False)

    best_per_symbol = reports["best"]
    if not alpha_candidates.empty:
        best_per_symbol = (
            alpha_candidates.sort_values(
                by=["ROI_Per_Day_Pct", "Sharpe_Ratio", "Net_Profit_USD"],
                ascending=[False, False, False],
            )
            .groupby("Symbol", as_index=False)
            .first()
        )
        best_per_symbol.to_csv(report_dir / "alpha_best_per_symbol.csv", index=False)
    shortlist = build_alpha_shortlist(alpha_candidates, limit=args.shortlist_limit)
    shortlist.to_csv(report_dir / "alpha_shortlist.csv", index=False)

    status_path = write_pipeline_status(
        report_dir=report_dir,
        all_results=reports["all"],
        alpha_candidates=alpha_candidates,
        best_per_symbol=best_per_symbol,
        shortlist=shortlist,
        input_dir=input_dir,
        scripts_dir=alpha_scripts_dir,
    )

    if args.notify_telegram:
        notify_alpha_candidates(shortlist if not shortlist.empty else alpha_candidates, status_path=status_path, telegram=TelegramAlert(), send_scripts=True)

    print(f"Processed CSV files from: {input_dir}")
    print(f"All backtest results: {report_dir / 'alpha_backtest_results.csv'}")
    print(f"Alpha candidates: {report_dir / 'alpha_candidates.csv'}")
    print(f"Best per symbol: {report_dir / 'alpha_best_per_symbol.csv'}")
    print(f"Shortlist: {report_dir / 'alpha_shortlist.csv'}")
    print(f"Alpha scripts dir: {alpha_scripts_dir}")
    print(f"Qualified alpha strategies: {len(alpha_candidates)}")
    print(f"Shortlisted strategies: {len(shortlist)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
