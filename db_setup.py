import sqlite3

def init_db():
    conn = sqlite3.connect('storage/trading_system.db')
    cursor = conn.cursor()

    # 1. Strategies Table
    cursor.execute('''CREATE TABLE IF NOT EXISTS strategies (
        id TEXT PRIMARY KEY,
        name TEXT,
        version TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')

    # 2. Runs Table (One backtest or one live forward-test session)
    cursor.execute('''CREATE TABLE IF NOT EXISTS runs (
        id TEXT PRIMARY KEY,
        strategy_id TEXT,
        symbol TEXT,
        timeframe TEXT,
        start_date DATETIME,
        end_date DATETIME,
        settings_hash TEXT,
        mode TEXT CHECK(mode IN ('BACKTEST', 'FORWARD')),
        FOREIGN KEY(strategy_id) REFERENCES strategies(id)
    )''')

    # 3. Trades Table
    cursor.execute('''CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT,
        timestamp DATETIME,
        side TEXT,
        qty REAL,
        price REAL,
        pnl REAL,
        FOREIGN KEY(run_id) REFERENCES runs(id)
    )''')

    # 4. Metrics Table (The summary results)
    cursor.execute('''CREATE TABLE IF NOT EXISTS metrics (
        run_id TEXT PRIMARY KEY,
        net_profit REAL,
        profit_factor REAL,
        win_rate REAL,
        max_drawdown REAL,
        trades_count INTEGER,
        FOREIGN KEY(run_id) REFERENCES runs(id)
    )''')

    conn.commit()
    conn.close()
    print("✅ Database Schema initialized successfully in storage/trading_system.db")

if __name__ == "__main__":
    init_db()
