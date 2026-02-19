#!/usr/bin/env python3
import json
import pandas as pd

print('=== CREATING CANONICAL FILES ===\n')

# 1. equity.csv from health.jsonl
print('1. Creating equity.csv...')
equity_data = []
with open('logs/events/health.jsonl', 'r') as f:
    for line in f:
        try:
            event = json.loads(line)
            equity_data.append({
                'timestamp': pd.to_datetime(event['ts']),
                'equity_usd': float(event.get('equity_usd', 0.0)),
                'pnl_realized_usd': float(event.get('pnl_realized_usd', 0.0))
            })
        except:
            continue

df_equity = pd.DataFrame(equity_data).sort_values('timestamp')
df_equity.set_index('timestamp', inplace=True)
df_resampled = df_equity.resample('5T').last().ffill()
df_resampled.to_csv('equity.csv')

total = len(df_resampled)
non_zero = (df_resampled['equity_usd'] > 0).sum()
eq_min = df_resampled['equity_usd'].min()
eq_max = df_resampled['equity_usd'].max()
eq_latest = df_resampled['equity_usd'].iloc[-1]

print(f'   Rows: {total} (5-min resampled)')
print(f'   Non-zero equity: {non_zero} rows')
print(f'   Range: {eq_min:.2f} to {eq_max:.2f}')
print(f'   Latest: {eq_latest:.2f}')

# 2. signals.csv from decision metadata
print('\n2. Creating signals.csv...')
df_signals = pd.read_csv('logs/backtests/signals_live.csv')

# Just copy signals as-is since it already has the right format
canonical_signals = df_signals.copy()
canonical_signals.to_csv('signals.csv', index=False)

print(f'   Rows: {len(canonical_signals)}')
print('    signals.csv created')

print('\n=== CANONICAL FILES CREATION COMPLETE ===')
