import sqlite3
import os

print("Working Directory:", os.getcwd())

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'db.sqlite3')

def initialize_db():
    # Points to your existing file in the root
    conn = sqlite3.connect('db.sqlite3') 
    cursor = conn.cursor()
    
    # Create the metrics table specifically for CSV ingestion
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_name TEXT UNIQUE,
            net_profit REAL,
            profit_factor REAL,
            win_rate REAL,
            max_dd REAL,
            sharpe REAL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()
    print("✅ Table 'metrics' successfully created in db.sqlite3")

if __name__ == "__main__":
    initialize_db()