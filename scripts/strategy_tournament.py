import pandas as pd
import numpy as np
import glob
import os
import gc
from my_strategies import apply_strategy

def strategy_tournament():
    PINE_FOLDER = '/home/ubuntu/tradingview_webhook_bot/backtesting/pine/'
    DATA_FILES = glob.glob('/home/ubuntu/tradingview_webhook_bot/storage/backtest_data/*.csv')
    REPORT_PATH = '/home/ubuntu/tradingview_webhook_bot/storage/reports/tournament_winners.csv'

    all_files = [f for f in os.listdir(PINE_FOLDER) if os.path.isfile(os.path.join(PINE_FOLDER, f))]
    results = []

    print(f"🚀 AUTO-TUNER ACTIVE: Testing {len(all_files)} files...")

    for data_file in DATA_FILES:
        symbol = os.path.basename(data_file).split('_')[0]
        df_raw = pd.read_csv(data_file)
        df_raw['close'] = df_raw['close'].astype(float)
        df_raw['pct'] = df_raw['close'].pct_change()

        for raw_name in all_files:
            clean_name = raw_name.strip("'").strip('"')

            # STAGE 1: Standard Test
            daily_avg, max_dd, tier = run_test(df_raw, clean_name, optimize=False)

            # STAGE 2: Auto-Tune (If failed or Average)
            if tier in ["💀 HIGH_RISK", "📉 LOSS", "⚖️ AVERAGE"]:
                print(f"🔧 Tuning {clean_name} for {symbol}...")
                daily_opt, dd_opt, tier_opt = run_test(df_raw, clean_name, optimize=True)

                # Keep the best version if it improves returns or tier
                if daily_opt > daily_avg or tier_opt == "🎯 ALPHA":
                    daily_avg, max_dd, tier = daily_opt, dd_opt, f"{tier_opt} (Optimized)"

            results.append({
                "Symbol": symbol,
                "Strategy": clean_name,
                "Daily_%": round(daily_avg, 3),
                "Max_DD_%": round(max_dd, 2),
                "Tier": tier
            })
            gc.collect()

    final_df = pd.DataFrame(results).sort_values(by=["Daily_%"], ascending=False)
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    final_df.to_csv(REPORT_PATH, index=False)
    print("\n🏆 --- FINAL OPTIMIZED LEADERBOARD --- 🏆")
    print(final_df.to_string(index=False))

# run_test function ko sirf update karo
def run_test(df_raw, name, optimize):
    df = df_raw.copy()
    
    # ALPHA SETTINGS
    LEVERAGE = 2.5 if optimize else 1.2 # Boost leverage for High Confidence
    STOP_LOSS = 0.025 # Tighter 2.5% SL
    TAKE_PROFIT = 0.075 # Aggressive 7.5% TP

    df['sig'] = apply_strategy(df, name, optimize=optimize)
    df['strat_ret'] = df['sig'].shift(1) * df['pct'] * LEVERAGE
    df['strat_ret'] = df['strat_ret'].clip(lower=-STOP_LOSS, upper=TAKE_PROFIT)

    cum_res = (1 + df['strat_ret'].fillna(0)).cumprod()
    daily_avg = ((cum_res.iloc[-1] - 1) * 100) / 365
    max_dd = ((cum_res - cum_res.cummax()) / cum_res.cummax()).min() * 100

    # NEW TIER LOGIC
    if daily_avg >= 0.5 and abs(max_dd) <= 18: status = "🎯 ALPHA"
    elif daily_avg > 0.1 and abs(max_dd) <= 25: status = "⚖️ AVERAGE"
    else: status = "💀 REJECT"

    return daily_avg, max_dd, status

if __name__ == "__main__":
    strategy_tournament()
