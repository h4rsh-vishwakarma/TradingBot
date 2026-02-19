#!/usr/bin/env python3
import json
from binance.client import Client
from datetime import datetime

# Load credentials
with open('/home/ubuntu/tradingview-webhook-mvp/trading_bot/credentials.json') as f:
    creds = json.load(f)

client = Client(creds['api_key'], creds['api_secret'], testnet=True)

print("\n" + "="*80)
print("🤖 TRADING BOT STATUS - " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
print("="*80)

# Get balance
balance = client.futures_account_balance()
usdt = [b for b in balance if b['asset'] == 'USDT'][0]
print(f"\n💰 ACCOUNT BALANCE: ${float(usdt['balance']):,.2f} USDT")
print(f"   Available: ${float(usdt['availableBalance']):,.2f}")
print(f"   Cross Wallet: ${float(usdt['crossWalletBalance']):,.2f}")

# Get positions
positions = client.futures_position_information()
active = [p for p in positions if float(p['positionAmt']) != 0]
print(f"\n📊 ACTIVE POSITIONS: {len(active)}/50")
for pos in active:
    amt = float(pos['positionAmt'])
    side = "LONG" if amt > 0 else "SHORT"
    pnl = float(pos['unRealizedProfit'])
    entry = float(pos['entryPrice'])
    mark = float(pos['markPrice'])
    pnl_pct = (pnl / (abs(amt) * entry)) * 100 if entry > 0 else 0
    print(f"   {pos['symbol']:10s} {side:5s} {abs(amt):8.4f} @ ${entry:,.2f} | Mark: ${mark:,.2f} | PnL: ${pnl:+,.2f} ({pnl_pct:+.2f}%)")

# Get open orders
orders = client.futures_get_open_orders()
print(f"\n📋 OPEN ORDERS: {len(orders)}")
for order in orders[:5]:
    print(f"   {order['symbol']} {order['side']} {order['origQty']} @ ${order['price']}")

# Get recent trades
try:
    trades = client.futures_account_trades(symbol='BTCUSDT', limit=5)
    print(f"\n📈 RECENT BTCUSDT TRADES: {len(trades)}")
    for t in trades:
        dt = datetime.fromtimestamp(int(t['time'])/1000).strftime("%H:%M:%S")
        pnl = float(t['realizedPnl'])
        print(f"   {dt} {t['side']:4s} {t['qty']:8s} @ ${float(t['price']):,.2f} | PnL: ${pnl:+,.4f}")
except Exception as e:
    print(f"   Error: {e}")

print("\n" + "="*80)
