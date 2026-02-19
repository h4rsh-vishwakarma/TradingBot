import ccxt
import os
from dotenv import load_dotenv

load_dotenv()

exchange = ccxt.binance({
    'apiKey': os.getenv('BINANCE_API_KEY'),
    'secret': os.getenv('BINANCE_API_SECRET'),
    'options': {'defaultType': 'future'}
})

print('=== BINANCE ACCOUNT STATUS ===')
balance = exchange.fetch_balance()
print(f'USDT Balance: \')
print(f'Used Margin: \')
print(f'Total: \')

print('\n=== OPEN POSITIONS ===')
positions = exchange.fetch_positions(['BTC/USDT:USDT'])
open_count = 0
for pos in positions:
    if float(pos['contracts']) != 0:
        open_count += 1
        print(f'Symbol: {pos[" symbol\]}')
 print(f'Side: {pos[\side\]}')
 print(f'Size: {pos[\contracts\]} contracts')
 print(f'Entry Price: \')
 print(f'Unrealized PnL: \')
 print(f'Leverage: {pos.get(\leverage\, \N/A\)}x')

if open_count == 0:
 print('No open positions')

print(f'\nTotal Open Positions: {open_count}/3')

print('\n=== RECENT ORDERS (LAST 5) ===')
try:
 orders = exchange.fetch_orders('BTC/USDT:USDT', limit=5)
 if orders:
 for order in orders[-5:]:
 print(f'{order[\datetime\]} | {order[\side\]} {order[\amount\]} @ \ | Status: {order[\status\]}')
 else:
 print('No recent orders')
except Exception as e:
 print(f'Error fetching orders: {e}')
