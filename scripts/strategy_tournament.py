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

    # Optimized Grid for 2% Daily Target
    param_grid = [
        {'mult': 1.8, 'len': 9},   # Hyper-Aggressive
        {'mult': 2.5, 'len': 14},  # Balanced
        {'mult': 3.5, 'len': 21}   # Trend-Following
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

                daily, dd, status = run_test(df_raw, clean_name, True, e_mult, e_len)

                if daily > best_daily and status != "💀 ERROR":
                    best_daily = daily
                    best_res = (daily, dd, status, {'mult': e_mult, 'len': e_len})

            if best_res:
                daily_roi, max_dd, tier, opt_p = best_res
                
                # Check uniqueness
                sig = (round(daily_roi, 5), round(max_dd, 2))
                if sig not in seen_signatures:
                    seen_signatures.add(sig)
                    results.append({
                        "Symbol": symbol,
                        "Strategy": clean_name,
                        "Daily_ROI_%": round(daily_roi, 3), # Naya Column
                        "Max_DD_%": round(max_dd, 2),
                        "Tier": tier,
                        "Optimal_Mult": round(opt_p['mult'], 2),
                        "Optimal_Len": int(opt_p['len'])
                    })
            gc.collect()

    final_df = pd.DataFrame(results).sort_values(by=["Daily_ROI_%"], ascending=False)
    final_df.to_csv(REPORT_PATH, index=False)
    
    print("\n🚀 --- TOP ALPHA STRATEGIES (TARGET 2% DAILY) --- 🚀")
    print(final_df.head(15).to_string(index=False))

def run_test(df_raw, name, optimize, mult, length):
    df = df_raw.copy()
    
    # ⚡ MODERATE LEVERAGE FOR LONG-TERM STABILITY
    # 4x is too high for 3 years, reducing to 2.5x to stop "Infinity" math
    LEVERAGE = 2.5 if optimize else 1.0 
    STOP_LOSS = 0.02   # 2% SL
    TAKE_PROFIT = 0.06 # 6% TP
    
    try:
        df['sig'] = apply_strategy(df, name, optimize, mult, length)
        
        # Calculate daily returns (NON-COMPOUNDING to prevent e+22)
        # We assume fixed position size to get realistic daily %
        df['daily_ret'] = df['sig'].shift(1) * df['pct'] * LEVERAGE
        df['daily_ret'] = df['daily_ret'].clip(lower=-STOP_LOSS, upper=TAKE_PROFIT)

        # 📊 Realistic ROI Calculation
        # Total profit / Total days
        total_days = 1095
        total_return_sum = df['daily_ret'].sum() * 100 # Total percent
        
        daily_roi = total_return_sum / total_days
        
        # Max Drawdown still needs compounding to see the peak-to-trough
        cum_res = (1 + df['daily_ret'].fillna(0)).cumprod()
        max_dd = ((cum_res - cum_res.cummax()) / cum_res.cummax()).min() * 100

        # Tiering based on 2% Goal
        if daily_roi >= 1.5: status = "🚀 ALPHA++" 
        elif daily_roi >= 0.5: status = "🎯 ALPHA"
        elif daily_roi > 0.1: status = "⚖️ AVERAGE"
        else: status = "💀 REJECT"
            
        return daily_roi, max_dd, status
    except:
        return -1, -1, "💀 ERROR"

if __name__ == "__main__":
    strategy_tournament()
