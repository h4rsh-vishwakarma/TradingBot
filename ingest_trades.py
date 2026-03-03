import pandas as pd
import sqlite3
import sys
import os

DB_PATH = 'storage/trading_system.db'

def ingest_tv_export(file_path, strategy_id, symbol, timeframe):
    if not os.path.exists(file_path):
        print(f"❌ Error: File {file_path} not found.")
        return

    # Load CSV
    try:
        df = pd.read_csv(file_path)
        # TradingView CSV columns: 'Trade #', 'Type', 'Signal', 'Date/Time', 'Price', 'Profit', etc.
        print(f"📊 Processing {len(df)} trades from {file_path}...")
    except Exception as e:
        print(f"❌ Error reading CSV: {e}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Create a unique Run ID for this import
    run_id = f"BT_{strategy_id}_{symbol}_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}"
    
    try:
        # 1. Insert Run Metadata
        cursor.execute("INSERT INTO runs (id, strategy_id, symbol, timeframe, mode) VALUES (?, ?, ?, ?, 'BACKTEST')",
                       (run_id, strategy_id, symbol, timeframe))

        # 2. Insert Trades
        for _, row in df.iterrows():
            # Basic mapping (Adapt based on your TV CSV header)
            side = row.get('Type', 'ENTRY')
            price = row.get('Price', 0)
            qty = row.get('Contracts', 0)
            ts = row.get('Date/Time', '')
            pnl = row.get('Profit', 0)

            cursor.execute('''INSERT INTO trades (run_id, timestamp, side, qty, price, pnl) 
                              VALUES (?, ?, ?, ?, ?, ?)''', 
                           (run_id, ts, side, qty, price, pnl))

        conn.commit()
        print(f"✅ Successfully ingested into Run ID: {run_id}")
    except Exception as e:
        print(f"❌ Database Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("Usage: python3 ingest_trades.py <file.csv> <strategy_id> <symbol> <timeframe>")
    else:
        ingest_tv_export(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
