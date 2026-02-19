import ccxt
import os
from dotenv import load_dotenv

load_dotenv()

exchange = ccxt.binance({
    'apiKey': os.getenv('BINANCE_API_KEY'),
    'secret': os.getenv('BINANCE_API_SECRET'),
    'options': {'defaultType': 'future'}
})

print('=' * 70)
print('CLOSING PROFITABLE POSITIONS')
print('=' * 70)

# Get current positions
positions = exchange.fetch_positions(['SOL/USDT:USDT', 'ETH/USDT:USDT'])

for pos in positions:
    symbol = pos['symbol']
    contracts = float(pos['contracts'])
    pnl = float(pos.get('unrealizedPnl', 0))
    
    if contracts != 0 and pnl > 0:
        side = pos['side']
        print(f'\n📊 Position: {symbol} {side.upper()}')
        print(f'   Size: {contracts}')
        print(f'   Unrealized PnL:  ✅ PROFIT')
        
        # Determine close side (opposite of position)
        close_side = 'sell' if side == 'long' else 'buy'
        
        try:
            print(f'   Closing with {close_side.upper()} market order...')
            
            # Place market order to close position
            order = exchange.create_order(
                symbol=symbol,
                type='market',
                side=close_side,
                amount=abs(contracts),
                params={'reduceOnly': True}
            )
            
            print(f'   ✅ Position closed successfully!')
            print(f'   Order ID: {order[" id\]}')
 print(f' Realized PnL: ')
 
 except Exception as e:
 print(f' ❌ Error closing position: {str(e)}')
 elif contracts != 0:
 side = pos['side']
 print(f'\n⏭️ Skipping {symbol} {side.upper()} (PnL: - not profitable)')

print('\n' + '=' * 70)
print('OPERATION COMPLETE')
print('=' * 70)
