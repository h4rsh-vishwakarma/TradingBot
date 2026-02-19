import json
from binance.client import Client

# Load credentials
with open('credentials_multi_exchange.json', 'r') as f:
    creds = json.load(f)

binance_config = creds['binance']
client = Client(
    binance_config['api_key'],
    binance_config['api_secret'],
    testnet=binance_config.get('testnet', False)
)

print('=' * 70)
print('CLOSING PROFITABLE POSITIONS')
print('=' * 70)

# Get all open positions
positions = client.futures_position_information()

closed_count = 0
total_pnl = 0

for pos in positions:
    symbol = pos['symbol']
    amount = float(pos['positionAmt'])
    pnl = float(pos['unRealizedProfit'])
    entry = float(pos['entryPrice'])
    
    # Only process positions with non-zero amount and profit
    if amount != 0 and pnl > 0:
        side = 'LONG' if amount > 0 else 'SHORT'
        
        # Skip BTC - leave it for the liquidation bot
        if symbol == 'BTCUSDT':
            print(f'\nSkipping {symbol} {side} (Reserved for liquidation bot)')
            print(f'  PnL: ')
            continue
        
        print(f'\n{symbol} {side}')
        print(f'  Size: {abs(amount)}')
        print(f'  Entry: ')
        print(f'  Unrealized PnL: ')
        
        close_side = 'SELL' if amount > 0 else 'BUY'
        
        try:
            print(f'  Closing with {close_side} market order...')
            
            order = client.futures_create_order(
                symbol=symbol,
                side=close_side,
                type='MARKET',
                quantity=abs(amount),
                reduceOnly=True
            )
            
            print(f'  SUCCESS - Position closed!')
            print(f'  Order ID: {order[" orderId\]}')
 
 closed_count += 1
 total_pnl += pnl
 
 except Exception as e:
 print(f' ERROR: {e}')

print('\n' + '=' * 70)
print(f'Closed {closed_count} profitable positions')
print(f'Total realized PnL: ')
print('=' * 70)
