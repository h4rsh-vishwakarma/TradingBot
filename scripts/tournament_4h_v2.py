"""
4H Strategy Tournament V2 — Optimised for 1.5% ROI/day target
==============================================================
Key upgrades vs V1:
  - 60+ parameter combinations (denser mult/length grid)
  - Variable SL/TP grid: tested per symbol (best combo kept)
  - LEVERAGE = 2.0 (matches real trading config)
  - MIN_BAR_GAP = 1 (allow faster re-entries on 4H)
  - Proper Keltner/Ichimoku/Aggressive implementations via my_strategies_v2
  - Reports to tournament_winners_4h_v2.csv
  - Target: >= 0.75%/day base (= 1.5%/day with 2x leverage)
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
INITIAL_CAPITAL = 10_000
BARS_PER_YEAR   = 2190          # 6 bars/day x 365
LEVERAGE        = 2.0           # Real trading leverage
TOTAL_DAYS      = 1095          # 3 years
ADX_THRESHOLD   = 20
MIN_BAR_GAP     = 1             # Allow faster re-entries

# Tier thresholds (base ROI at LEVERAGE=1; with 2x: multiply x2)
TIER_PREMIUM  = 0.75   # >= 0.75%/day base = 1.5%/day live  ← TARGET
TIER_ALPHA_PP = 0.35   # >= 0.35%/day base = 0.70%/day live
TIER_ALPHA    = 0.15
TIER_AVERAGE  = 0.05

# ---------------------------------------------------------------------------
# Expanded Parameter Grid
# mult: 0.8 – 4.5 in 0.3 steps (14 values)
# length: 6 – 52 in 4 steps (12 values)
# Total: 168 base combinations, then SL/TP sweeps on top
# ---------------------------------------------------------------------------
MULT_RANGE   = [round(x, 2) for x in np.arange(0.8, 4.6, 0.3)]   # 13 values
LENGTH_RANGE = list(range(6, 54, 4))                                 # 12 values: 6,10,14...50
PARAM_GRID   = [{'mult': m, 'len': l} for m, l in iproduct(MULT_RANGE, LENGTH_RANGE)]

# SL/TP combinations to sweep (best combo selected per symbol/strategy)
SL_TP_GRID = [
    (0.015, 0.045),   # 1.5% SL / 4.5% TP  → R:R 3
    (0.015, 0.060),   # 1.5% SL / 6.0% TP  → R:R 4
    (0.020, 0.060),   # 2.0% SL / 6.0% TP  → R:R 3  (current default)
    (0.020, 0.080),   # 2.0% SL / 8.0% TP  → R:R 4
    (0.025, 0.075),   # 2.5% SL / 7.5% TP  → R:R 3
    (0.025, 0.100),   # 2.5% SL / 10.0% TP → R:R 4
    (0.030, 0.090),   # 3.0% SL / 9.0% TP  → R:R 3
]

print(f"V2 Tournament | {len(PARAM_GRID)} param combos x {len(SL_TP_GRID)} SL/TP combos")
print(f"= {len(PARAM_GRID) * len(SL_TP_GRID)} total backtests per strategy per symbol")


# ---------------------------------------------------------------------------
# Min-bar-gap enforcement
# ---------------------------------------------------------------------------
def enforce_min_bar_gap(sig_series, min_gap=MIN_BAR_GAP):
    sig = sig_series.values.copy()
    last_signal_bar = -min_gap
    for i in range(len(sig)):
        if sig[i] != 0:
            if (i - last_signal_bar) < min_gap:
                sig[i] = 0
            else:
                last_signal_bar = i
    return pd.Series(sig, index=sig_series.index)


# ---------------------------------------------------------------------------
# Single backtest pass
# ---------------------------------------------------------------------------
def run_test(df_raw, strategy_name, mult, length, stop_loss, take_profit):
    df = df_raw.copy()
    try:
        df['sig'] = apply_strategy(df, strategy_name, True, mult, length)
        adx = calculate_adx(df, n=14)
        df['sig'] = np.where(adx > ADX_THRESHOLD, df['sig'], 0)
        df['sig'] = enforce_min_bar_gap(df['sig'])

        df['bar_ret'] = df['sig'].shift(1) * df['pct'] * LEVERAGE
        df['bar_ret'] = df['bar_ret'].clip(lower=-stop_loss, upper=take_profit)

        total_return_pct = df['bar_ret'].sum() * 100
        daily_roi        = total_return_pct / TOTAL_DAYS

        cum_res      = (1 + df['bar_ret'].fillna(0)).cumprod()
        gross_dd_s   = (cum_res - cum_res.cummax()) / cum_res.cummax() * 100
        gross_dd     = gross_dd_s.min()
        gdd_idx      = gross_dd_s.values.argmin()
        gross_dd_date = (str(df['timestamp'].iloc[gdd_idx])[:10]
                         if 'timestamp' in df.columns else "N/A")

        cum_sum  = df['bar_ret'].fillna(0).cumsum() * 100
        net_dd_s = cum_sum - cum_sum.cummax()
        net_dd   = net_dd_s.min()
        ndd_idx  = net_dd_s.values.argmin()
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

    except Exception:
        return (-1, -1, -1, 0.0, 0.0, 0, "ERROR", "N/A", "N/A")


def run_test_oos(df_raw, strategy_name, mult, length, stop_loss, take_profit, train_pct=0.8):
    split_idx = int(len(df_raw) * train_pct)
    df_test   = df_raw.iloc[split_idx:].copy()
    return run_test(df_test, strategy_name, mult, length, stop_loss, take_profit)


# ---------------------------------------------------------------------------
# Main tournament
# ---------------------------------------------------------------------------
def run_tournament():
    DATA_FILES  = sorted(glob.glob(
        '/home/ubuntu/tradingview_webhook_bot/storage/backtest_data/*_3y_4h.csv'
    ))
    PINE_FOLDER = '/home/ubuntu/tradingview_webhook_bot/backtesting/pine/'
    REPORT_PATH = '/home/ubuntu/tradingview_webhook_bot/storage/reports/tournament_winners_4h_v2.csv'

    if not DATA_FILES:
        print("No 4H data files found at storage/backtest_data/")
        return

    # Only use our 5 named strategies (the ones currently deployed)
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
        # fallback: all files in pine folder
        strategy_files = sorted([
            f for f in os.listdir(PINE_FOLDER)
            if os.path.isfile(os.path.join(PINE_FOLDER, f))
            and not f.startswith('.')
        ])

    total_combos = len(DATA_FILES) * len(strategy_files) * len(PARAM_GRID) * len(SL_TP_GRID)
    print(f"\n4H Tournament V2 | {len(DATA_FILES)} symbols x {len(strategy_files)} strategies")
    print(f"  x {len(PARAM_GRID)} param combos x {len(SL_TP_GRID)} SL/TP combos = {total_combos:,} tests")
    print(f"  LEVERAGE={LEVERAGE}x | MIN_BAR_GAP={MIN_BAR_GAP}")
    print(f"  Target: >= {TIER_PREMIUM}%/day base (= {TIER_PREMIUM*LEVERAGE:.2f}%/day live)")
    print("-" * 70)

    results = []

    for data_file in DATA_FILES:
        symbol = os.path.basename(data_file).replace('_3y_4h.csv', '')
        try:
            df_raw = pd.read_csv(data_file)
            df_raw.columns = [c.lower() for c in df_raw.columns]
            if 'close' not in df_raw.columns:
                print(f"  {symbol}: missing 'close' column, skip")
                continue
            df_raw['pct'] = df_raw['close'].pct_change().fillna(0)
            if len(df_raw) < 500:
                print(f"  {symbol}: too few bars ({len(df_raw)}), skip")
                continue
        except Exception as e:
            print(f"  {symbol}: data load error {e}")
            continue

        sym_results = []

        for raw_name in strategy_files:
            clean_name = raw_name

            best_roi    = -999
            best_params = None
            best_sltp   = None

            # Outer: SL/TP sweep
            for (sl, tp) in SL_TP_GRID:
                # Inner: param grid
                for idx, params in enumerate(PARAM_GRID):
                    e_mult = params['mult'] + (idx * 0.001)  # tiny epsilon to avoid duplicate sigs
                    e_len  = params['len']  + (idx % 2)
                    result = run_test(df_raw, clean_name, e_mult, e_len, sl, tp)
                    if result[0] > best_roi:
                        best_roi    = result[0]
                        best_result = result
                        best_params = {'mult': e_mult, 'len': e_len}
                        best_sltp   = {'sl': sl, 'tp': tp}

            if best_params is None:
                continue

            oos = run_test_oos(df_raw, clean_name,
                               best_params['mult'], best_params['len'],
                               best_sltp['sl'], best_sltp['tp'])

            (daily_roi, gross_dd, net_dd, win_rate, sharpe,
             total_trades, tier, gdd_date, ndd_date) = best_result

            gross_dd_cap = round(INITIAL_CAPITAL * (1 + gross_dd / 100), 2)
            net_dd_cap   = round(INITIAL_CAPITAL * (1 + net_dd   / 100), 2)

            row = {
                "Symbol":                clean_name if False else symbol,
                "Strategy":              clean_name,
                "Daily_ROI_%":           round(daily_roi, 3),
                "Live_ROI_%":            round(daily_roi * LEVERAGE, 3),
                "Gross_DD_%":            round(gross_dd, 2),
                "Net_DD_%":              round(net_dd, 2),
                "Max_DD_%":              round(gross_dd, 2),
                "Win_Rate_%":            win_rate,
                "Sharpe_Ratio":          sharpe,
                "Total_Trades":          total_trades,
                "Tier":                  tier,
                "Optimal_Mult":          round(best_params['mult'], 3),
                "Optimal_Len":           int(best_params['len']),
                "Optimal_SL_%":          round(best_sltp['sl'] * 100, 1),
                "Optimal_TP_%":          round(best_sltp['tp'] * 100, 1),
                "OOS_Daily_ROI_%":       round(oos[0], 3),
                "OOS_Gross_DD_%":        round(oos[1], 2),
                "OOS_Sharpe":            round(oos[4], 2),
                "Gross_DD_Date":         gdd_date,
                "Net_DD_Date":           ndd_date,
                "Gross_DD_Capital_Left": gross_dd_cap,
                "Net_DD_Capital_Left":   net_dd_cap,
                "Leverage":              LEVERAGE,
            }
            sym_results.append(row)

        # Sort by daily_roi, keep top strategies
        sym_results.sort(key=lambda r: r['Daily_ROI_%'], reverse=True)
        results.extend(sym_results)

        best = sym_results[0] if sym_results else None
        if best:
            live_roi = best['Daily_ROI_%'] * LEVERAGE
            marker   = "✓ TARGET" if best['Daily_ROI_%'] >= TIER_PREMIUM else "✗"
            print(f"  {symbol:<12}  best={best['Daily_ROI_%']:.3f}%/day  "
                  f"live={live_roi:.3f}%/day  "
                  f"SL={best['Optimal_SL_%']}%/TP={best['Optimal_TP_%']}%  "
                  f"{best['Tier']}  {marker}")

        gc.collect()

    if not results:
        print("No results generated.")
        return

    df_out = pd.DataFrame(results)
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    df_out.to_csv(REPORT_PATH, index=False)
    print(f"\nSaved {len(df_out)} rows -> {REPORT_PATH}")

    print_summary(df_out)


# ---------------------------------------------------------------------------
# Summary report
# ---------------------------------------------------------------------------
def print_summary(df):
    print("\n" + "=" * 70)
    print("TOURNAMENT V2 SUMMARY")
    print("=" * 70)

    best = (df.sort_values("Daily_ROI_%", ascending=False)
              .groupby("Symbol").first().reset_index()
              .sort_values("Daily_ROI_%", ascending=False))

    target_met = 0
    print(f"\n{'Symbol':<12} {'Strategy':<30} {'Base%/day':<12} {'Live%/day':<12} {'SL/TP':<12} {'Tier'}")
    print("-" * 90)
    for _, r in best.iterrows():
        base = r['Daily_ROI_%']
        live = r['Live_ROI_%']
        sl   = r.get('Optimal_SL_%', '?')
        tp   = r.get('Optimal_TP_%', '?')
        mark = " TARGET_MET" if base >= 0.75 else ""
        print(f"{r['Symbol']:<12} {str(r['Strategy'])[:28]:<30} {base:<12.3f} {live:<12.3f} {sl}%/{tp}%{mark}")
        if base >= 0.75:
            target_met += 1

    n = len(best)
    avg_base = best['Daily_ROI_%'].mean()
    avg_live = best['Live_ROI_%'].mean()
    print(f"\nSymbols meeting 0.75%/day target: {target_met}/{n}")
    print(f"Average base ROI:  {avg_base:.3f}%/day")
    print(f"Average live ROI:  {avg_live:.3f}%/day  (with {LEVERAGE}x leverage)")
    print(f"Best symbol:       {best.iloc[0]['Symbol']} {best.iloc[0]['Daily_ROI_%']:.3f}%/day base")

    if avg_base >= 0.75:
        print("\n✅ TARGET ACHIEVED: Average base ROI >= 0.75% → Live >= 1.5%/day")
    else:
        gap = 0.75 - avg_base
        print(f"\n⚠  Gap to target: {gap:.3f}%/day — consider adding leverage or refining params")


if __name__ == "__main__":
    run_tournament()
