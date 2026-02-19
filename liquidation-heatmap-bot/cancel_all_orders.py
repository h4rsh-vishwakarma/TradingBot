#!/usr/bin/env python3
from binance.client import Client
import json

config = json.load(open('/home/ubuntu/trading_bot/credentials_multi_exchange.json'))['binance']
client = Client(config['api_key'], config['api_secret'], testnet=config['testnet'])

# Get current position
positions = client.futures_position_information(symbol='BTCUSDT')
active_pos = [p for p in positions if float(p['positionAmt']) != 0]

print("=" * 80)
if len(active_pos) > 0:
    pos = active_pos[0]
    amt = float(pos['positionAmt'])
    print(f"CURRENT POSITION: {'LONG' if amt > 0 else 'SHORT'} {abs(amt):.4f} BTC")
else:
    print("NO ACTIVE POSITION")
print("=" * 80)

# Get all open orders
orders = client.futures_get_open_orders(symbol='BTCUSDT')
print(f"\nFound {len(orders)} open orders")

if len(orders) > 0:
    print("\nCancelling all orphaned SL/TP orders...")
    cancelled = 0
    for order in orders:
        try:
            client.futures_cancel_order(symbol='BTCUSDT', orderId=order['orderId'])
            cancelled += 1
            print(f"  ✅ Cancelled {order['side']} {order['type']} (ID: {order['orderId']})")
        except Exception as e:
            print(f"  ❌ Failed to cancel {order['orderId']}: {str(e)}")
    
    print(f"\n✅ Cancelled {cancelled} orders")
else:
    print("\n✅ No orders to cancel")

print("=" * 80)
