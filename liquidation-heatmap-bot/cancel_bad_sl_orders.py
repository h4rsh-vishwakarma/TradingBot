#!/usr/bin/env python3
"""Cancel stop loss orders that are on wrong side of entry price."""

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

# Get current position
symbol = 'BTCUSDT'
position = client.futures_position_information(symbol=symbol)[0]
position_amt = float(position['positionAmt'])
entry_price = float(position['entryPrice'])

print(f"Current position: {'LONG' if position_amt > 0 else 'SHORT'}")
print(f"Entry price: ${entry_price:,.2f}")
print(f"Position size: {position_amt} BTC")

# Get all orders
orders = client.futures_get_open_orders(symbol=symbol)
print(f"\nTotal orders: {len(orders)}")

# For LONG position, cancel SL orders ABOVE entry
# For SHORT position, cancel SL orders BELOW entry
bad_orders = []
for order in orders:
    order_id = order['orderId']
    order_type = order['type']
    side = order['side']
    stop_price = float(order.get('stopPrice', 0))
    
    # Check if it's a stop loss order
    if 'STOP' in order_type and stop_price > 0:
        # For LONG: SL should be BELOW entry
        if position_amt > 0 and stop_price > entry_price:
            bad_orders.append({
                'id': order_id,
                'type': order_type,
                'side': side,
                'stop_price': stop_price,
                'reason': f'SL ${stop_price:,.2f} is ABOVE entry ${entry_price:,.2f} (should be below for LONG)'
            })
        # For SHORT: SL should be ABOVE entry
        elif position_amt < 0 and stop_price < entry_price:
            bad_orders.append({
                'id': order_id,
                'type': order_type,
                'side': side,
                'stop_price': stop_price,
                'reason': f'SL ${stop_price:,.2f} is BELOW entry ${entry_price:,.2f} (should be above for SHORT)'
            })

if not bad_orders:
    print("\n✅ No incorrectly placed stop loss orders found!")
else:
    print(f"\n❌ Found {len(bad_orders)} incorrectly placed stop loss orders:")
    for order in bad_orders:
        print(f"\nOrder {order['id']} ({order['type']} {order['side']})")
        print(f"  Stop Price: ${order['stop_price']:,.2f}")
        print(f"  Reason: {order['reason']}")
        
        # Cancel the order
        try:
            result = client.futures_cancel_order(symbol=symbol, orderId=order['id'])
            print(f"  ✅ Canceled")
        except Exception as e:
            print(f"  ❌ Failed to cancel: {e}")
    
    print(f"\n✅ Canceled {len(bad_orders)} bad orders")
    
    # Show remaining orders
    remaining = client.futures_get_open_orders(symbol=symbol)
    print(f"Remaining orders: {len(remaining)}")
