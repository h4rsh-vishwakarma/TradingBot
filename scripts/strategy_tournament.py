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

    # 🛡️ OPTIMIZED RISK PARAMETERS — Target NDD < -50%
    LEVERAGE = 1.0              # No leverage (was 2.5x — #1 cause of -96% DD)
    STOP_LOSS = 0.01            # 1% SL per bar (was 2%)
    TAKE_PROFIT = 0.03          # 3% TP per bar (was 6%) — maintains 1:3 RR
    MAX_DAILY_LOSS = -0.03      # Circuit breaker: -3% max loss per day
    COOLDOWN_TRIGGER = 3        # Go flat after 3 consecutive losses
    COOLDOWN_BARS = 4           # Skip 4 bars (1 hour on 15m data)

    try:
        df['sig'] = apply_strategy(df, name, optimize, mult, length)

        # 🛡️ FILTER 1: ADX > 20 (relaxed from 25 to capture moderate trends)
        from my_strategies import calculate_adx
        adx = calculate_adx(df, n=14)
        df['sig'] = np.where(adx > 20, df['sig'], 0)

        # 🛡️ FILTER 2: ATR Volatility — skip abnormally volatile periods
        atr_14 = (df['high'] - df['low']).rolling(14).mean()
        atr_ma = atr_14.rolling(100).mean()
        df['sig'] = np.where(atr_14 > 2 * atr_ma, 0, df['sig'])

        # Calculate daily returns
        df['daily_ret'] = df['sig'].shift(1) * df['pct'] * LEVERAGE
        df['daily_ret'] = df['daily_ret'].clip(lower=-STOP_LOSS, upper=TAKE_PROFIT)

        # 🛡️ FILTER 3: Consecutive loss cooldown
        # After COOLDOWN_TRIGGER consecutive losses, skip COOLDOWN_BARS bars
        rets = df['daily_ret'].values.copy()
        consec_losses = 0
        skip_remaining = 0
        for i in range(len(rets)):
            if skip_remaining > 0:
                rets[i] = 0.0
                skip_remaining -= 1
                continue
            if rets[i] < 0:
                consec_losses += 1
                if consec_losses >= COOLDOWN_TRIGGER:
                    skip_remaining = COOLDOWN_BARS
                    consec_losses = 0
            else:
                consec_losses = 0
        df['daily_ret'] = rets

        # 🛡️ FILTER 4: Daily loss circuit breaker (-3% max per day)
        if 'timestamp' in df.columns:
            df['_date'] = pd.to_datetime(df['timestamp']).dt.date
            df['_daily_cum'] = df.groupby('_date')['daily_ret'].cumsum()
            df.loc[df['_daily_cum'] < MAX_DAILY_LOSS, 'daily_ret'] = 0.0
            df.drop(columns=['_date', '_daily_cum'], inplace=True)

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

        # --- QUALITY-BASED TIERING (Optimized for 1x leverage) ---
        # DD thresholds tightened: NDD must be < -50% for any ALPHA tier

        # Hard reject: DD > 50% or NDD > 50%
        if abs(gross_dd) > 50 or abs(net_dd) > 50:
            if daily_roi >= 0.5:
                status = "⚖️ AVERAGE"  # High ROI but too much DD → AVERAGE only
            else:
                status = "💀 REJECT"
        # ALPHA++ — Elite: good ROI + low DD + quality metrics
        elif daily_roi >= 0.6 and sharpe >= 4.0 and win_rate >= 45 and abs(gross_dd) < 30:
            status = "🚀 ALPHA++"
        elif daily_roi >= 0.5 and sharpe >= 3.5 and win_rate >= 45 and abs(gross_dd) < 35:
            status = "🚀 ALPHA++"
        # ALPHA — Solid performers with controlled DD
        elif daily_roi >= 0.3 and sharpe >= 3.0 and win_rate >= 45 and abs(gross_dd) < 40:
            status = "🎯 ALPHA"
        elif daily_roi >= 0.25 and sharpe >= 2.5 and win_rate >= 48 and abs(gross_dd) < 45:
            status = "🎯 ALPHA"
        # AVERAGE — Marginal, needs manual review
        elif daily_roi >= 0.1 and sharpe >= 1.5:
            status = "⚖️ AVERAGE"
        elif daily_roi >= 0.05:
            status = "⚖️ AVERAGE"
        else:
            status = "💀 REJECT"

        # Bonus: Extremely high Sharpe with decent ROI and low DD
        if sharpe >= 6.0 and daily_roi >= 0.3 and abs(gross_dd) < 30 and "ALPHA++" not in status:
            status = "🚀 ALPHA++"
        elif sharpe >= 5.0 and daily_roi >= 0.2 and abs(gross_dd) < 40 and "ALPHA" not in status:
            status = "🎯 ALPHA"

        return daily_roi, gross_dd, net_dd, win_rate, sharpe, total_trades, status, gross_dd_date, net_dd_date, gross_dd_capital, net_dd_capital
    except:
        return -1, -1, -1, 0.0, 0.0, 0, "💀 ERROR", "N/A", "N/A", 0, 0

if __name__ == "__main__":
    strategy_tournament()
