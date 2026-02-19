#!/usr/bin/env python3
from binance.client import Client
import json

config = json.load(open('/home/ubuntu/trading_bot/credentials_multi_exchange.json'))['binance']
client = Client(config['api_key'], config['api_secret'], testnet=True)

# Get all orders
orders = client.futures_get_open_orders(symbol='BTCUSDT')

# Get current position
pos = client.futures_position_information(symbol='BTCUSDT')
active_pos = [p for p in pos if float(p['positionAmt']) != 0][0]
position_side = "LONG" if float(active_pos['positionAmt']) > 0 else "SHORT"

print(f"Current position: {position_side}")
print(f"Total orders: {len(orders)}")

# Cancel opposite direction orders
canceled = 0
for o in orders:
    order_side = o['side']
    order_type = o['type']
    
    # For LONG position, cancel BUY stop/TP orders (those are for SHORT)
    # For SHORT position, cancel SELL stop/TP orders (those are for LONG)
    should_cancel = False
    
    if position_side == "LONG" and order_side == "BUY":
        should_cancel = True
        print(f"Canceling SHORT order: {o['orderId']} ({order_type} {order_side})")
    elif position_side == "SHORT" and order_side == "SELL":
        should_cancel = True
        print(f"Canceling LONG order: {o['orderId']} ({order_type} {order_side})")
    
    if should_cancel:
        try:
            client.futures_cancel_order(symbol='BTCUSDT', orderId=o['orderId'])
            canceled += 1
            print(f"  ✅ Canceled")
        except Exception as e:
            print(f"  ❌ Failed: {e}")

print(f"\nCanceled {canceled} opposite direction orders")
print(f"Remaining orders: {len(client.futures_get_open_orders(symbol='BTCUSDT'))}")
