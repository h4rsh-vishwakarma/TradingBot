#!/usr/bin/env python3
from binance_futures_adapter import BinanceFuturesAdapter
import json

# Load credentials
with open('credentials_multi_exchange.json', 'r') as f:
    creds = json.load(f)

adapter = BinanceFuturesAdapter(creds['binance']['api_key'], creds['binance']['api_secret'], testnet=True)

# Check position
pos = adapter.client.futures_position_information(symbol='BTCUSDT')
position_amt = float(pos[0]['positionAmt'])
print(f"Position: {position_amt} BTC")

# Check open orders
orders = adapter.client.futures_get_open_orders(symbol='BTCUSDT')
print(f"Open orders: {len(orders)}")

if len(orders) > 0:
    print("\nOpen Orders:")
    for order in orders:
        print(f"  - {order['side']} {order['origQty']} @ {order['price']} (ID: {order['orderId']}, Type: {order['type']})")
