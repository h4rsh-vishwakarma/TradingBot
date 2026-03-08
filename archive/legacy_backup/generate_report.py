import sqlite3
import pandas as pd
from datetime import datetime
import os

DB_PATH = 'storage/trading_system.db'
REPORT_OUTPUT = 'storage/performance_report.html'

def generate_summary():
    if not os.path.exists(DB_PATH):
        print(f"❌ Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)

    try:
        # Improved Query: Join runs and trades to get strategy details
        query = """
        SELECT r.strategy_id, r.symbol, r.mode, t.pnl, t.timestamp, t.side
        FROM trades t
        JOIN runs r ON t.run_id = r.id
        """
        df = pd.read_sql_query(query, conn)
        conn.close()

        if df.empty:
            print("📭 No trades found in database to report.")
            return

        # Data Cleaning: Handle missing PnL (often 0 or None for entry logs)
        df['pnl'] = df['pnl'].fillna(0)

        # Metrics Calculation Logic
        stats = df.groupby(['strategy_id', 'symbol']).apply(lambda x: pd.Series({
            'Trades': len(x),
            'Net_Profit': round(x['pnl'].sum(), 2),
            'Win_Rate': round((len(x[x['pnl'] > 0]) / len(x)) * 100, 2) if len(x) > 0 else 0,
            'Gross_Profit': x[x['pnl'] > 0]['pnl'].sum(),
            'Gross_Loss': abs(x[x['pnl'] < 0]['pnl'].sum()),
        })).reset_index()

        # Profit Factor Calculation
        stats['Profit_Factor'] = (stats['Gross_Profit'] / stats['Gross_Loss'].replace(0, 1)).round(2)

        # --- 1. TERMINAL PRINT ---
        print("\n" + "="*60)
        print(f"🚀 PERFORMANCE SUMMARY | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print("="*60)
        print(stats[['strategy_id', 'symbol', 'Trades', 'Net_Profit', 'Win_Rate', 'Profit_Factor']].to_string(index=False))
        print("="*60 + "\n")

        # --- 2. HTML REPORT GENERATION ---
        html_style = """
        <style>
            body { font-family: 'Segoe UI', sans-serif; margin: 40px; background: #f8f9fa; }
            .card { background: white; padding: 20px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
            table { width: 100%; border-collapse: collapse; margin-top: 20px; }
            th, td { padding: 12px; text-align: left; border-bottom: 1px solid #eee; }
            th { background: #2d3436; color: white; }
            tr:hover { background: #f1f2f6; }
            .pos { color: #27ae60; font-weight: bold; }
            .neg { color: #e74c3c; font-weight: bold; }
            .header { display: flex; justify-content: space-between; align-items: center; }
        </style>
        """

        html_table = stats.to_html(classes='table', index=False)
        # Adding color coding to Net Profit
        html_table = html_table.replace('<td>-', '<td class="neg">-').replace('<td>', '<td>$') # Simple styling trick

        full_html = f"""
        <html>
        <head>{html_style}</head>
        <body>
            <div class="card">
                <div class="header">
                    <h1>📈 Trading Strategy Dashboard</h1>
                    <p>Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                </div>
                <hr>
                {html_table}
            </div>
        </body>
        </html>
        """

        with open(REPORT_OUTPUT, "w") as f:
            f.write(full_html)
        print(f"✅ HTML Report saved to: {REPORT_OUTPUT}")

    except Exception as e:
        print(f"❌ Error generating report: {e}")

if __name__ == "__main__":
    generate_summary()
