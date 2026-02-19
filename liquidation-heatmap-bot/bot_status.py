#!/usr/bin/env python3
from binance.client import Client
import json
from datetime import datetime

config = json.load(open('/home/ubuntu/trading_bot/credentials_multi_exchange.json'))['binance']
client = Client(config['api_key'], config['api_secret'], testnet=config['testnet'])

print("=" * 80)
print(f"BOT STATUS - {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
print("=" * 80)

# Get positions
positions = client.futures_position_information()
active_positions = [p for p in positions if float(p['positionAmt']) != 0]

print(f"\n📊 ACTIVE POSITIONS: {len(active_positions)}/4")
for pos in active_positions:
    symbol = pos['symbol']
    amt = float(pos['positionAmt'])
    side = 'LONG' if amt > 0 else 'SHORT'
    size = abs(amt)
    entry = float(pos['entryPrice'])
    mark = float(pos['markPrice'])
    pnl = float(pos['unRealizedProfit'])
    
    print(f"  • {symbol}: {side} {size:.4f} @ ${entry:,.2f} | Mark: ${mark:,.2f} | PnL: ${pnl:,.2f}")

# Get open orders
orders = client.futures_get_open_orders()
print(f"\n📋 OPEN ORDERS: {len(orders)}")

# Count by type
sl_orders = [o for o in orders if 'STOP' in o['type']]
tp_orders = [o for o in orders if 'TAKE_PROFIT' in o['type']]

print(f"  • Stop Loss: {len(sl_orders)}")
print(f"  • Take Profit: {len(tp_orders)}")

if len(orders) > 0:
    print(f"\n⚠️  WARNING: {len(orders)} orphaned SL/TP orders detected!")
    print(f"  These should auto-cancel when positions close.")

# Get recent trades
trades = client.futures_account_trades(symbol='BTCUSDT', limit=10)
print(f"\n📈 RECENT TRADES (Last 10):")
for trade in reversed(trades[-5:]):
    side = trade['side']
    price = float(trade['price'])
    qty = float(trade['qty'])
    time_str = datetime.fromtimestamp(trade['time']/1000).strftime('%H:%M:%S')
    print(f"  • {time_str} UTC: {side} {qty:.4f} BTC @ ${price:,.2f}")

print("\n" + "=" * 80)
