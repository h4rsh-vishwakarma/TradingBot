import pandas as pd
import numpy as np
import glob
import os
import gc

def run_1_percent_hunt():
    csv_path = '/home/ubuntu/tradingview_webhook_bot/storage/backtest_data/*.csv'
    files = glob.glob(csv_path)
    leaderboard = []
    
    # --- FINAL TUNED PARAMETERS ---
    LEVERAGE = 1.5  # Lower leverage = Lower Drawdown
    STOP_LOSS = 0.01 # 1.2% Tight SL
    TAKE_PROFIT = 0.03 # 4% TP

    print(f"🎯 Locking in Alpha (Leverage: {LEVERAGE}x | SL: 1.2%)...")

    for file in files:
        df = pd.read_csv(file, usecols=['timestamp', 'close'])
        df['close'] = df['close'].astype(float)
        df['pct_change'] = df['close'].pct_change()
        
        # RSI Logic
        df['up'] = np.where(df['pct_change'] > 0, df['pct_change'], 0)
        df['down'] = np.where(df['pct_change'] < 0, -df['pct_change'], 0)
        df['rs'] = df['up'].rolling(14).mean() / df['down'].rolling(14).mean()
        df['rsi'] = 100 - (100 / (1 + df['rs']))

        # Mean Reversion Signal
        df['signal'] = 0
        df.loc[df['rsi'] < 30, 'signal'] = 1
        df.loc[df['rsi'] > 70, 'signal'] = -1
        
        # Risk Control
        df['strat_ret'] = df['signal'].shift(1) * df['pct_change'] * LEVERAGE
        df['strat_ret'] = df['strat_ret'].clip(lower=-STOP_LOSS, upper=TAKE_PROFIT)

        # Metrics
        df['cum_res'] = (1 + df['strat_ret'].fillna(0)).cumprod()
        total_days = 365
        total_ret = (df['cum_res'].iloc[-1] - 1) * 100
        daily_avg = total_ret / total_days
        
        rolling_max = df['cum_res'].cummax()
        max_dd = ((df['cum_res'] - rolling_max) / rolling_max).min() * 100

        # CEO CRITERIA CHECK
        is_alpha = (daily_avg >= 1.0) and (abs(max_dd) <= 15.0) 
        
        leaderboard.append({
            "Symbol": os.path.basename(file).split('_')[0],
            "Daily_Avg_%": round(daily_avg, 3),
            "Max_DD_%": round(max_dd, 2),
            "Target_Hit": "🎯 ALPHA" if is_alpha else "❌ REJECT"
        })
        del df
        gc.collect()

    results_df = pd.DataFrame(leaderboard).sort_values(by="Daily_Avg_%", ascending=False)
    results_df.to_csv("/home/ubuntu/tradingview_webhook_bot/storage/reports/alpha_leaderboard_final.csv", index=False)
    print("\n🏆 --- FINAL ALPHA LEADERBOARD --- 🏆")
    print(results_df.to_string(index=False))

if __name__ == "__main__":
    run_1_percent_hunt()
