import pandas as pd
import json
from pathlib import Path

def load_jsonl(p):
    return [json.loads(l) for l in open(p) if l.strip()]

print('=== Generating Canonical Files ===')

# 1. Generate trade_log.csv
try:
    dec = pd.DataFrame(load_jsonl('logs/events/decision.jsonl'))
    ordr = pd.DataFrame(load_jsonl('logs/events/order.jsonl'))
    fills = pd.DataFrame(load_jsonl('logs/events/fill.jsonl'))
    
    dec['ts'] = pd.to_datetime(dec['ts'])
    ordr['ts'] = pd.to_datetime(ordr['ts'])
    fills['ts'] = pd.to_datetime(fills['ts'])
    
    df = fills.merge(ordr[['order_id','decision_id','side']], on='order_id', how='left')
    df = df.merge(dec[['decision_id','ts']], on='decision_id', how='left', suffixes=('_exec','_dec'))
    
    trade_log = pd.DataFrame({
        'decision_time': df['ts_dec'],
        'exec_time': df['ts_exec'],
        'side': df['side'],
        'qty': df['qty'],
        'price': df['px'],
        'pnl_usd': df.get('pnl_close', 0.0),
        'transaction_cost': df.get('fee', 0.0)
    })
    trade_log.to_csv('trade_log.csv', index=False)
    print(f' trade_log.csv: {len(trade_log)} rows')
except Exception as e:
    print(f' trade_log.csv: {e}')

# 2. Generate equity.csv
try:
    h = load_jsonl('logs/events/health.jsonl')
    hd = pd.DataFrame(h)
    hd['ts'] = pd.to_datetime(hd['ts'])
    hd = hd.set_index('ts').sort_index()
    eq = hd[['equity_usd']].rename(columns={'equity_usd':'equity_value'})
    eq = eq.resample('5T').last().ffill().reset_index()
    eq.to_csv('equity.csv', index=False)
    print(f' equity.csv: {len(eq)} rows')
except Exception as e:
    print(f' equity.csv: {e}')

# 3. Generate signals.csv
try:
    if Path('logs/backtests/signals_live.csv').exists():
        s = pd.read_csv('logs/backtests/signals_live.csv', parse_dates=['timestamp'])
        s['ts'] = pd.to_datetime(s['timestamp'])
        out = s.copy()
        out['pred_bps'] = pd.NA
        out['pred_raw'] = s.get('signal_strength', pd.NA)
        out['S_top'] = s.get('S_long', pd.NA)
        out['S_bot'] = s.get('S_short', pd.NA)
        cols = ['ts','pred_bps','pred_raw','S_top','S_bot','spread_bps','est_slip_bps','signal_dir','signal_strength']
        out = out[[c for c in cols if c in out.columns]]
        out.to_csv('signals.csv', index=False)
        print(f' signals.csv: {len(out)} rows')
    else:
        # Create from decision events
        dec = pd.DataFrame(load_jsonl('logs/events/decision.jsonl'))
        dec['ts'] = pd.to_datetime(dec['ts'])
        out = pd.DataFrame({
            'ts': dec['ts'],
            'pred_bps': pd.NA,
            'pred_raw': dec.get('signal_strength', pd.NA),
            'S_top': dec.get('S_long', pd.NA),
            'S_bot': dec.get('S_short', pd.NA),
            'spread_bps': dec.get('spread_bps', pd.NA),
            'est_slip_bps': dec.get('est_slip_bps', pd.NA),
            'signal_dir': dec.get('signal_dir', pd.NA)
        })
        out.to_csv('signals.csv', index=False)
        print(f' signals.csv: {len(out)} rows (from decisions)')
except Exception as e:
    print(f' signals.csv: {e}')

print('=== Complete ===')
