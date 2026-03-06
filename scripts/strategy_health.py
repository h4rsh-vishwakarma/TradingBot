import sqlite3
import pandas as pd
import os

DB_PATH = os.path.expanduser("~/tradingview_webhook_bot/storage/idempotency.db")

def get_loser_strategies():
    if not os.path.exists(DB_PATH):
        return []
    
    try:
        conn = sqlite3.connect(DB_PATH)
        # Strategies dhundna jinka net_profit negative hai
        df = pd.read_sql_query("SELECT strategy_name, net_profit FROM strategy_metrics WHERE net_profit < 0", conn)
        conn.close()
        return df['strategy_name'].tolist()
    except Exception as e:
        print(f"Error reading DB: {e}")
        return []

if __name__ == "__main__":
    losers = get_loser_strategies()
    print(f"📉 Current Loser Strategies (Counter-Trade Candidates): {losers}")
