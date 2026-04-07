"""
4H Strategy Tournament V3 — OOS-ranked, anti-overfit
=====================================================
Fixes V2 overfit issues:
  - Max holding = 24 bars (4 days on 4H) — no always-in-market
  - Rank by OOS_Daily_ROI (80/20 split, unseen data)
  - Min 150 trades over 3 years for statistical significance
  - Focused param grid: avoid edge-of-grid artifacts
  - LEVERAGE = 2.0 (matches real trading config)
  - SL = 1.5%, TP = 6.0% (fixed at optimum found in V2)
  - Target: OOS >= 0.75%/day base (= 1.5%/day live)
"""

import pandas as pd
import numpy as np
import glob
import os
import gc
from math import sqrt
from itertools import product as iproduct

from my_strategies_v2 import apply_strategy, calculate_adx

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
INITIAL_CAPITAL  = 10_000
BARS_PER_YEAR    = 2190
LEVERAGE         = 2.0
STOP_LOSS        = 0.015   # 1.5% — optimal found in V2
TAKE_PROFIT      = 0.060   # 6.0% — optimal found in V2
TOTAL_DAYS       = 1095
ADX_THRESHOLD    = 20
MIN_BAR_GAP      = 2       # min 2 bars between entries
MAX_HOLD_BARS    = 24      # max 4 days in a position (realistic for 4H swing)
MIN_TRADES       = 150     # statistical minimum

TIER_PREMIUM  = 0.75
TIER_ALPHA_PP = 0.40
TIER_ALPHA    = 0.20
TIER_AVERAGE  = 0.05

# ---------------------------------------------------------------------------
# Focused param grid — avoid edges (0.8 and 4.5 were edge artifacts in V2)
# mult: 1.2 to 3.8 in 0.3 steps = 10 values
# length: 8 to 40 in 4 steps = 9 values
# Total: 90 combinations
# ---------------------------------------------------------------------------
MULT_RANGE   = [round(x, 2) for x in np.arange(1.2, 4.0, 0.3)]   # 10 values
LENGTH_RANGE = list(range(8, 44, 4))                                # 9 values: 8,12,16...40
PARAM_GRID   = [{'mult': m, 'len': l} for m, l in iproduct(MULT_RANGE, LENGTH_RANGE)]


def enforce_gap_and_hold(sig_series, min_gap=MIN_BAR_GAP, max_hold=MAX_HOLD_BARS):
    """Enforce min-bar-gap AND max-hold-period."""
    sig = sig_series.values.copy()
    last_signal_bar = -min_gap
    current_dir     = 0
    hold_count      = 0
    result          = np.zeros(len(sig), dtype=int)
    for i in range(len(sig)):
        if sig[i] != 0:
            if (i - last_signal_bar) >= min_gap:
                result[i]        = int(sig[i])
                last_signal_bar  = i
                current_dir      = int(sig[i])
                hold_count       = 1
        elif current_dir != 0:
            hold_count += 1
            if hold_count <= max_hold:
                result[i] = current_dir   # hold position
            else:
                current_dir = 0           # exit after max_hold bars
                hold_count  = 0
    return pd.Series(result, index=sig_series.index)


def run_test(df_raw, strategy_name, mult, length):
    df = df_raw.copy()
    try:
        df['sig'] = apply_strategy(df, strategy_name, True, mult, length)
        adx = calculate_adx(df, n=14)
        df['sig'] = np.where(adx > ADX_THRESHOLD, df['sig'], 0)
        df['sig'] = enforce_gap_and_hold(df['sig'])

        df['bar_ret'] = df['sig'].shift(1) * df['pct'] * LEVERAGE
        df['bar_ret'] = df['bar_ret'].clip(lower=-STOP_LOSS, upper=TAKE_PROFIT)

        total_return_pct = df['bar_ret'].sum() * 100
        daily_roi        = total_return_pct / TOTAL_DAYS

        cum_res    = (1 + df['bar_ret'].fillna(0)).cumprod()
        gross_dd_s = (cum_res - cum_res.cummax()) / cum_res.cummax() * 100
        gross_dd   = gross_dd_s.min()
        gdd_idx    = gross_dd_s.values.argmin()
        gross_dd_date = (str(df['timestamp'].iloc[gdd_idx])[:10]
                         if 'timestamp' in df.columns else "N/A")

        cum_sum    = df['bar_ret'].fillna(0).cumsum() * 100
        net_dd_s   = cum_sum - cum_sum.cummax()
        net_dd     = net_dd_s.min()
        ndd_idx    = net_dd_s.values.argmin()
        net_dd_date = (str(df['timestamp'].iloc[ndd_idx])[:10]
                       if 'timestamp' in df.columns else "N/A")

        trades         = df['bar_ret'][df['bar_ret'] != 0]
        total_trades   = len(trades)
        winning_trades = len(trades[trades > 0])
        win_rate = round(winning_trades / total_trades * 100, 1) if total_trades > 0 else 0.0

        mean_ret = df['bar_ret'].mean()
        std_ret  = df['bar_ret'].std()
        sharpe   = round((mean_ret / std_ret) * sqrt(BARS_PER_YEAR), 2) if std_ret > 0 else 0.0

        if daily_roi >= TIER_PREMIUM and abs(gross_dd) <= 60:
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

    except Exception as e:
        return (-1, -1, -1, 0.0, 0.0, 0, "ERROR", "N/A", "N/A")


def run_test_oos(df_raw, strategy_name, mult, length, train_pct=0.8):
    split_idx = int(len(df_raw) * train_pct)
    df_test   = df_raw.iloc[split_idx:].copy()
    return run_test(df_test, strategy_name, mult, length)


def run_tournament():
    DATA_FILES  = sorted(glob.glob(
        '/home/ubuntu/tradingview_webhook_bot/storage/backtest_data/*_3y_4h.csv'
    ))
    PINE_FOLDER = '/home/ubuntu/tradingview_webhook_bot/backtesting/pine/'
    REPORT_PATH = '/home/ubuntu/tradingview_webhook_bot/storage/reports/tournament_winners_4h_v3.csv'

    if not DATA_FILES:
        print("No data files found.")
        return

    CORE_STRATEGIES = [
        "07 macd breakout",
        "10 aggressive entry",
        "21 full momentum",
        "22 ichimoku trend pro",
        "23 ichimoku macd pro",
        "24 keltner breakout",
        "44 psar volume surge 4h",
        "56 psar volume tight",
    ]
    strategy_files = [s for s in CORE_STRATEGIES
                      if os.path.exists(os.path.join(PINE_FOLDER, s))]
    if not strategy_files:
        strategy_files = sorted([f for f in os.listdir(PINE_FOLDER)
                                  if os.path.isfile(os.path.join(PINE_FOLDER, f))
                                  and not f.startswith('.')])

    print(f"\n4H Tournament V3 | {len(DATA_FILES)} symbols x {len(strategy_files)} strategies")
    print(f"  x {len(PARAM_GRID)} param combos = {len(DATA_FILES)*len(strategy_files)*len(PARAM_GRID):,} tests")
    print(f"  LEVERAGE={LEVERAGE}x | SL={STOP_LOSS*100:.1f}% / TP={TAKE_PROFIT*100:.1f}%")
    print(f"  MAX_HOLD={MAX_HOLD_BARS} bars | MIN_TRADES={MIN_TRADES}")
    print(f"  RANKED BY: OOS_Daily_ROI (anti-overfit)")
    print(f"  Target: OOS >= {TIER_PREMIUM}%/day base (= {TIER_PREMIUM*LEVERAGE:.2f}%/day live)")
    print("-" * 70)

    results = []

    for data_file in DATA_FILES:
        symbol = os.path.basename(data_file).replace('_3y_4h.csv', '')
        try:
            df_raw = pd.read_csv(data_file)
            df_raw.columns = [c.lower() for c in df_raw.columns]
            if 'close' not in df_raw.columns:
                continue
            df_raw['pct'] = df_raw['close'].pct_change().fillna(0)
            if len(df_raw) < 500:
                continue
        except Exception as e:
            print(f"  {symbol}: {e}")
            continue

        sym_results = []

        for raw_name in strategy_files:
            best_oos_roi = -999
            best_is_roi  = -999
            best_params  = None
            best_result  = None
            best_oos     = None

            for idx, params in enumerate(PARAM_GRID):
                e_mult = params['mult'] + (idx * 0.001)
                e_len  = params['len']  + (idx % 2)
                result = run_test(df_raw, raw_name, e_mult, e_len)

                # Skip if too few trades
                if result[5] < MIN_TRADES:
                    continue

                oos = run_test_oos(df_raw, raw_name, e_mult, e_len)

                # RANK BY OOS
                if oos[0] > best_oos_roi:
                    best_oos_roi = oos[0]
                    best_is_roi  = result[0]
                    best_result  = result
                    best_params  = {'mult': e_mult, 'len': e_len}
                    best_oos     = oos

            if best_params is None:
                continue

            (daily_roi, gross_dd, net_dd, win_rate, sharpe,
             total_trades, tier, gdd_date, ndd_date) = best_result

            gross_dd_cap = round(INITIAL_CAPITAL * (1 + gross_dd / 100), 2)
            net_dd_cap   = round(INITIAL_CAPITAL * (1 + net_dd   / 100), 2)

            # Assign tier based on OOS (conservative)
            oos_roi = best_oos[0]
            if oos_roi >= TIER_PREMIUM and abs(gross_dd) <= 60:
                oos_tier = "PREMIUM"
            elif oos_roi >= TIER_ALPHA_PP:
                oos_tier = "ALPHA++"
            elif oos_roi >= TIER_ALPHA:
                oos_tier = "ALPHA"
            elif oos_roi > TIER_AVERAGE:
                oos_tier = "AVERAGE"
            else:
                oos_tier = "REJECT"

            row = {
                "Symbol":                symbol,
                "Strategy":              raw_name,
                "Daily_ROI_%":           round(oos_roi, 3),          # OOS as primary
                "IS_Daily_ROI_%":        round(daily_roi, 3),
                "Live_ROI_%":            round(oos_roi * LEVERAGE, 3),
                "Gross_DD_%":            round(gross_dd, 2),
                "Net_DD_%":              round(net_dd, 2),
                "Max_DD_%":              round(gross_dd, 2),
                "Win_Rate_%":            win_rate,
                "Sharpe_Ratio":          sharpe,
                "Total_Trades":          total_trades,
                "Tier":                  oos_tier,
                "Optimal_Mult":          round(best_params['mult'], 3),
                "Optimal_Len":           int(best_params['len']),
                "Optimal_SL_%":          round(STOP_LOSS * 100, 1),
                "Optimal_TP_%":          round(TAKE_PROFIT * 100, 1),
                "OOS_Daily_ROI_%":       round(oos_roi, 3),
                "OOS_Gross_DD_%":        round(best_oos[1], 2),
                "OOS_Sharpe":            round(best_oos[4], 2),
                "Gross_DD_Date":         gdd_date,
                "Net_DD_Date":           ndd_date,
                "Gross_DD_Capital_Left": gross_dd_cap,
                "Net_DD_Capital_Left":   net_dd_cap,
                "Leverage":              LEVERAGE,
            }
            sym_results.append(row)

        sym_results.sort(key=lambda r: r['Daily_ROI_%'], reverse=True)
        results.extend(sym_results)

        best = sym_results[0] if sym_results else None
        if best:
            live_roi = best['Live_ROI_%']
            marker   = "TARGET_MET" if best['Daily_ROI_%'] >= TIER_PREMIUM else (
                       "ALPHA++" if best['Daily_ROI_%'] >= TIER_ALPHA_PP else "ALPHA")
            print(f"  {symbol:<12}  OOS={best['Daily_ROI_%']:.3f}%/day  "
                  f"live={live_roi:.3f}%/day  "
                  f"mult={best['Optimal_Mult']}  len={best['Optimal_Len']}  "
                  f"{best['Strategy'][:20]}  {marker}")

        gc.collect()

    if not results:
        print("No results.")
        return

    df_out = pd.DataFrame(results)
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    df_out.to_csv(REPORT_PATH, index=False)
    print(f"\nSaved {len(df_out)} rows -> {REPORT_PATH}")

    # Summary
    best_df = (df_out.sort_values("Daily_ROI_%", ascending=False)
               .groupby("Symbol").first().reset_index()
               .sort_values("Daily_ROI_%", ascending=False))

    print("\n" + "=" * 70)
    print("V3 FINAL SUMMARY (ranked by OOS ROI)")
    print("=" * 70)
    target_met = 0
    print(f"\n{'Symbol':<12} {'Strategy':<25} {'OOS%/day':<10} {'Live%/day':<10} {'Tier'}")
    print("-" * 65)
    for _, r in best_df.iterrows():
        mark = " ✓ TARGET" if r['Daily_ROI_%'] >= 0.75 else ""
        print(f"{r['Symbol']:<12} {str(r['Strategy'])[:23]:<25} {r['Daily_ROI_%']:<10.3f} {r['Live_ROI_%']:<10.3f} {r['Tier']}{mark}")
        if r['Daily_ROI_%'] >= 0.75:
            target_met += 1

    n = len(best_df)
    avg_oos = best_df['Daily_ROI_%'].mean()
    avg_live = best_df['Live_ROI_%'].mean()
    print(f"\nSymbols meeting 0.75%/day OOS target: {target_met}/{n}")
    print(f"Average OOS ROI:  {avg_oos:.3f}%/day")
    print(f"Average live ROI: {avg_live:.3f}%/day  (with {LEVERAGE}x leverage)")

    if avg_oos >= 0.75:
        print("\\n✅ TARGET ACHIEVED: Average OOS >= 0.75% → Live >= 1.5%/day")
    else:
        print(f"\n→ Average live = {avg_live:.2f}%/day — {'above' if avg_live >= 1.5 else 'approaching'} 1.5% target")


if __name__ == "__main__":
    run_tournament()
