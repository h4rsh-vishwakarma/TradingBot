import sqlite3
import pandas as pd

DB_PATH = 'storage/trading_system.db'

def generate_summary():
    conn = sqlite3.connect(DB_PATH)
    
    # Query to get all trades and their run metadata
    query = """
    SELECT r.strategy_id, r.symbol, r.mode, t.pnl 
    FROM trades t
    JOIN runs r ON t.run_id = r.id
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    if df.empty:
        print("📭 No data found to report.")
        return

    # Filter out entries with no PnL (Open positions or Entry logs)
    df = df.dropna(subset=['pnl'])

    # Grouping by Strategy to calculate metrics
    report = df.groupby(['strategy_id', 'symbol']).apply(lambda x: pd.Series({
        'Total Trades': len(x),
        'Net Profit': x['pnl'].sum(),
        'Win Rate %': (len(x[x['pnl'] > 0]) / len(x)) * 100,
        'Gross Profit': x[x['pnl'] > 0]['pnl'].sum(),
        'Gross Loss': abs(x[x['pnl'] < 0]['pnl'].sum()),
    })).reset_index()

    # Calculate Profit Factor
    report['Profit Factor'] = report['Gross Profit'] / report['Gross Loss'].replace(0, 1)

    print("\n" + "="*50)
    print("🚀 STRATEGY PERFORMANCE REPORT (v1)")
    print("="*50)
    print(report[['strategy_id', 'symbol', 'Total Trades', 'Net Profit', 'Win Rate %', 'Profit Factor']].to_string(index=False))
    print("="*50 + "\n")

if __name__ == "__main__":
    generate_summary()
