#!/usr/bin/env python3
from binance.client import Client
import json

config = json.load(open('/home/ubuntu/trading_bot/credentials_multi_exchange.json'))['binance']
client = Client(config['api_key'], config['api_secret'], testnet=config['testnet'])

# Get all open orders
orders = client.futures_get_open_orders(symbol='BTCUSDT')

print("=" * 80)
print(f"TOTAL OPEN ORDERS: {len(orders)}")
print("=" * 80)

if len(orders) > 0:
    for i, order in enumerate(orders[:20], 1):  # Show first 20
        print(f"\n{i}. {order['side']} {order['type']}")
        print(f"   Price: ${float(order['price']):,.2f}")
        print(f"   Quantity: {float(order['origQty'])}")
        print(f"   Status: {order['status']}")
        print(f"   Order ID: {order['orderId']}")
    
    if len(orders) > 20:
        print(f"\n... and {len(orders) - 20} more orders")
else:
    print("\n✅ No open orders")

print("\n" + "=" * 80)
