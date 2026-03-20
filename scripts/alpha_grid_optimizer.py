import pandas as pd
import numpy as np
import glob
import os
import gc

def alpha_grid_optimizer():
    files = glob.glob('/home/ubuntu/tradingview_webhook_bot/storage/backtest_data/*.csv')
    master_results = []

    # Parameters: Thoda flexible range
    rsi_windows = [10, 14]
    leverages = [2.0, 3.0]
    tp_sl_ratios = [1.5, 2.0] # Reward to Risk Ratio

    print("🛡️ Booting Survival Optimizer... Looking for the best possible match.")

    for file in files:
        symbol = os.path.basename(file).split('_')[0]
        df_raw = pd.read_csv(file)
        df_raw['close'] = df_raw['close'].astype(float)
        df_raw['pct_ret'] = df_raw['close'].pct_change()

        best_daily = -999
        best_setup = None

        for rsi_w in rsi_windows:
            for lev in leverages:
                for rr in tp_sl_ratios:
                    df = df_raw.copy()
                    
                    # Logic: RSI + Price Action
                    up = np.where(df['pct_ret'] > 0, df['pct_ret'], 0)
                    down = np.where(df['pct_ret'] < 0, -df['pct_ret'], 0)
                    df['rsi'] = 100 - (100 / (1 + pd.Series(up).rolling(rsi_w).mean() / pd.Series(down).rolling(rsi_w).mean()))
                    
                    # Signal logic
                    df['signal'] = 0
                    df.loc[df['rsi'] < 30, 'signal'] = 1
                    df.loc[df['rsi'] > 70, 'signal'] = -1

                    # Execution with RR Ratio
                    sl = 0.02 # 2% SL for breathing room
                    tp = sl * rr
                    
                    df['strat_ret'] = df['signal'].shift(1) * df['pct_ret'] * lev
                    df['strat_ret'] = df['strat_ret'].clip(lower=-sl, upper=tp)
                    
                    cum_res = (1 + df['strat_ret'].fillna(0)).cumprod()
                    daily_avg = ((cum_res.iloc[-1] - 1) * 100) / 365
                    dd = ((cum_res - cum_res.cummax()) / cum_res.cummax()).min() * 100

                    # Thoda realistic filter (0.7% Daily, 20% DD)
                    if daily_avg >= 0.7 and abs(dd) <= 25:
                        if daily_avg > best_daily:
                            best_daily = daily_avg
                            best_setup = {
                                "Symbol": symbol,
                                "Daily_%": round(daily_avg, 2),
                                "DD_%": round(dd, 2),
                                "Lev": lev,
                                "RR": rr
                            }
                    del df
                    gc.collect()

        if best_setup:
            master_results.append(best_setup)

    if master_results:
        print("\n✅ --- FOUND SURVIVAL ALPHAS --- ✅")
        print(pd.DataFrame(master_results))
    else:
        print("\n🛑 Deep Failure: Market is too volatile for this logic. Need to switch to Scalping mode.")

alpha_grid_optimizer()
