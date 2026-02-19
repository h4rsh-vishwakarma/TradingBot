#!/usr/bin/env python3
"""Deep validation of calculations"""
import json
import gzip

print("=== CALCULATION VALIDATION ===\n")

# Get latest health snapshot
with gzip.open('/home/ubuntu/trading_bot/logs/events/health_20251220.jsonl.gz', 'rt') as f:
    lines = f.readlines()
    health = json.loads(lines[-1])

print("1. EQUITY CALCULATION:")
print(f"   equity_usd = {health['equity_usd']}")
print(f"   pnl_realized_usd = {health['pnl_realized_usd']}")
print(f"   pnl_unrealized_usd = {health['pnl_unrealized_usd']}")

initial_balance = 1000.0
calculated_equity = initial_balance + health['pnl_realized_usd'] + health['pnl_unrealized_usd']
print(f"   Initial balance = {initial_balance}")
print(f"   Calculated equity = {initial_balance} + {health['pnl_realized_usd']} + {health['pnl_unrealized_usd']}")
print(f"   Calculated equity = {calculated_equity}")
print(f"   Reported equity = {health['equity_usd']}")

if abs(calculated_equity - health['equity_usd']) < 0.01:
    print("   ✅ Equity calculation CORRECT")
else:
    print(f"   ❌ ERROR: Equity mismatch! Diff = {abs(calculated_equity - health['equity_usd'])}")

# Check positions
print(f"\n2. POSITION TRACKING:")
print(f"   positions_open = {health['positions_open']}")
print(f"   risk_used_pct = {health['risk_used_pct']}")

# Get all fills to count positions
with gzip.open('/home/ubuntu/trading_bot/logs/events/fill_20251220.jsonl.gz', 'rt') as f:
    fills = [json.loads(line) for line in f.readlines()]

with gzip.open('/home/ubuntu/trading_bot/logs/events/order_20251220.jsonl.gz', 'rt') as f:
    orders = [json.loads(line) for line in f.readlines()]

print(f"   Total fills: {len(fills)}")
print(f"   Total orders: {len(orders)}")

# Check signal strength calculations
print(f"\n3. SIGNAL STRENGTH VALIDATION:")
with gzip.open('/home/ubuntu/trading_bot/logs/events/decision_20251220.jsonl.gz', 'rt') as f:
    decisions = [json.loads(line) for line in f.readlines()]
    
trade_decisions = [d for d in decisions if d['action'] == 'PLACE']
print(f"   Total trade decisions: {len(trade_decisions)}")

if trade_decisions:
    last_trade = trade_decisions[-1]
    print(f"\n   Last trade:")
    print(f"   S_long = {last_trade['S_long']}")
    print(f"   S_short = {last_trade['S_short']}")
    print(f"   votes = {last_trade['votes']}")
    
    # Validate signal strength calculation
    votes_map = last_trade['votes']
    long_count = sum(1 for v in votes_map.values() if v == 'LONG')
    short_count = sum(1 for v in votes_map.values() if v == 'SHORT')
    total_votes = len([v for v in votes_map.values() if v != 'NONE'])
    
    if total_votes > 0:
        expected_s_long = long_count / 3.0
        expected_s_short = short_count / 3.0
        
        print(f"\n   Validation:")
        print(f"   Long votes: {long_count}/3 = {expected_s_long}")
        print(f"   Short votes: {short_count}/3 = {expected_s_short}")
        
        if abs(expected_s_long - last_trade['S_long']) < 0.01:
            print(f"   ✅ S_long calculation CORRECT")
        else:
            print(f"   ❌ S_long ERROR: expected {expected_s_long}, got {last_trade['S_long']}")
            
        if abs(expected_s_short - last_trade['S_short']) < 0.01:
            print(f"   ✅ S_short calculation CORRECT")
        else:
            print(f"   ❌ S_short ERROR: expected {expected_s_short}, got {last_trade['S_short']}")

# Check pred_bps calculation
print(f"\n4. PREDICTION BPS VALIDATION:")
with gzip.open('/home/ubuntu/trading_bot/logs/events/prediction_20251220.jsonl.gz', 'rt') as f:
    predictions = [json.loads(line) for line in f.readlines()]

print(f"   Total predictions: {len(predictions)}")
errors = []
for i, pred in enumerate(predictions[-5:]):
    expected_bps = pred['pred_raw'] * 50
    if abs(expected_bps - pred['pred_bps']) > 0.01:
        errors.append((i, pred['pred_raw'], pred['pred_bps'], expected_bps))

if errors:
    print(f"   ❌ Found {len(errors)} prediction BPS errors:")
    for idx, raw, reported, expected in errors:
        print(f"      Sample {idx}: raw={raw}, reported_bps={reported}, expected_bps={expected}")
else:
    print(f"   ✅ All prediction BPS calculations CORRECT")

print("\n=== VALIDATION COMPLETE ===")
