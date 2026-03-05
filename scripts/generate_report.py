import sqlite3
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os

def sync_to_sheets(df):
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name('/app/service_account.json', scope)
        client = gspread.authorize(creds)
        
        # Spreadsheet name must match exactly
        spreadsheet = client.open('Trading_Bot_Ledger')
        
        # Try to find or create the 'Backtest_Leaderboard' tab
        try:
            worksheet = spreadsheet.worksheet('Backtest_Leaderboard')
        except gspread.exceptions.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(title='Backtest_Leaderboard', rows='100', cols='10')

        # Clear old data and update with new leaderboard
        worksheet.clear()
        worksheet.update([df.columns.values.tolist()] + df.values.tolist())
        print('✅ Successfully synced to Google Sheets: Backtest_Leaderboard')
        
    except Exception as e:
        print(f'❌ Sheets Sync Failed: {str(e)}')

def generate():
    db_path = '/app/storage/idempotency.db'
    if not os.path.exists(db_path):
        print('❌ Database not found!')
        return

    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query('SELECT strategy_name, net_profit, profit_factor, max_drawdown, total_trades, timestamp FROM strategy_metrics ORDER BY profit_factor DESC', conn)
    conn.close()

    if df.empty:
        print('⚠️ No data to sync.')
        return

    print('\n🏆 --- CURRENT LEADERBOARD --- 🏆')
    print(df.to_string(index=False))
    
    # Run Sync
    sync_to_sheets(df)

if __name__ == '__main__':
    generate()
