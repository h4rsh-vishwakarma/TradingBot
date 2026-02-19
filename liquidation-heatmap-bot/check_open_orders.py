#!/usr/bin/env python3
"""
Check open orders on Binance to see if stop-loss/take-profit orders exist
"""
import sys
sys.path.append('/home/ubuntu/trading_bot')

from binance_futures_adapter import BinanceFuturesAdapter
import json

def check_orders():
    print("=" * 60)
    print("CHECKING OPEN ORDERS ON BINANCE")
    print("=" * 60)
    
    try:
        with open('/home/ubuntu/trading_bot/credentials_multi_exchange.json', 'r') as f:
            creds = json.load(f)
        
        binance_creds = creds.get('binance', {})
        
        adapter = BinanceFuturesAdapter(
            api_key=binance_creds['api_key'],
            api_secret=binance_creds['api_secret'],
            testnet=binance_creds.get('testnet', True)
        )
        
        print(f"✅ Connected to Binance (testnet={adapter.testnet})\n")
        
        # Get open orders
        try:
            orders = adapter.client.futures_get_open_orders(symbol='BTCUSDT')
            
            if not orders or len(orders) == 0:
                print("⚠️  NO OPEN ORDERS FOUND!")
                print("This means there are NO stop-loss or take-profit orders.")
                print("The position has NO PROTECTION!\n")
                return False
            
            print(f"📋 Found {len(orders)} open order(s):\n")
            
            for i, order in enumerate(orders, 1):
                order_type = order.get('type', 'UNKNOWN')
                side = order.get('side', 'UNKNOWN')
                price = float(order.get('stopPrice', 0)) or float(order.get('price', 0))
                qty = float(order.get('origQty', 0))
                status = order.get('status', 'UNKNOWN')
                order_id = order.get('orderId', 'N/A')
                
                print(f"Order #{i}:")
                print(f"  Type: {order_type}")
                print(f"  Side: {side}")
                print(f"  Price: ${price:,.2f}")
                print(f"  Quantity: {qty:.4f} BTC")
                print(f"  Status: {status}")
                print(f"  Order ID: {order_id}")
                print()
            
            return True
            
        except Exception as e:
            print(f"❌ Error fetching orders: {e}")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    has_orders = check_orders()
    sys.exit(0 if has_orders else 1)
