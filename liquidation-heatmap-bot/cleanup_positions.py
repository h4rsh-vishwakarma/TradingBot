#!/usr/bin/env python3
from binance_futures_adapter import BinanceFuturesAdapter
import json
import time

# Load credentials
with open('credentials_multi_exchange.json', 'r') as f:
    creds = json.load(f)

adapter = BinanceFuturesAdapter(creds['binance']['api_key'], creds['binance']['api_secret'], testnet=True)

print("🧹 EMERGENCY CLEANUP - Canceling all open orders and closing position")
print("=" * 80)

# Cancel all open orders
print("\n1️⃣ Canceling all open orders...")
try:
    result = adapter.client.futures_cancel_all_open_orders(symbol='BTCUSDT')
    print(f"✅ All orders canceled: {result}")
except Exception as e:
    print(f"❌ Error canceling orders: {e}")

time.sleep(2)

# Close the position
print("\n2️⃣ Closing position...")
pos = adapter.client.futures_position_information(symbol='BTCUSDT')
position_amt = float(pos[0]['positionAmt'])

if abs(position_amt) > 0.0001:
    side = 'BUY' if position_amt < 0 else 'SELL'  # Opposite side to close
    qty = abs(position_amt)
    
    print(f"   Position: {position_amt} BTC")
    print(f"   Closing with: {side} {qty} BTC MARKET order")
    
    try:
        close_order = adapter.client.futures_create_order(
            symbol='BTCUSDT',
            side=side,
            type='MARKET',
            quantity=qty
        )
        print(f"✅ Position closed: {close_order['orderId']}")
    except Exception as e:
        print(f"❌ Error closing position: {e}")
else:
    print("✅ No position to close")

print("\n3️⃣ Final status check...")
time.sleep(2)
pos = adapter.client.futures_position_information(symbol='BTCUSDT')
orders = adapter.client.futures_get_open_orders(symbol='BTCUSDT')
print(f"   Position: {float(pos[0]['positionAmt'])} BTC")
print(f"   Open orders: {len(orders)}")
print("\n✅ Cleanup complete!")
