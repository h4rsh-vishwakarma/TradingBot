#!/usr/bin/env python3
from binance.client import Client
import json

config = json.load(open('/home/ubuntu/trading_bot/credentials_multi_exchange.json'))['binance']
client = Client(config['api_key'], config['api_secret'], testnet=True)

# Get current position
pos = client.futures_position_information(symbol='BTCUSDT')
active_pos = [p for p in pos if float(p['positionAmt']) != 0]

print("=" * 70)
print("CURRENT POSITION")
print("=" * 70)
if active_pos:
    p = active_pos[0]
    entry = float(p['entryPrice'])
    current = float(p['markPrice'])
    size = float(p['positionAmt'])
    unrealized = float(p['unRealizedProfit'])
    
    print(f"Direction: {'LONG' if size > 0 else 'SHORT'}")
    print(f"Size: {abs(size):.4f} BTC")
    print(f"Entry Price: ${entry:,.2f}")
    print(f"Current Price: ${current:,.2f}")
    print(f"Unrealized P&L: ${unrealized:,.2f} ({(unrealized/(abs(size)*entry)*100):.2f}%)")
else:
    print("No active position")
    exit(0)

# Get all open orders
orders = client.futures_get_open_orders(symbol='BTCUSDT')

print(f"\n{'=' * 70}")
print(f"OPEN ORDERS ({len(orders)} total)")
print("=" * 70)

# Separate order types
stop_losses = []
take_profits = []
limit_orders = []

for o in orders:
    order_type = o['type']
    side = o['side']
    
    if order_type == 'STOP_MARKET':
        price = float(o['stopPrice'])
        qty = float(o['origQty'])
        # If position is LONG and order is SELL, it's a stop loss
        # If position is SHORT and order is BUY, it's a stop loss
        if (size > 0 and side == 'SELL') or (size < 0 and side == 'BUY'):
            stop_losses.append({'price': price, 'qty': qty, 'orderId': o['orderId']})
    elif order_type == 'TAKE_PROFIT_MARKET':
        price = float(o['stopPrice'])
        qty = float(o['origQty'])
        take_profits.append({'price': price, 'qty': qty, 'orderId': o['orderId']})
    elif order_type == 'LIMIT':
        price = float(o['price'])
        qty = float(o['origQty'])
        limit_orders.append({'price': price, 'qty': qty, 'side': side, 'orderId': o['orderId']})

if stop_losses:
    print("\n🛑 STOP LOSS ORDERS:")
    for sl in sorted(stop_losses, key=lambda x: x['price']):
        distance = ((sl['price'] - current) / current * 100)
        print(f"   ${sl['price']:>10,.2f} | {abs(distance):>6.2f}% away | Qty: {sl['qty']:.4f}")
        
if take_profits:
    print("\n🎯 TAKE PROFIT ORDERS:")
    for tp in sorted(take_profits, key=lambda x: x['price']):
        distance = ((tp['price'] - current) / current * 100)
        print(f"   ${tp['price']:>10,.2f} | {abs(distance):>+6.2f}% away | Qty: {tp['qty']:.4f}")

if limit_orders:
    print("\n📊 LIMIT ORDERS:")
    for lim in sorted(limit_orders, key=lambda x: x['price']):
        distance = ((lim['price'] - current) / current * 100)
        print(f"   {lim['side']:4} ${lim['price']:>10,.2f} | {distance:>+6.2f}% | Qty: {lim['qty']:.4f}")

# Calculate when position will close
print(f"\n{'=' * 70}")
print("POSITION CLOSE SCENARIOS")
print("=" * 70)

if stop_losses:
    avg_sl = sum(sl['price'] for sl in stop_losses) / len(stop_losses)
    sl_distance = ((avg_sl - current) / current * 100)
    sl_loss = sum((sl['price'] - entry) * sl['qty'] for sl in stop_losses)
    print(f"\n📉 If Stop Loss hits (avg ${avg_sl:,.2f}):")
    print(f"   Price needs to move: {abs(sl_distance):.2f}% {'DOWN' if sl_distance < 0 else 'UP'}")
    print(f"   Estimated Loss: ${sl_loss:,.2f}")
    print(f"   Current price: ${current:,.2f}")
    print(f"   Stop loss at: ${avg_sl:,.2f}")

if take_profits:
    avg_tp = sum(tp['price'] for tp in take_profits) / len(take_profits)
    tp_distance = ((avg_tp - current) / current * 100)
    tp_profit = sum((tp['price'] - entry) * tp['qty'] for tp in take_profits)
    print(f"\n📈 If Take Profit hits (avg ${avg_tp:,.2f}):")
    print(f"   Price needs to move: {abs(tp_distance):.2f}% {'UP' if tp_distance > 0 else 'DOWN'}")
    print(f"   Estimated Profit: ${tp_profit:,.2f}")
    print(f"   Current price: ${current:,.2f}")
    print(f"   Take profit at: ${avg_tp:,.2f}")

print(f"\n{'=' * 70}")
print("⏱️  POSITION WILL CLOSE WHEN:")
print("=" * 70)
print(f"1. Price drops to ~${avg_sl:,.2f} (Stop Loss) - LOSS scenario")
print(f"2. Price rises to ~${avg_tp:,.2f} (Take Profit) - PROFIT scenario")
print(f"3. Manual close via exchange or bot command")
print(f"\nCurrent unrealized P&L: ${unrealized:,.2f}")
