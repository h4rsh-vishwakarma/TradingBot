import json
from datetime import datetime
from pathlib import Path

# Read health events for current session
health_file = Path('logs/events/health.jsonl')
run_id = '7102dddc-5071-444c-998e-9c6045abec9b'

equity_data = []
with open(health_file, 'r') as f:
    for line in f:
        try:
            evt = json.loads(line.strip())
            if evt.get('run_id') == run_id:
                ts = evt.get('ts', '')
                equity = evt.get('equity_usd', 1000.0)
                if ts:
                    equity_data.append((ts, equity))
        except Exception as e:
            pass

# Write equity.csv
with open('equity_fresh_live.csv', 'w') as f:
    f.write('ts,equity_value\n')
    for ts, eq in equity_data:
        f.write(f'{ts},{eq}\n')

print(f'Generated equity_fresh_live.csv with {len(equity_data)} entries')
print(f'Date range: {equity_data[0][0] if equity_data else " N/A\} to {equity_data[-1][0] if equity_data else \N/A\}')
print(f'Equity: -> ')
