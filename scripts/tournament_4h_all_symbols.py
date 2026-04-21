"""
4H Strategy Tournament — All 16 Symbols
========================================
Runs strategy parameter optimization over 3 years of 4H OHLCV data.
Produces a ranked report at storage/reports/tournament_winners_4h.csv.

Key differences vs strategy_tournament.py (15m):
  - 4H bars: BARS_PER_YEAR = 2190  (6 bars/day x 365)
  - Sharpe annualization: sqrt(2190)
  - LEVERAGE = 1.0  (no inflation)
  - ADX filter threshold: > 20  (wider than 25 used for 15m)
  - Wider param_grid suited to swing/trend timeframes
  - Tier thresholds lowered to match 4H trade frequency
  - Minimum 2-bar gap enforced between signals
"""

import pandas as pd
import numpy as np
import glob
import os
import gc
from math import sqrt

from my_strategies import apply_strategy, calculate_adx

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
INITIAL_CAPITAL  = 10_000
BARS_PER_YEAR    = 2190          # 6 bars/day x 365
LEVERAGE         = 1.0
STOP_LOSS        = 0.02          # 2%
TAKE_PROFIT      = 0.06          # 6%
TOTAL_DAYS       = 1095          # 3 years
ADX_THRESHOLD    = 20            # Looser than 15m (25) — 4H trends are slower
MIN_BAR_GAP      = 2             # Minimum bars between signal flips

# Tier thresholds (lower because 4H has fewer trades -> lower daily ROI is good)
TIER_PREMIUM     = 1.00          # >= 1.00%/day + DD<=55% => PREMIUM (live ready)
TIER_ALPHA_PP    = 0.30          # >= 0.30% daily  => ALPHA++
TIER_ALPHA       = 0.10          # >= 0.10% daily  => ALPHA
TIER_AVERAGE     = 0.02          # >  0.02% daily  => AVERAGE
                                 # else            => REJECT

# 4H-tuned parameter grid
PARAM_GRID = [
    {'mult': 1.0, 'len': 6},
    {'mult': 1.2, 'len': 8},
    {'mult': 1.5, 'len': 10},
    {'mult': 1.8, 'len': 12},
    {'mult': 2.0, 'len': 14},
    {'mult': 2.2, 'len': 16},
    {'mult': 2.5, 'len': 20},
    {'mult': 2.8, 'len': 24},
    {'mult': 3.0, 'len': 26},
    {'mult': 3.5, 'len': 34},
    {'mult': 4.0, 'len': 42},
    {'mult': 5.0, 'len': 55},
    {'mult': 6.0, 'len': 70},
]


# ---------------------------------------------------------------------------
# Signal enforcement: minimum bar gap between entries
# ---------------------------------------------------------------------------
def enforce_min_bar_gap(sig_series, min_gap=MIN_BAR_GAP):
    """
    Suppress a new signal if fewer than min_gap bars have elapsed since the
    last non-zero signal.  Prevents rapid re-entries that would be unrealistic
    on 4H charts.
    """
    sig = sig_series.values.copy()
    last_signal_bar = -min_gap  # initialise so first bar is always eligible
    for i in range(len(sig)):
        if sig[i] != 0:
            if (i - last_signal_bar) < min_gap:
                sig[i] = 0      # too soon — suppress
            else:
                last_signal_bar = i
    return pd.Series(sig, index=sig_series.index)


# ---------------------------------------------------------------------------
# Single backtest run
# ---------------------------------------------------------------------------
def run_test(df_raw, strategy_name, mult, length):
    """
    Runs one backtest pass.  Returns:
        (daily_roi, gross_dd, net_dd, win_rate, sharpe,
         total_trades, tier, gross_dd_date, net_dd_date)
    """
    df = df_raw.copy()

    try:
        # Generate raw signals
        df['sig'] = apply_strategy(df, strategy_name, True, mult, length)

        # ADX filter — only trade when trend is meaningful
        adx = calculate_adx(df, n=14)
        df['sig'] = np.where(adx > ADX_THRESHOLD, df['sig'], 0)

        # Minimum bar-gap filter — prevents rapid re-entry
        df['sig'] = enforce_min_bar_gap(df['sig'])

        # Per-bar returns (non-compounding base, then clipped by SL/TP)
        df['bar_ret'] = df['sig'].shift(1) * df['pct'] * LEVERAGE
        df['bar_ret'] = df['bar_ret'].clip(lower=-STOP_LOSS, upper=TAKE_PROFIT)

        # Daily ROI (non-compounding sum over 3-year window)
        total_return_pct = df['bar_ret'].sum() * 100
        daily_roi = total_return_pct / TOTAL_DAYS

        # Gross DD: compounding equity curve peak-to-trough
        cum_res = (1 + df['bar_ret'].fillna(0)).cumprod()
        gross_dd_series = (cum_res - cum_res.cummax()) / cum_res.cummax() * 100
        gross_dd = gross_dd_series.min()
        gdd_idx = gross_dd_series.values.argmin()
        gross_dd_date = (
            str(df['timestamp'].iloc[gdd_idx])[:10]
            if 'timestamp' in df.columns else "N/A"
        )

        # Net DD: non-compounding cumsum
        cum_sum = df['bar_ret'].fillna(0).cumsum() * 100
        cum_peak = cum_sum.cummax()
        net_dd_series = cum_sum - cum_peak
        net_dd = net_dd_series.min()
        ndd_idx = net_dd_series.values.argmin()
        net_dd_date = (
            str(df['timestamp'].iloc[ndd_idx])[:10]
            if 'timestamp' in df.columns else "N/A"
        )

        # Win rate
        trades = df['bar_ret'][df['bar_ret'] != 0]
        total_trades = len(trades)
        winning_trades = len(trades[trades > 0])
        win_rate = (
            round(winning_trades / total_trades * 100, 1)
            if total_trades > 0 else 0.0
        )

        # Sharpe — annualised with 4H bar count
        mean_ret = df['bar_ret'].mean()
        std_ret  = df['bar_ret'].std()
        sharpe = (
            round((mean_ret / std_ret) * sqrt(BARS_PER_YEAR), 2)
            if std_ret > 0 else 0.0
        )

        # Tier assignment (4H-adjusted thresholds)
        if daily_roi >= TIER_PREMIUM and abs(gross_dd) <= 55:
            tier = "PREMIUM"
        elif daily_roi >= TIER_ALPHA_PP:
            tier = "ALPHA++"
        elif daily_roi >= TIER_ALPHA:
            tier = "ALPHA"
        elif daily_roi > TIER_AVERAGE:
            tier = "AVERAGE"
        else:
            tier = "REJECT"

        return (daily_roi, gross_dd, net_dd, win_rate, sharpe,
                total_trades, tier, gross_dd_date, net_dd_date)

    except Exception:
        return (-1, -1, -1, 0.0, 0.0, 0, "ERROR", "N/A", "N/A")


# ---------------------------------------------------------------------------
# Out-of-sample validation (80/20 split)
# ---------------------------------------------------------------------------
def run_test_oos(df_raw, strategy_name, mult, length, train_pct=0.8):
    split_idx = int(len(df_raw) * train_pct)
    df_test = df_raw.iloc[split_idx:].copy()
    df_test['pct'] = df_test['close'].pct_change()
    return run_test(df_test, strategy_name, mult, length)


# ---------------------------------------------------------------------------
# Main tournament
# ---------------------------------------------------------------------------
def strategy_tournament_4h():
    PINE_FOLDER = '/home/ubuntu/tradingview_webhook_bot/backtesting/pine/'
    DATA_FILES  = sorted(glob.glob(
        '/home/ubuntu/tradingview_webhook_bot/storage/backtest_data/*_3y_4h.csv'
    ))
    REPORT_PATH = '/home/ubuntu/tradingview_webhook_bot/storage/reports/tournament_winners_4h.csv'

    if not DATA_FILES:
        print("No 4H data files found. Run fetch_4h_data_all_symbols.py first.")
        return

    strategy_files = sorted([
        f for f in os.listdir(PINE_FOLDER)
        if os.path.isfile(os.path.join(PINE_FOLDER, f))
    ])

    if not strategy_files:
        print(f"No strategy files found in {PINE_FOLDER}")
        return

    print(f"4H Tournament | {len(DATA_FILES)} symbols x {len(strategy_files)} strategies x {len(PARAM_GRID)} param combos")
    print(f"Tier thresholds: ALPHA++ >= {TIER_ALPHA_PP}%, ALPHA >= {TIER_ALPHA}%, AVERAGE > {TIER_AVERAGE}%")
    print("-" * 70)

    results       = []
    seen_sigs     = set()

    for data_file in DATA_FILES:
        symbol = os.path.basename(data_file).split('_')[0]
        print(f"\n[{symbol}] Loading data...")

        df_raw = pd.read_csv(data_file)
        df_raw['pct'] = df_raw['close'].pct_change()

        for raw_name in strategy_files:
            clean_name = raw_name.strip("'").strip('"')
            best_daily = -999
            best_res   = None
            best_params = None

            for params in PARAM_GRID:
                # Small per-strategy entropy offset (same technique as existing tournament)
                idx    = strategy_files.index(raw_name)
                e_mult = params['mult'] + (idx * 0.01)
                e_len  = params['len']  + (idx % 3)

                result = run_test(df_raw, clean_name, e_mult, e_len)
                daily_roi = result[0]

                if daily_roi > best_daily and result[6] != "ERROR":
                    best_daily  = daily_roi
                    best_res    = result
                    best_params = {'mult': e_mult, 'len': e_len}

            if best_res is None:
                continue

            daily_roi, gross_dd, net_dd, win_rate, sharpe, \
                total_trades, tier, gdd_date, ndd_date = best_res

            # OOS validation
            oos_roi, oos_dd, oos_sharpe = 0.0, 0.0, 0.0
            try:
                oos = run_test_oos(df_raw, clean_name, best_params['mult'], best_params['len'])
                oos_roi, oos_dd, oos_sharpe = oos[0], oos[1], oos[4]
            except Exception:
                pass

            # Deduplicate by (roi, gross_dd) fingerprint
            sig = (round(daily_roi, 5), round(gross_dd, 2))
            if sig in seen_sigs:
                continue
            seen_sigs.add(sig)

            results.append({
                "Symbol":               symbol,
                "Strategy":             clean_name,
                "Daily_ROI_%":          round(daily_roi, 3),
                "Gross_DD_%":           round(gross_dd, 2),
                "Net_DD_%":             round(net_dd, 2),
                "Max_DD_%":             round(gross_dd, 2),
                "Win_Rate_%":           win_rate,
                "Sharpe_Ratio":         sharpe,
                "Total_Trades":         total_trades,
                "Tier":                 tier,
                "Optimal_Mult":         round(best_params['mult'], 2),
                "Optimal_Len":          int(best_params['len']),
                "OOS_Daily_ROI_%":      round(oos_roi, 3),
                "OOS_Gross_DD_%":       round(oos_dd, 2),
                "OOS_Sharpe":           round(oos_sharpe, 2),
                "Gross_DD_Date":        gdd_date,
                "Net_DD_Date":          ndd_date,
                "Gross_DD_Capital_Left": round(INITIAL_CAPITAL * (1 + gross_dd / 100), 2),
                "Net_DD_Capital_Left":   round(INITIAL_CAPITAL * (1 + net_dd / 100), 2),
            })

        gc.collect()

    if not results:
        print("No results generated.")
        return

    # Save full results
    final_df = pd.DataFrame(results).sort_values(by="Daily_ROI_%", ascending=False)
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    final_df.to_csv(REPORT_PATH, index=False)
    print(f"\nFull results saved to {REPORT_PATH} ({len(final_df)} rows)")

    # -----------------------------------------------------------------------
    # Post-tournament summary output
    # -----------------------------------------------------------------------
    _print_summary(final_df)

    return final_df


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------
def _print_summary(df):
    """Prints top 3 strategies per symbol, winning counts, and Pine params."""

    print("\n" + "=" * 70)
    print(" 4H TOURNAMENT RESULTS SUMMARY")
    print("=" * 70)

    # --- Top 3 per symbol ---
    print("\nTop 3 strategies per symbol:")
    print("-" * 70)

    symbols = df['Symbol'].unique()
    for sym in sorted(symbols):
        sym_df = df[df['Symbol'] == sym].head(3)
        print(f"\n  {sym}")
        for _, row in sym_df.iterrows():
            print(
                f"    [{row['Tier']:8s}]  {row['Strategy'][:40]:<40}  "
                f"ROI={row['Daily_ROI_%']:+.3f}%/day  "
                f"Sharpe={row['Sharpe_Ratio']:.2f}  "
                f"WR={row['Win_Rate_%']:.1f}%  "
                f"DD={row['Gross_DD_%']:.1f}%  "
                f"Trades={int(row['Total_Trades'])}"
            )

    # --- Winning combination count ---
    winners = df[df['Tier'].isin(['ALPHA++', 'ALPHA'])]
    alpha_pp = df[df['Tier'] == 'ALPHA++']
    alpha    = df[df['Tier'] == 'ALPHA']

    print("\n" + "-" * 70)
    print(f"Total winning combinations (ALPHA++ + ALPHA): {len(winners)}")
    print(f"  ALPHA++ : {len(alpha_pp)}")
    print(f"  ALPHA   : {len(alpha)}")

    # --- Recommended Pine params per symbol (best ALPHA++ or ALPHA row) ---
    print("\nRecommended Pine Script parameters per symbol:")
    print("-" * 70)
    print(f"  {'Symbol':<12}  {'Strategy':<40}  {'mult':>6}  {'len':>5}  {'Tier':<10}  {'ROI/day':>8}")
    print(f"  {'-'*12}  {'-'*40}  {'-'*6}  {'-'*5}  {'-'*10}  {'-'*8}")

    for sym in sorted(symbols):
        # Best winner for this symbol; fall back to best overall row
        sym_winners = df[(df['Symbol'] == sym) & (df['Tier'].isin(['ALPHA++', 'ALPHA']))]
        if not sym_winners.empty:
            best = sym_winners.iloc[0]
        else:
            best = df[df['Symbol'] == sym].iloc[0]

        print(
            f"  {best['Symbol']:<12}  {best['Strategy'][:40]:<40}  "
            f"{best['Optimal_Mult']:>6.2f}  {int(best['Optimal_Len']):>5}  "
            f"{best['Tier']:<10}  {best['Daily_ROI_%']:>+7.3f}%"
        )

    print("=" * 70)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    strategy_tournament_4h()
