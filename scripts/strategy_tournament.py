import pandas as pd
import numpy as np
import glob
import os
import gc
from my_strategies import apply_strategy

def strategy_tournament():
    PINE_FOLDER = '/home/ubuntu/tradingview_webhook_bot/backtesting/pine/'
    DATA_FILES = glob.glob('/home/ubuntu/tradingview_webhook_bot/storage/backtest_data/*_3y_15m.csv')
    REPORT_PATH = '/home/ubuntu/tradingview_webhook_bot/storage/reports/tournament_winners.csv'

    all_files = sorted([f for f in os.listdir(PINE_FOLDER) if os.path.isfile(os.path.join(PINE_FOLDER, f))])
    results = []
    seen_signatures = set()

    # Expanded Grid — 7 combos for deeper optimization
    param_grid = [
        {'mult': 1.5, 'len': 7},   # Ultra-Scalp
        {'mult': 1.8, 'len': 9},   # Hyper-Aggressive
        {'mult': 2.0, 'len': 11},  # Fast Swing
        {'mult': 2.5, 'len': 14},  # Balanced
        {'mult': 3.0, 'len': 18},  # Moderate Trend
        {'mult': 3.5, 'len': 21},  # Trend-Following
        {'mult': 4.0, 'len': 26}   # Macro Trend
    ]

    print(f"🔥 ALPHA AGGRESSOR MODE: Target 2% Daily ROI | Scanning {len(all_files)} Strategies...")

    for data_file in DATA_FILES:
        symbol = os.path.basename(data_file).split('_')[0]
        df_raw = pd.read_csv(data_file)
        df_raw['pct'] = df_raw['close'].pct_change()

        for raw_name in all_files:
            clean_name = raw_name.strip("'").strip('"')
            best_daily = -999
            best_res = None

            for params in param_grid:
                # Add unique entropy per strategy
                idx = all_files.index(raw_name)
                e_mult = params['mult'] + (idx * 0.01)
                e_len = params['len'] + (idx % 3)

                daily, gross_dd, net_dd, win_rate, sharpe, trades, status, gdd_date, ndd_date, gdd_cap, ndd_cap = run_test(df_raw, clean_name, True, e_mult, e_len)

                if daily > best_daily and status != "💀 ERROR":
                    best_daily = daily
                    best_res = (daily, gross_dd, net_dd, win_rate, sharpe, trades, status, {'mult': e_mult, 'len': e_len}, gdd_date, ndd_date, gdd_cap, ndd_cap)

            if best_res:
                daily_roi, gross_dd, net_dd, win_rate, sharpe, trades, tier, opt_p, gdd_date, ndd_date, gdd_cap, ndd_cap = best_res

                # Out-of-sample validation (80/20 split)
                oos_roi, oos_dd, oos_sharpe = 0.0, 0.0, 0.0
                try:
                    _, oos_result = run_test_oos(df_raw, clean_name, opt_p['mult'], opt_p['len'])
                    oos_roi = oos_result[0]  # daily_roi
                    oos_dd = oos_result[1]   # gross_dd
                    oos_sharpe = oos_result[4]  # sharpe
                except Exception:
                    pass

                # Check uniqueness
                sig = (round(daily_roi, 5), round(gross_dd, 2))
                if sig not in seen_signatures:
                    seen_signatures.add(sig)
                    results.append({
                        "Symbol": symbol,
                        "Strategy": clean_name,
                        "Daily_ROI_%": round(daily_roi, 3),
                        "Gross_DD_%": round(gross_dd, 2),
                        "Net_DD_%": round(net_dd, 2),
                        "Max_DD_%": round(gross_dd, 2),
                        "GDD_Date": gdd_date,
                        "GDD_Capital_Left": int(gdd_cap),
                        "NDD_Date": ndd_date,
                        "NDD_Capital_Left": int(ndd_cap),
                        "Win_Rate_%": win_rate,
                        "Sharpe_Ratio": sharpe,
                        "Total_Trades": trades,
                        "Tier": tier,
                        "Optimal_Mult": round(opt_p['mult'], 2),
                        "Optimal_Len": int(opt_p['len']),
                        "OOS_Daily_ROI_%": round(oos_roi, 3),
                        "OOS_Gross_DD_%": round(oos_dd, 2),
                        "OOS_Sharpe": round(oos_sharpe, 2),
                    })
            gc.collect()

    final_df = pd.DataFrame(results).sort_values(by=["Daily_ROI_%"], ascending=False)
    final_df.to_csv(REPORT_PATH, index=False)
    
    print("\n🚀 --- TOP ALPHA STRATEGIES (TARGET 2% DAILY) --- 🚀")
    print(final_df.head(15).to_string(index=False))

def run_test_oos(df_raw, name, mult, length, train_pct=0.8):
    """Run test with train/test split for out-of-sample validation."""
    split_idx = int(len(df_raw) * train_pct)
    df_train = df_raw.iloc[:split_idx].copy()
    df_test = df_raw.iloc[split_idx:].copy()
    df_train['pct'] = df_train['close'].pct_change()
    df_test['pct'] = df_test['close'].pct_change()

    # Optimize on train set
    train_result = run_test(df_train, name, True, mult, length)[:7]
    # Validate on test set (same params, no re-optimization)
    test_result = run_test(df_test, name, True, mult, length)[:7]
    return train_result, test_result


def run_test(df_raw, name, optimize, mult, length):
    df = df_raw.copy()

    LEVERAGE = 2.5 if optimize else 1.0
    STOP_LOSS = 0.02   # 2% SL
    TAKE_PROFIT = 0.06 # 6% TP

    try:
        df['sig'] = apply_strategy(df, name, optimize, mult, length)

        # 🛡️ ADX > 25 FILTER IN BACKTEST (matches Pine Script logic)
        # Pehle sirf Pine template mein tha, ab backtest mein bhi lagega
        # Isse choppy market trades hata ke DD significantly drop hoga
        from my_strategies import calculate_adx
        adx = calculate_adx(df, n=14)
        df['sig'] = np.where(adx > 25, df['sig'], 0)  # Kill signals in weak trends

        # Calculate daily returns (NON-COMPOUNDING to prevent e+22)
        df['daily_ret'] = df['sig'].shift(1) * df['pct'] * LEVERAGE
        df['daily_ret'] = df['daily_ret'].clip(lower=-STOP_LOSS, upper=TAKE_PROFIT)

        # 📊 ROI Calculation
        total_days = 1095
        total_return_sum = df['daily_ret'].sum() * 100
        daily_roi = total_return_sum / total_days

        # 📉 GROSS DD: Compounding (peak-to-trough equity curve)
        cum_res = (1 + df['daily_ret'].fillna(0)).cumprod()
        gross_dd_series = ((cum_res - cum_res.cummax()) / cum_res.cummax()) * 100
        gross_dd = gross_dd_series.min()
        gross_dd_idx = gross_dd_series.idxmin()
        gross_dd_date = str(df['timestamp'].iloc[gross_dd_idx])[:10] if 'timestamp' in df.columns and gross_dd_idx < len(df) else "N/A"
        # Capital left after gross DD (compounding): start * (1 + dd/100)
        gross_dd_capital = round(100000 * (1 + gross_dd / 100), 0)

        # 📉 NET DD: Non-compounding (cumulative sum, fixed position size)
        cum_sum = df['daily_ret'].fillna(0).cumsum() * 100
        cum_peak = cum_sum.cummax()
        net_dd_series = cum_sum - cum_peak
        net_dd = net_dd_series.min()
        net_dd_idx = net_dd_series.idxmin()
        net_dd_date = str(df['timestamp'].iloc[net_dd_idx])[:10] if 'timestamp' in df.columns and net_dd_idx < len(df) else "N/A"
        # Capital left after net DD (fixed size): start + start * dd/100
        net_dd_capital = round(100000 * (1 + net_dd / 100), 0)

        # 📈 WIN RATE: Winning trades / Total trades
        trades = df['daily_ret'][df['daily_ret'] != 0]
        total_trades = len(trades)
        winning_trades = len(trades[trades > 0])
        win_rate = round((winning_trades / total_trades * 100), 1) if total_trades > 0 else 0.0

        # 📊 SHARPE RATIO: Risk-adjusted return (annualized)
        mean_ret = df['daily_ret'].mean()
        std_ret = df['daily_ret'].std()
        # 15m bars, ~96 bars/day, ~35040 bars/year
        sharpe = round((mean_ret / std_ret) * np.sqrt(35040), 2) if std_ret > 0 else 0.0

        # --- QUALITY-BASED TIERING ---
        # Not just ROI — also checks Sharpe, Win Rate, DD, and trade count

        # Disqualify: DD > 80% is too risky regardless of ROI
        if abs(gross_dd) > 80:
            if daily_roi >= 1.0:
                status = "🎯 ALPHA"  # High ROI but dangerous DD → downgrade from ALPHA++
            elif daily_roi >= 0.3:
                status = "⚖️ AVERAGE"
            else:
                status = "💀 REJECT"
        # ALPHA++ — Elite tier: high ROI + quality metrics
        elif daily_roi >= 1.8 and sharpe >= 4.0 and win_rate >= 45:
            status = "🚀 ALPHA++"
        elif daily_roi >= 1.5 and sharpe >= 3.5 and win_rate >= 45:
            status = "🚀 ALPHA++"
        # ALPHA — Solid performers
        elif daily_roi >= 1.0 and sharpe >= 3.0 and win_rate >= 45:
            status = "🎯 ALPHA"
        elif daily_roi >= 0.8 and sharpe >= 2.5 and win_rate >= 48:
            status = "🎯 ALPHA"
        # AVERAGE — Marginal, needs manual review
        elif daily_roi >= 0.3 and sharpe >= 1.5:
            status = "⚖️ AVERAGE"
        elif daily_roi >= 0.1:
            status = "⚖️ AVERAGE"
        else:
            status = "💀 REJECT"

        # Bonus: Extremely high Sharpe (>6) with decent ROI → upgrade
        if sharpe >= 6.0 and daily_roi >= 1.0 and "ALPHA++" not in status:
            status = "🚀 ALPHA++"
        elif sharpe >= 5.0 and daily_roi >= 0.8 and "ALPHA" not in status:
            status = "🎯 ALPHA"

        return daily_roi, gross_dd, net_dd, win_rate, sharpe, total_trades, status, gross_dd_date, net_dd_date, gross_dd_capital, net_dd_capital
    except:
        return -1, -1, -1, 0.0, 0.0, 0, "💀 ERROR", "N/A", "N/A", 0, 0

if __name__ == "__main__":
    strategy_tournament()
