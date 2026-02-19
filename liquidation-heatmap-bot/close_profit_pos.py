import ccxt
import os
from dotenv import load_dotenv

load_dotenv()

exchange = ccxt.binance({
    'apiKey': os.getenv('BINANCE_API_KEY'),
    'secret': os.getenv('BINANCE_API_SECRET'),
    'options': {'defaultType': 'future'}
})

print('CLOSING PROFITABLE POSITIONS')
print('=' * 70)

positions = exchange.fetch_positions(['SOL/USDT:USDT', 'ETH/USDT:USDT'])

for pos in positions:
    symbol = pos['symbol']
    contracts = float(pos['contracts'])
    pnl = float(pos.get('unrealizedPnl', 0))
    
    if contracts != 0 and pnl > 0:
        side = pos['side']
        entry = float(pos.get('entryPrice', 0))
        mark = float(pos.get('markPrice', 0))
        
        print('')
        print(f'Position: {symbol} {side.upper()}')
        print(f'  Size: {contracts}')
        print(f'  Entry: ')
        print(f'  Mark: ')
        print(f'  Unrealized PnL: ')
        
        close_side = 'sell' if side == 'long' else 'buy'
        
        try:
            print(f'  Closing with {close_side.upper()} market order...')
            
            order = exchange.create_order(
                symbol=symbol,
                type='market',
                side=close_side,
                amount=abs(contracts),
                params={'reduceOnly': True}
            )
            
            order_id = order.get('id', 'N/A')
            print(f'  SUCCESS - Position closed!')
            print(f'  Order ID: {order_id}')
            
        except Exception as e:
            print(f'  ERROR: {e}')
    elif contracts != 0:
        side = pos['side']
        print(f'Skipping {symbol} {side.upper()} - PnL:  (not profitable)')

print('')
print('=' * 70)
print('DONE')
