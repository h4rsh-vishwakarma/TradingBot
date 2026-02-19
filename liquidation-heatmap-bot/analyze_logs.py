#!/usr/bin/env python3
import json
import os
from datetime import datetime

events_dir = '/home/ubuntu/trading_bot/events'

# Count events in each file
print("=" * 70)
print("EVENT EMITTERS SUMMARY")
print("=" * 70)

event_files = [
    'decision.jsonl', 'order.jsonl', 'fill.jsonl', 'bracket_calc.jsonl',
    'veto.jsonl', 'session.jsonl', 'error.jsonl', 'guard.jsonl', 'health.jsonl'
]

for filename in event_files:
    filepath = os.path.join(events_dir, filename)
    if os.path.exists(filepath):
        count = sum(1 for _ in open(filepath))
        size = os.path.getsize(filepath) / (1024 * 1024)  # MB
        print(f"{filename:20} {count:6} events  {size:6.2f} MB")

print("\n" + "=" * 70)
print("FILL EVENTS (Last 10)")
print("=" * 70)

fills = []
with open(os.path.join(events_dir, 'fill.jsonl')) as f:
    for line in f:
        fills.append(json.loads(line))

for f in fills[-10:]:
    ts = f['ts'][:19]
    side = f['side']
    qty = float(f['qty'])
    px = float(f['px'])
    fee = float(f['fee'])
    print(f"{ts} | {side:5} | Qty: {qty:.4f} | Price: ${px:,.2f} | Fee: ${fee:.2f}")

print("\n" + "=" * 70)
print("TRADING STATISTICS")
print("=" * 70)

total_fees = sum(float(f['fee']) for f in fills)
longs = len([f for f in fills if f['side'] == 'LONG'])
shorts = len([f for f in fills if f['side'] == 'SHORT'])

print(f"Total Fills: {len(fills)}")
print(f"LONG fills: {longs}")
print(f"SHORT fills: {shorts}")
print(f"Total Fees Paid: ${total_fees:.2f}")

print("\n" + "=" * 70)
print("RECENT DECISIONS (Last 5)")
print("=" * 70)

decisions = []
with open(os.path.join(events_dir, 'decision.jsonl')) as f:
    for line in f:
        decisions.append(json.loads(line))

for d in decisions[-5:]:
    ts = d['ts'][:19]
    signal = d['signal_dir']
    strength = d['signal_strength']
    action = d['action']
    price = d['context']['price']
    print(f"{ts} | {signal:5} {strength:6} | Action: {action:8} | Price: ${price:,.2f}")

print("\n" + "=" * 70)
print("RECENT ORDERS (Last 5)")
print("=" * 70)

orders = []
with open(os.path.join(events_dir, 'order.jsonl')) as f:
    for line in f:
        orders.append(json.loads(line))

for o in orders[-5:]:
    ts = o['ts'][:19]
    side = o['side']
    order_type = o['type']
    px = float(o['px'])
    qty = float(o['qty'])
    status = o['status']
    print(f"{ts} | {side:4} {order_type:6} | Price: ${px:,.2f} | Qty: {qty:.4f} | Status: {status}")

print("\n" + "=" * 70)
print("SESSION EVENTS (Last 3)")
print("=" * 70)

sessions = []
with open(os.path.join(events_dir, 'session.jsonl')) as f:
    for line in f:
        sessions.append(json.loads(line))

for s in sessions[-3:]:
    ts = s['ts'][:19]
    event = s['event']
    session_id = s['session_id'][:16]
    print(f"{ts} | {event:20} | Session: {session_id}...")

print("\n" + "=" * 70)
print("ERROR EVENTS")
print("=" * 70)

error_count = sum(1 for _ in open(os.path.join(events_dir, 'error.jsonl')))
print(f"Total Errors: {error_count}")
if error_count > 0:
    print("Recent errors:")
    with open(os.path.join(events_dir, 'error.jsonl')) as f:
        errors = [json.loads(line) for line in f]
    for e in errors[-5:]:
        print(f"{e['ts'][:19]} | {e.get('error', 'N/A')}")
else:
    print("✅ No errors recorded")

print("\n" + "=" * 70)
print("VETO EVENTS (Last 5)")
print("=" * 70)

vetos = []
with open(os.path.join(events_dir, 'veto.jsonl')) as f:
    for line in f:
        vetos.append(json.loads(line))

for v in vetos[-5:]:
    ts = v['ts'][:19]
    signal = v.get('signal_dir', 'N/A')
    reason = v.get('veto_reason', v.get('context', {}).get('veto_reasons', ['N/A'])[0] if v.get('context') else 'N/A')
    print(f"{ts} | {signal:5} | Reason: {reason}")
