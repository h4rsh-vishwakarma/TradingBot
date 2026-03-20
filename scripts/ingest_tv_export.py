import pandas as pd
import sqlite3
import os
import sys

def ingest_data(file_path):
    db_path = '/app/storage/idempotency.db'
    
    if not os.path.exists(file_path):
        print(f'❌ Error: {file_path} not found')
        return

    try:
        # Read TV Export
        df = pd.read_csv(file_path)
        
        # Connect to DB
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Create table if not exists (QBA-003)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS strategy_metrics (
                strategy_name TEXT,
                net_profit REAL,
                profit_factor REAL,
                max_drawdown TEXT,
                total_trades INTEGER,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Insert Data
        for _, row in df.iterrows():
            cursor.execute('''
                INSERT INTO strategy_metrics (strategy_name, net_profit, profit_factor, max_drawdown, total_trades)
                VALUES (?, ?, ?, ?, ?)
            ''', (row.get('Strategy'), row.get('Net Profit'), row.get('Profit Factor'), row.get('Max Drawdown'), row.get('Trades')))
        
        conn.commit()
        conn.close()
        print(f'✅ Successfully ingested {len(df)} strategies into database.')

    except Exception as e:
        print(f'❌ Ingestion failed: {str(e)}')

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--file', required=True)
    args = parser.parse_args()
    ingest_data(args.file)
