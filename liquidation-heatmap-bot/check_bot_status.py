#!/usr/bin/env python3
import sys
sys.path.insert(0, '/home/ubuntu/trading_bot')
from binance.client import Client
import json

config = json.load(open('/home/ubuntu/trading_bot/credentials_multi_exchange.json'))['binance']
client = Client(config['api_key'], config['api_secret'], testnet=config['testnet'])

# Check position
pos = client.futures_position_information(symbol='BTCUSDT')
active_pos = [p for p in pos if float(p['positionAmt']) != 0]

if active_pos:
    p = active_pos[0]
    print(f"Position: {p['positionAmt']} BTC @ ${float(p['entryPrice']):.2f}")
    print(f"Current Price: ${float(p['markPrice']):.2f}")
    print(f"Unrealized PnL: ${float(p['unRealizedProfit']):.2f}")
else:
    print('Position: NONE')

# Check orders
orders = client.futures_get_open_orders(symbol='BTCUSDT')
estimated_pos = max(1, len(orders) // 3) if len(orders) > 0 else 0
print(f"Open Orders: {len(orders)}")
print(f"Estimated Positions: {estimated_pos}/3")

# Check balance
balance = client.futures_account_balance()
usdt = [b for b in balance if b['asset'] == 'USDT'][0]
print(f"Balance: ${float(usdt['balance']):.2f}")
