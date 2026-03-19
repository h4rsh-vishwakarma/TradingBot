import pandas as pd
import numpy as np
import glob
import os
import gc

def auto_tune_symbols():
    files = glob.glob('/home/ubuntu/tradingview_webhook_bot/storage/backtest_data/*.csv')
    master_leaderboard = []

    # Parameter Space to test
    leverages = [1.0, 1.5, 2.0]
    stops = [0.01, 0.015, 0.02] # 1%, 1.5%, 2%
    
    print("🧠 Starting Multi-Strategy Auto-Tuner & Backup Logic...")

    for file in files:
        symbol = os.path.basename(file).split('_')[0]
        df_full = pd.read_csv(file, usecols=['timestamp', 'close'])
        df_full['close'] = df_full['close'].astype(float)
        df_full['pct_change'] = df_full['close'].pct_change()

        best_for_symbol = None
        max_daily = -999

        # --- Strategy 1: RSI Mean Reversion (Current Best) ---
        # --- Strategy 2: Trend Following (EMA Cross - Backup) ---
        df_full['ema_fast'] = df_full['close'].rolling(20).mean()
        df_full['ema_slow'] = df_full['close'].rolling(50).mean()

        for lev in leverages:
            for sl in stops:
                # Loop through different logics
                for strategy_type in ['RSI_REVERSION', 'TREND_FOLLOW']:
                    df = df_full.copy()
                    
                    if strategy_type == 'RSI_REVERSION':
                        # RSI Logic (Existing)
                        df['up'] = np.where(df['pct_change'] > 0, df['pct_change'], 0)
                        df['down'] = np.where(df['pct_change'] < 0, -df['pct_change'], 0)
                        df['rsi'] = 100 - (100 / (1 + df['up'].rolling(14).mean() / df['down'].rolling(14).mean()))
                        df['signal'] = np.where(df['rsi'] < 30, 1, np.where(df['rsi'] > 70, -1, 0))
                    
                    else:
                        # Trend Logic (Backup)
                        df['signal'] = np.where(df['ema_fast'] > df['ema_slow'], 1, -1)

                    # Calculate Returns with SL/TP
                    df['strat_ret'] = df['signal'].shift(1) * df['pct_change'] * lev
                    df['strat_ret'] = df['strat_ret'].clip(lower=-sl, upper=0.04)
                    
                    cum_res = (1 + df['strat_ret'].fillna(0)).cumprod()
                    total_ret = (cum_res.iloc[-1] - 1) * 100
                    daily_avg = total_ret / 365
                    
                    # Drawdown
                    max_dd = ((cum_res - cum_res.cummax()) / cum_res.cummax()).min() * 100

                    if daily_avg > max_daily and abs(max_dd) <= 15:
                        max_daily = daily_avg
                        best_for_symbol = {
                            "Symbol": symbol,
                            "Strategy": strategy_type,
                            "Leverage": lev,
                            "SL": sl,
                            "Daily_Avg_%": round(daily_avg, 3),
                            "Max_DD_%": round(max_dd, 2),
                            "Status": "🎯 ALPHA"
                        }
                    del df
                    gc.collect()
        
        if best_for_symbol:
            master_leaderboard.append(best_for_symbol)

    results_df = pd.DataFrame(master_leaderboard)
    print("\n🏆 --- AUTO-TUNED ALPHA LEADERBOARD (WITH BACKUPS) --- 🏆")
    print(results_df.to_string(index=False))
    results_df.to_csv("/home/ubuntu/tradingview_webhook_bot/storage/reports/alpha_tuned_results.csv", index=False)

if __name__ == "__main__":
    auto_tune_symbols()
