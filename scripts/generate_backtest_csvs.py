"""
Generate Backtest CSVs for all strategies from tournament data.
Creates per-trade PnL CSVs in backtesting/A_Leaderboard/backtest_imports/
so that BacktestEngine.validate_signal() can find and score them.
"""

import os, sys, pandas as pd, numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from my_strategies import apply_strategy, calculate_adx

DATA_DIR = PROJECT_ROOT / "storage" / "backtest_data"
OUTPUT_DIR = PROJECT_ROOT / "backtesting" / "A_Leaderboard" / "backtest_imports"
REPORT_PATH = PROJECT_ROOT / "storage" / "reports" / "tournament_winners.csv"

LEVERAGE = 2.5
STOP_LOSS = 0.02
TAKE_PROFIT = 0.06

def generate_trade_csv(symbol, strategy_name, mult, length):
    """Generate a per-trade PnL CSV from backtest data."""
    data_file = DATA_DIR / f"{symbol}_3y_15m.csv"
    if not data_file.exists():
        print(f"  Data file missing: {data_file}")
        return False

    df = pd.read_csv(data_file)
    df['pct'] = df['close'].pct_change()

    try:
        df['sig'] = apply_strategy(df, strategy_name, True, mult, length)
        adx = calculate_adx(df, n=14)
        df['sig'] = np.where(adx > 25, df['sig'], 0)

        # Return from each signal: sig[t] causes return at t+1
        # So trade_ret[t] = sig[t] * pct[t+1] * LEVERAGE
        df['trade_ret'] = df['sig'] * df['pct'].shift(-1) * LEVERAGE
        df['trade_ret'] = df['trade_ret'].clip(lower=-STOP_LOSS, upper=TAKE_PROFIT)
    except Exception as e:
        print(f"  Strategy error: {e}")
        return False

    # Extract only bars where a trade happened (signal != 0)
    trades = df[df['sig'] != 0][['timestamp', 'close', 'sig', 'trade_ret']].copy()
    trades = trades.rename(columns={
        'timestamp': 'Date',
        'close': 'Price',
        'sig': 'Side',
        'trade_ret': 'Profit'
    })
    trades['Side'] = trades['Side'].map({1: 'Long', -1: 'Short'})
    trades['Profit'] = (trades['Profit'] * 100).round(4)  # Convert to %

    if trades.empty:
        print(f"  No trades generated")
        return False

    # Clean filename for output
    clean_name = (strategy_name.replace("'", "").replace('"', '').replace("[", "")
                  .replace("]", "").replace(",", "").replace(" ", "_")[:50])
    clean_sym = symbol.replace("USDT", "USD")
    filename = f"{clean_name}_{clean_sym}_backtest.csv"
    out_path = OUTPUT_DIR / filename

    trades.to_csv(out_path, index=False)
    return True

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    if not REPORT_PATH.exists():
        print("tournament_winners.csv not found!")
        return

    df = pd.read_csv(REPORT_PATH)
    total = len(df)
    success = 0

    print(f"Generating backtest CSVs for {total} strategy-symbol combos...\n")

    for _, row in df.iterrows():
        symbol = row['Symbol']
        strategy = row['Strategy']
        mult = float(row.get('Optimal_Mult', 3.0))
        length = int(row.get('Optimal_Len', 14))

        print(f"  [{symbol}] {strategy[:40]}...", end=" ")
        if generate_trade_csv(symbol, strategy, mult, length):
            print("OK")
            success += 1
        else:
            print("SKIP")

    print(f"\nDone: {success}/{total} CSVs generated in {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
