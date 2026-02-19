import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json

with open('credentials.json') as f:
    creds_data = json.load(f)

scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_data, scope)
gc = gspread.authorize(creds)

sheet = gc.open_by_key('1ysGcPSyyJrlX3Wo7C4s7TCkRVF-d9YlvG7LbZeNNQ8k')

# Analyze OI changes
print('\n' + '='*60)
print('OI CHANGE ANALYSIS')
print('='*60)
oi_ws = sheet.worksheet('oi')
oi_data = oi_ws.get_all_records()
df_oi = pd.DataFrame(oi_data)

oi_col = 'Open Interest (USD)'
df_oi[oi_col] = pd.to_numeric(df_oi[oi_col], errors='coerce')
df_oi = df_oi.dropna(subset=[oi_col])

# Calculate 5-period changes (matching bot logic)
changes = []
for i in range(5, len(df_oi)):
    latest = df_oi[oi_col].iloc[i]
    prev = df_oi[oi_col].iloc[i-5]
    change_pct = (latest - prev) / prev * 100 if prev > 0 else 0
    changes.append(abs(change_pct))

print(f'\nOI 5-period change statistics ({len(changes)} samples):')
print(f'  Mean: {pd.Series(changes).mean():.4f}%')
print(f'  Median: {pd.Series(changes).median():.4f}%')
print(f'  75th percentile: {pd.Series(changes).quantile(0.75):.4f}%')
print(f'  90th percentile: {pd.Series(changes).quantile(0.90):.4f}%')
print(f'  95th percentile: {pd.Series(changes).quantile(0.95):.4f}%')
print(f'  99th percentile: {pd.Series(changes).quantile(0.99):.4f}%')
print(f'  Max: {pd.Series(changes).max():.4f}%')

print(f'\n  Current bot threshold: 5.00%')
exceeds = sum(1 for c in changes if c > 5.0)
print(f'  Times exceeded: {exceeds} / {len(changes)} ({exceeds/len(changes)*100:.2f}%)')

# Recommended thresholds
print(f'\n  RECOMMENDED THRESHOLDS:')
print(f'    Conservative (95th percentile): {pd.Series(changes).quantile(0.95):.2f}%')
print(f'    Moderate (90th percentile): {pd.Series(changes).quantile(0.90):.2f}%')
print(f'    Aggressive (75th percentile): {pd.Series(changes).quantile(0.75):.2f}%')

# Analyze Funding Rate
print('\n' + '='*60)
print('FUNDING RATE ANALYSIS')
print('='*60)
fr_ws = sheet.worksheet('fr')
fr_data = fr_ws.get_all_records()
df_fr = pd.DataFrame(fr_data)

funding_col = 'Funding Rate'
df_fr[funding_col] = pd.to_numeric(df_fr[funding_col], errors='coerce')
df_fr = df_fr.dropna(subset=[funding_col])

rates = df_fr[funding_col].abs() * 100  # Convert to percentage

print(f'\nFunding Rate statistics ({len(rates)} samples):')
print(f'  Mean: {rates.mean():.4f}%')
print(f'  Median: {rates.median():.4f}%')
print(f'  75th percentile: {rates.quantile(0.75):.4f}%')
print(f'  90th percentile: {rates.quantile(0.90):.4f}%')
print(f'  95th percentile: {rates.quantile(0.95):.4f}%')
print(f'  99th percentile: {rates.quantile(0.99):.4f}%')
print(f'  Max: {rates.max():.4f}%')

print(f'\n  Current bot threshold: 0.01% (0.0001)')
exceeds_fr = sum(1 for r in rates if r >= 0.01)
print(f'  Times exceeded: {exceeds_fr} / {len(rates)} ({exceeds_fr/len(rates)*100:.2f}%)')

print(f'\n  RECOMMENDED THRESHOLDS:')
print(f'    Conservative (95th percentile): {rates.quantile(0.95):.4f}%')
print(f'    Moderate (90th percentile): {rates.quantile(0.90):.4f}%')
print(f'    Aggressive (75th percentile): {rates.quantile(0.75):.4f}%')

print('\n' + '='*60)
