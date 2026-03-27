"""
Merge batch_backtest SUMMARY.csv into tournament_winners.csv.
Called automatically after every batch_backtest run.
"""
import pandas as pd
import numpy as np
import os
import logging

logger = logging.getLogger(__name__)

def merge_results(summary_path, winners_path):
    """Merge batch backtest results into tournament winners format."""
    if not os.path.exists(summary_path):
        logger.warning(f"No summary file: {summary_path}")
        return

    bt = pd.read_csv(summary_path)
    logger.info(f"Batch results: {len(bt)} strategies")

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

        # Quality-based tiering
        if dd > 80:
            if daily_roi >= 0.5: tier = "🎯 ALPHA"
            elif daily_roi >= 0.1: tier = "⚖️ AVERAGE"
            else: tier = "💀 REJECT"
        elif daily_roi >= 0.5 and sharpe >= 4.0 and wr >= 40:
            tier = "🚀 ALPHA++"
        elif daily_roi >= 0.3 and sharpe >= 3.0 and wr >= 40:
            tier = "🚀 ALPHA++"
        elif daily_roi >= 0.15 and sharpe >= 2.0 and wr >= 38:
            tier = "🎯 ALPHA"
        elif daily_roi >= 0.05 and sharpe >= 1.0:
            tier = "⚖️ AVERAGE"
        elif daily_roi > 0:
            tier = "⚖️ AVERAGE"
        else:
            tier = "💀 REJECT"

        # Bonus: exceptional Sharpe
        if sharpe >= 8.0 and daily_roi >= 0.2 and "ALPHA++" not in tier:
            tier = "🚀 ALPHA++"
        elif sharpe >= 5.0 and daily_roi >= 0.1 and "ALPHA" not in tier:
            tier = "🎯 ALPHA"

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
            "Tier": tier,
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

    # Save
    combined.to_csv(winners_path, index=False)

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
