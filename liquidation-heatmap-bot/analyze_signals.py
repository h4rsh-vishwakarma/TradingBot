#!/usr/bin/env python3
"""Analyze TradingView signals queue."""

import json
from collections import Counter
from datetime import datetime

queue_file = "tradingview_signals_queue.jsonl"

signals = []
with open(queue_file, 'r') as f:
    for line in f:
        signals.append(json.loads(line.strip()))

print("="*70)
print("TRADINGVIEW SIGNALS ANALYSIS")
print("="*70)

# Count by strategy
strategies = Counter(s['strategy_id'] for s in signals)
print("\n📊 Signals by Strategy:")
for strategy, count in strategies.most_common():
    strategy_name = next((s['strategy'] for s in signals if s['strategy_id'] == strategy), strategy)
    print(f"   {strategy_name}")
    print(f"   ({strategy}): {count} signals")

# Count by status
statuses = Counter(s['status'] for s in signals)
print("\n📋 Signals by Status:")
for status, count in statuses.items():
    print(f"   {status}: {count}")

# Count by side
sides = Counter(s['side'] for s in signals)
print("\n📈 Signals by Side:")
for side, count in sides.items():
    print(f"   {side}: {count}")

# Time range
print(f"\n⏰ Time Range:")
print(f"   Oldest: {signals[0]['timestamp']}")
print(f"   Newest: {signals[-1]['timestamp']}")

# Recent signals
print(f"\n🔥 Last 5 Signals:")
for signal in signals[-5:]:
    ts = signal['timestamp'][:19]
    print(f"   {ts} | {signal['side']:5} | {signal['strategy'][:40]:40} | {signal['status']}")

print(f"\n📊 Total: {len(signals)} signals")
print("="*70)
