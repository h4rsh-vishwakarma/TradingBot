#!/usr/bin/env python3
"""Direct sheet verification - check what's actually in the sheet"""
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timezone

scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_name('/home/ubuntu/trading_bot/credentials.json', scope)
client = gspread.authorize(creds)

sheet_key = '1ysGcPSyyJrlX3Wo7C4s7TCkRVF-d9YlvG7LbZeNNQ8k'
worksheet = client.open_by_key(sheet_key).worksheet('fr')

print("=== CHECKING ACTUAL GOOGLE SHEET CONTENT ===")
print(f"Current time: {datetime.now(timezone.utc)}")
print()

# Method 1: get_all_values
all_values = worksheet.get_all_values()
print(f"Total rows (including header): {len(all_values)}")
print(f"Last 5 rows:")
for row in all_values[-5:]:
    print(f"  {row}")
print()

# Method 2: Direct range
range_data = worksheet.get('A2:F150')
print(f"Range A2:F150 rows: {len(range_data) if range_data else 0}")
if range_data:
    print(f"Last 3 rows from range:")
    for row in range_data[-3:]:
        print(f"  {row}")
print()

# Method 3: col_values for timestamp
ts_col = worksheet.col_values(1)
print(f"Timestamp column rows: {len(ts_col)}")
print(f"Last 5 timestamps:")
for ts in ts_col[-5:]:
    print(f"  {ts}")
