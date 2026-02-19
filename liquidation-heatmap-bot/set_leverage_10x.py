#!/usr/bin/env python3
from binance_futures_adapter import BinanceFuturesAdapter

adapter = BinanceFuturesAdapter(
    api_key='dIuCO3DHfkmEsk0iLyGIIe9Vjjeeaycu0WHEIjaG5yz1qG1Fdq9pKb4dFBzzKoPI',
    api_secret='iRS1ME5Yq6bv2CytWD0oES38YMYetimNXQ78YaEpNAukWktR4XRYqtq4iKwQYsK7',
    testnet=True
)

print('=' * 70)
print('CHANGING BTCUSDT LEVERAGE TO 10X')
print('=' * 70)

# Change leverage to 10x
print('\nChanging leverage...')
result = adapter.client.futures_change_leverage(symbol='BTCUSDT', leverage=10)

print('\nSUCCESS!')
print('Symbol:', result['symbol'])
print('New Leverage:', result['leverage'], 'x')
print('Max Notional:', result.get('maxNotionalValue', 'N/A'))

print('\n' + '=' * 70)
print('DONE')
print('=' * 70)
