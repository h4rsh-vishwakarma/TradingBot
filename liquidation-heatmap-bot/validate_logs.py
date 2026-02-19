#!/usr/bin/env python3
"""Validate log integrity and calculations"""
import json
import gzip
import sys

print("=== VALIDATING EVENT LOGS ===\n")

# Check predictions
print("1. PREDICTION VALUES:")
with gzip.open('/home/ubuntu/trading_bot/logs/events/prediction_20251220.jsonl.gz', 'rt') as f:
    lines = f.readlines()
    print(f"   Total predictions: {len(lines)}")
    
    # Sample last 3
    for line in lines[-3:]:
        p = json.loads(line)
        print(f"   - pred_bps={p['pred_bps']}, confidence={p['confidence']}, quality={p.get('quality_score', 'N/A')}")
        
        # Validate pred_bps calculation
        if abs(p['pred_raw'] * 50 - p['pred_bps']) > 0.01:
            print(f"   ⚠️ ERROR: pred_bps mismatch! raw={p['pred_raw']}, bps={p['pred_bps']}, expected={p['pred_raw']*50}")

# Check decisions
print("\n2. DECISION VALUES:")
with gzip.open('/home/ubuntu/trading_bot/logs/events/decision_20251220.jsonl.gz', 'rt') as f:
    lines = f.readlines()
    print(f"   Total decisions: {len(lines)}")
    
    trades = [json.loads(l) for l in lines if 'PLACE' in l]
    print(f"   Trades (PLACE): {len(trades)}")
    no_trades = [json.loads(l) for l in lines if 'NO_TRADE' in l]
    print(f"   No trades: {len(no_trades)}")
    
    if trades:
        print(f"\n   Last trade decision:")
        t = trades[-1]
        print(f"   - signal_dir={t['signal_dir']}, strength={t['signal_strength']}")
        print(f"   - S_long={t['S_long']}, S_short={t['S_short']}")
        print(f"   - votes={t['votes']}")

# Check fills
print("\n3. FILL VALUES (PnL):")
with gzip.open('/home/ubuntu/trading_bot/logs/events/fill_20251220.jsonl.gz', 'rt') as f:
    lines = f.readlines()
    print(f"   Total fills: {len(lines)}")
    
    for line in lines[:5]:
        fill = json.loads(line)
        print(f"   - px={fill['px']}, qty={fill['qty']}, pnl_open={fill['pnl_open']}, pnl_close={fill['pnl_close']}")
        print(f"     slippage_bps={fill.get('slippage_bps', 'N/A')}")

# Check health snapshots
print("\n4. HEALTH VALUES:")
with gzip.open('/home/ubuntu/trading_bot/logs/events/health_20251220.jsonl.gz', 'rt') as f:
    lines = f.readlines()
    print(f"   Total health events: {len(lines)}")
    
    last_health = json.loads(lines[-1])
    print(f"   Last snapshot:")
    print(f"   - equity_usd={last_health.get('equity_usd', 'N/A')}")
    print(f"   - pnl_realized_usd={last_health.get('pnl_realized_usd', 'N/A')}")
    print(f"   - pnl_unrealized_usd={last_health.get('pnl_unrealized_usd', 'N/A')}")
    print(f"   - positions_open={last_health.get('positions_open', 'N/A')}")
    print(f"   - risk_used_pct={last_health.get('risk_used_pct', 'N/A')}")

print("\n=== VALIDATION COMPLETE ===")
