#!/usr/bin/env python3
from binance_futures_adapter import BinanceFuturesAdapter
from datetime import datetime

adapter = BinanceFuturesAdapter(
    api_key='dIuCO3DHfkmEsk0iLyGIIe9Vjjeeaycu0WHEIjaG5yz1qG1Fdq9pKb4dFBzzKoPI',
    api_secret='iRS1ME5Yq6bv2CytWD0oES38YMYetimNXQ78YaEpNAukWktR4XRYqtq4iKwQYsK7',
    testnet=True
)

print('=' * 60)
print('CURRENT POSITIONS')
print('=' * 60)
positions = adapter.client.futures_position_information(symbol='BTCUSDT')
position_exists = False
for pos in positions:
    amt = float(pos['positionAmt'])
    if abs(amt) > 0.0001:
        position_exists = True
        side = 'LONG' if amt > 0 else 'SHORT'
        entry_price = float(pos['entryPrice'])
        mark_price = float(pos['markPrice'])
        pnl = float(pos['unRealizedProfit'])
        print(f"Position: {pos['symbol']} {side}")
        print(f"  Amount: {abs(amt):.5f} BTC")
        print(f"  Entry Price: ${entry_price:.2f}")
        print(f"  Current Price: ${mark_price:.2f}")
        print(f"  Unrealized PnL: ${pnl:.2f}")
        leverage = pos.get('leverage', 'N/A')
        print(f"  Leverage: {leverage}x")
        print()

if not position_exists:
    print("No active positions\n")

print('=' * 60)
print('OPEN ORDERS (SL/TP)')
print('=' * 60)
orders = adapter.client.futures_get_open_orders(symbol='BTCUSDT')
print(f'Total open orders: {len(orders)}\n')

entry_orders = []
sl_orders = []
tp_orders = []

for order in orders:
    if order['type'] in ['LIMIT', 'MARKET']:
        entry_orders.append(order)
    elif order['type'] == 'STOP_MARKET':
        sl_orders.append(order)
    elif order['type'] == 'TAKE_PROFIT_MARKET':
        tp_orders.append(order)

if entry_orders:
    print('ENTRY ORDERS:')
    for order in entry_orders:
        price = float(order['price']) if order['price'] != '0' else 'MARKET'
        print(f"  {order['side']} {order['origQty']} BTC @ {price}")
    print()

if sl_orders:
    print('STOP-LOSS ORDERS:')
    for order in sl_orders:
        stop_price = float(order['stopPrice'])
        print(f"  {order['side']} {order['origQty']} BTC")
        print(f"    Trigger Price: ${stop_price:.2f}")
        print(f"    → Position closes when price hits ${stop_price:.2f}")
    print()

if tp_orders:
    print('TAKE-PROFIT ORDERS:')
    for order in tp_orders:
        stop_price = float(order['stopPrice'])
        print(f"  {order['side']} {order['origQty']} BTC")
        print(f"    Trigger Price: ${stop_price:.2f}")
        print(f"    → Position closes when price hits ${stop_price:.2f}")
    print()

print('=' * 60)
print('TRADINGVIEW SIGNAL STATUS')
print('=' * 60)

import os
queue_file = '/home/ubuntu/tradingview-webhook-mvp/tradingview_signals_queue.jsonl'
if os.path.exists(queue_file):
    with open(queue_file, 'r') as f:
        lines = f.readlines()
    print(f"Signals in queue: {len(lines)}")
    if lines:
        import json
        print("\nLast 3 signals:")
        for line in lines[-3:]:
            signal = json.loads(line)
            print(f"  {signal.get('timestamp', 'N/A')} - {signal.get('action', 'N/A')} - Confidence: {signal.get('confidence', 'N/A')}")
else:
    print("No signal queue file found")

print()
