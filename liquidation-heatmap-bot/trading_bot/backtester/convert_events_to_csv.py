"""
Convert trading bot event logs to TradingView-compatible CSV format.

Reads decision.jsonl events and creates a CSV with OHLCV + signals
suitable for backtesting.
"""

import json
import pandas as pd
from datetime import timezone
import sys

def convert_events_to_csv(decision_file, output_csv, price_source='binance'):
    """
    Convert decision events to TradingView CSV format.
    
    Args:
        decision_file: Path to decision.jsonl file
        output_csv: Path to output CSV file
        price_source: Source for OHLC data (currently uses close price from decisions)
    """
    print(f"Reading decisions from {decision_file}...")
    
    decisions = []
    with open(decision_file, 'r') as f:
        for line in f:
            try:
                event = json.loads(line)
                if event.get('event') == 'decision':
                    decisions.append(event)
            except json.JSONDecodeError:
                continue
    
    print(f"Loaded {len(decisions)} decision events")
    
    if len(decisions) == 0:
        print("No decisions found!")
        return
    
    # Convert to DataFrame
    rows = []
    for dec in decisions:
        context = dec.get('context', {})
        price = context.get('price') or dec.get('price')
        
        if price is None:
            continue
        
        # Approximate OHLC from close price (??0.1%)
        close = float(price)
        high = close * 1.001
        low = close * 0.999
        open_price = close
        
        # Extract signals
        signal_dir = dec.get('signal_dir', 'NONE')
        long_sig = 1 if signal_dir == 'LONG' else 0
        short_sig = 1 if signal_dir == 'SHORT' else 0
        
        # Parse timestamp
        ts = pd.to_datetime(dec['ts'])
        if ts.tz is None:
            ts = ts.tz_localize(timezone.utc)
        
        rows.append({
            'timestamp': ts,
            'open': open_price,
            'high': high,
            'low': low,
            'close': close,
            'volume': 1000.0,  # Placeholder
            'longSig': long_sig,
            'shortSig': short_sig
        })
    
    df = pd.DataFrame(rows)
    df = df.sort_values('timestamp')
    df = df.drop_duplicates(subset=['timestamp'], keep='first')
    
    # Convert signals to state changes only (critical for backtester)
    # The backtester enters when signal changes from 0 to 1/-1
    # So we need to output 0 for "hold current state" and 1/-1 only on transitions
    
    # Compute unified signal (-1=short, 0=none, 1=long)
    df['signal'] = 0
    df.loc[df['longSig'] == 1, 'signal'] = 1
    df.loc[df['shortSig'] == 1, 'signal'] = -1
    
    # Find actual signal changes (state transitions)
    df['signal_prev'] = df['signal'].shift(1, fill_value=0)
    df['signal_change'] = (df['signal'] != df['signal_prev'])
    
    # Zero out non-transition bars (backtester needs 0 except at entry points)
    df['longSig_orig'] = df['longSig']
    df['shortSig_orig'] = df['shortSig']
    
    df['longSig'] = 0
    df['shortSig'] = 0
    
    # Only set signal on actual transitions
    df.loc[(df['signal_change']) & (df['signal'] == 1), 'longSig'] = 1
    df.loc[(df['signal_change']) & (df['signal'] == -1), 'shortSig'] = 1
    
    # Drop helper columns
    df = df.drop(columns=['signal', 'signal_prev', 'signal_change', 'longSig_orig', 'shortSig_orig'])
    
    # Save to CSV
    df.to_csv(output_csv, index=False)
    
    print(f"\n??? Converted {len(df)} rows to {output_csv}")
    print(f"Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    print(f"Long signals (transitions): {df['longSig'].sum()}")
    print(f"Short signals (transitions): {df['shortSig'].sum()}")
    print(f"Total signal transitions: {df['longSig'].sum() + df['shortSig'].sum()}")

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python convert_events_to_csv.py <decision.jsonl> <output.csv>")
        sys.exit(1)
    
    convert_events_to_csv(sys.argv[1], sys.argv[2])
