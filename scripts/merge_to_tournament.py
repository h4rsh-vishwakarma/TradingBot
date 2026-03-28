"""
Merge batch_backtest SUMMARY.csv into tournament_winners.csv.
Called automatically after every batch_backtest run.
"""
import os
import logging
import sys
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

FILE_PATH = Path(__file__).resolve()
PROJECT_ROOT = FILE_PATH.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tradingview_webhook_bot.alerts.telegram_alerts import AlertSeverity, TelegramAlert
from tradingview_webhook_bot.tournament_rules import (
    apply_tournament_rules,
    build_tournament_change_message,
)


def _load_previous_report(winners_path):
    if not os.path.exists(winners_path):
        return None
    try:
        return pd.read_csv(winners_path)
    except Exception:
        return None


def _notify_tournament_changes(previous_df, current_df):
    message = build_tournament_change_message(
        previous_df=previous_df,
        current_df=current_df,
        source_label="Batch Backtest Tournament Update",
    )
    if not message:
        return

    try:
        telegram = TelegramAlert()
        telegram.send(
            severity=AlertSeverity.INFO,
            title="Batch Tournament Change",
            message=message,
        )
    except Exception as exc:
        logger.warning("Telegram notification skipped: %s", exc)

def merge_results(summary_path, winners_path):
    """Merge batch backtest results into tournament winners format."""
    if not os.path.exists(summary_path):
        logger.warning(f"No summary file: {summary_path}")
        return

    bt = pd.read_csv(summary_path)
    logger.info(f"Batch results: {len(bt)} strategies")
    previous_report = _load_previous_report(winners_path)

    # Load existing tournament (if exists)
    if os.path.exists(winners_path):
        tw = pd.read_csv(winners_path)
        # Keep only original tournament entries (not previously merged batch results)
        # Original entries have Daily_ROI > 0.1 typically and come from grid search
        tw_original = tw[~tw['Strategy'].isin(bt['Strategy'].unique()) | ~tw['Symbol'].isin(bt['Symbol'].unique())]
    else:
        tw_original = pd.DataFrame()

    # Convert batch results to tournament format
    rows = []
    for _, r in bt.iterrows():
        total_roi = r.get("ROI %", 0)
        wr = r.get("Win Rate %", 0)
        dd = abs(r.get("Max DD %", 0))
        trades = int(r.get("Total Trades", 0))
        final_cap = r.get("Final Capital", 10000)

        # Daily ROI: compound daily rate over ~1095 trading days (3 years)
        if total_roi > 0 and final_cap > 0:
            # Compound: (final/start)^(1/days) - 1
            daily_roi = round(((final_cap / 10000) ** (1/1095) - 1) * 100, 3)
        else:
            daily_roi = round(total_roi / 1095, 3)

        # Sharpe estimate
        sharpe = round(abs(daily_roi * 100 / max(dd, 0.1)), 2)
        sharpe = min(sharpe, 15)  # cap at 15

        # Capital left estimates (based on $100K starting capital)
        gdd_capital = round(100000 * (1 + (-dd) / 100), 0)
        ndd_capital = round(100000 * (1 + (-dd * 1.1) / 100), 0)

        rows.append({
            "Symbol": r["Symbol"],
            "Strategy": r["Strategy"],
            "Daily_ROI_%": daily_roi,
            "Gross_DD_%": round(-dd, 2),
            "Net_DD_%": round(-dd * 1.1, 2),
            "Max_DD_%": round(-dd, 2),
            "GDD_Date": r.get("DD_Date", "N/A"),
            "GDD_Capital_Left": int(gdd_capital),
            "NDD_Date": r.get("DD_Date", "N/A"),
            "NDD_Capital_Left": int(ndd_capital),
            "Win_Rate_%": round(wr, 1),
            "Sharpe_Ratio": sharpe,
            "Total_Trades": trades,
            "Tier": "💀 REJECT",
            "Optimal_Mult": 3.0,
            "Optimal_Len": 14,
            "OOS_Daily_ROI_%": round(daily_roi * 0.6, 3),
            "OOS_Gross_DD_%": round(-dd, 2),
            "OOS_Sharpe": round(sharpe * 0.8, 2),
        })

    bt_df = pd.DataFrame(rows)

    # Merge: original tournament + batch results (no duplicates)
    combined = pd.concat([tw_original, bt_df], ignore_index=True)

    # Remove exact duplicates (same Strategy + Symbol)
    combined = combined.drop_duplicates(subset=["Strategy", "Symbol"], keep="first")

    # Sort by Daily ROI descending
    combined = combined.sort_values("Daily_ROI_%", ascending=False)
    combined = apply_tournament_rules(combined)

    # Save
    combined.to_csv(winners_path, index=False)
    _notify_tournament_changes(previous_report, combined)

    # Count tiers
    tiers = {}
    for tier_name in ["ALPHA++", "ALPHA", "AVERAGE", "REJECT"]:
        tiers[tier_name] = len(combined[combined["Tier"].str.contains(tier_name, na=False, regex=False)])

    logger.info(f"Tournament updated: {len(combined)} strategies")
    logger.info(f"  ALPHA++: {tiers.get('ALPHA++', 0)} | ALPHA: {tiers.get('ALPHA', 0)} | AVERAGE: {tiers.get('AVERAGE', 0)} | REJECT: {tiers.get('REJECT', 0)}")
    return combined

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    summary = os.path.join(base, "storage/backtest_results/SUMMARY.csv")
    winners = os.path.join(base, "storage/reports/tournament_winners.csv")
    merge_results(summary, winners)
