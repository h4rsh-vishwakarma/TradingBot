#!/usr/bin/env python3
from binance_futures_adapter import BinanceFuturesAdapter

adapter = BinanceFuturesAdapter(
    api_key='dIuCO3DHfkmEsk0iLyGIIe9Vjjeeaycu0WHEIjaG5yz1qG1Fdq9pKb4dFBzzKoPI',
    api_secret='iRS1ME5Yq6bv2CytWD0oES38YMYetimNXQ78YaEpNAukWktR4XRYqtq4iKwQYsK7',
    testnet=True
)

print('=' * 70)
print('ALL POSITIONS ACROSS ALL SYMBOLS')
print('=' * 70)

positions = adapter.client.futures_position_information()
position_count = 0

for pos in positions:
    amt = float(pos['positionAmt'])
    if abs(amt) > 0.0001:
        position_count += 1
        side = 'LONG' if amt > 0 else 'SHORT'
        print(f"\nPosition #{position_count}: {pos['symbol']} {side}")
        print(f"  Amount: {abs(amt):.5f}")
        print(f"  Entry Price: ${float(pos['entryPrice']):.2f}")
        print(f"  Mark Price: ${float(pos['markPrice']):.2f}")
        print(f"  Unrealized PnL: ${float(pos['unRealizedProfit']):.2f}")

if position_count == 0:
    print("\nNo active positions found")
else:
    print(f"\n{'=' * 70}")
    print(f"TOTAL ACTIVE POSITIONS: {position_count}")
    print('=' * 70)

# Check orders for BTCUSDT
print("\n\n" + '=' * 70)
print('BTCUSDT OPEN ORDERS')
print('=' * 70)

orders = adapter.client.futures_get_open_orders(symbol='BTCUSDT')
entry_count = len([o for o in orders if o['type'] in ['LIMIT', 'MARKET']])
sl_count = len([o for o in orders if o['type'] == 'STOP_MARKET'])
tp_count = len([o for o in orders if o['type'] == 'TAKE_PROFIT_MARKET'])

print(f"\nEntry orders: {entry_count}")
print(f"Stop-loss orders: {sl_count}")
print(f"Take-profit orders: {tp_count}")
print(f"Total: {len(orders)}")
