import pandas as pd
import os
import sqlite3
import re

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'db.sqlite3')
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(SCRIPT_DIR, 'backtest_imports')

def clean_val(val):
    if pd.isna(val) or val == "0": return 0.0
    # Removes everything except numbers, dots, and minus signs
    cleaned = re.sub(r'[^\d.-]', '', str(val))
    try:
        return float(cleaned)
    except:
        return 0.0

def parse_tv_csv(file_path):
    # 1. Load the CSV (TradingView 'List of Trades' is usually standard CSV)
    # Using 'utf-8-sig' to handle potential Byte Order Marks (BOM)
    df = pd.read_csv(file_path, encoding='utf-8-sig')

    # 2. Identify the correct columns
    # We use 'Net P&L USD' for profit and drawdown calculations
    pnl_col = 'Net P&L USD'
    
    if pnl_col not in df.columns:
        raise ValueError(f"Column '{pnl_col}' not found in {file_path}")

    # 3. Calculate Metrics
    net_profit = df[pnl_col].sum()
    
    # Profit Factor = (Sum of Wins) / |Sum of Losses|
    wins = df[df[pnl_col] > 0][pnl_col].sum()
    losses = abs(df[df[pnl_col] < 0][pnl_col].sum())
    profit_factor = (wins / losses) if losses != 0 else (wins if wins > 0 else 0.0)

    # Win Rate = (Number of winning trades / Total trades) * 100
    total_trades = len(df)
    win_rate = (len(df[df[pnl_col] > 0]) / total_trades * 100) if total_trades > 0 else 0.0

    # Max Drawdown (using Cumulative P&L)
    cum_pnl = df[pnl_col].cumsum()
    running_max = cum_pnl.cummax()
    drawdown = running_max - cum_pnl
    max_dd = drawdown.max()

    # Sharpe Ratio (Simplified: Mean / Std Dev)
    # Note: This is a basic version; professional Sharpe uses risk-free rates
    if total_trades > 1 and df[pnl_col].std() != 0:
        sharpe = (df[pnl_col].mean() / df[pnl_col].std()) * (total_trades**0.5)
    else:
        sharpe = 0.0

    # Clean the filename for the strategy name
    raw_name = os.path.basename(file_path)
    clean_name = raw_name.split('_BITSTAMP')[0].replace('_', ' ')

    return {
        "strategy_name": clean_name,
        "net_profit": round(float(net_profit), 2),
        "profit_factor": round(float(profit_factor), 2),
        "win_rate": round(float(win_rate), 2),
        "max_dd": round(float(max_dd), 2),
        "sharpe": round(float(sharpe), 2)
    }
    # Try multiple encodings because TradingView is inconsistent
    for enc in ['utf-8', 'utf-16', 'cp1252']:
        try:
            df = pd.read_csv(file_path, header=None, encoding=enc)
            break
        except:
            continue
    
    # Helper to find value even if there are extra spaces or weird characters
    def find_val(keyword):
        # Search the first column for the keyword
        mask = df[0].astype(str).str.contains(keyword, case=False, na=False)
        if not mask.any():
            return "0"
        return df[mask].iloc[0, 1]

    raw_name = os.path.basename(file_path)
    clean_name = raw_name.split('_BITSTAMP')[0].replace('_', ' ')

    return {
        "strategy_name": clean_name,
        "net_profit": clean_val(find_val("Net Profit")),
        "profit_factor": clean_val(find_val("Profit Factor")),
        "win_rate": clean_val(find_val("Percent Profitable")),
        "max_dd": clean_val(find_val("Max Drawdown")),
        "sharpe": clean_val(find_val("Sharpe Ratio"))
    }

def save_to_db(data):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO metrics (strategy_name, net_profit, profit_factor, win_rate, max_dd, sharpe)
        VALUES (:strategy_name, :net_profit, :profit_factor, :win_rate, :max_dd, :sharpe)
        ON CONFLICT(strategy_name) DO UPDATE SET
            net_profit=excluded.net_profit,
            profit_factor=excluded.profit_factor,
            win_rate=excluded.win_rate,
            max_dd=excluded.max_dd,
            sharpe=excluded.sharpe
    ''', data)
    conn.commit()
    conn.close()

if __name__ == "__main__":
    for file in os.listdir(INPUT_DIR):
        if file.endswith(".csv"):
            try:
                stats = parse_tv_csv(os.path.join(INPUT_DIR, file))
                save_to_db(stats)
                # This print will tell us if it's actually finding numbers now
                print(f"✅ {stats['strategy_name']}: Profit=${stats['net_profit']}")
            except Exception as e:
                print(f"❌ Error in {file}: {e}")