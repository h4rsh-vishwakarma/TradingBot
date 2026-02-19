#!/usr/bin/env python3
"""
Cancel all open stop-loss and take-profit orders on Binance testnet
to clear the max stop order limit (code=-4045)
"""
import json
from binance.client import Client
from binance.exceptions import BinanceAPIException

def cancel_all_stop_orders():
    """Cancel all open stop/limit orders on Binance testnet"""
    
    # Load credentials
    with open('credentials_multi_exchange.json', 'r') as f:
        config = json.load(f)
    
    api_key = config['binance']['api_key']
    api_secret = config['binance']['api_secret']
    testnet = config['binance']['testnet']
    
    # Initialize client
    if testnet:
        client = Client(api_key, api_secret, testnet=True)
        client.API_URL = 'https://testnet.binancefuture.com'
        print("✅ Connected to Binance TESTNET")
    else:
        client = Client(api_key, api_secret)
        print("✅ Connected to Binance MAINNET")
    
    symbol = 'BTCUSDT'
    
    try:
        # Get all open orders
        open_orders = client.futures_get_open_orders(symbol=symbol)
        print(f"\n📊 Found {len(open_orders)} open orders for {symbol}")
        
        if not open_orders:
            print("✅ No open orders to cancel")
            return
        
        # Cancel each order
        cancelled_count = 0
        failed_count = 0
        
        for order in open_orders:
            order_id = order['orderId']
            order_type = order['type']
            side = order['side']
            
            try:
                client.futures_cancel_order(symbol=symbol, orderId=order_id)
                cancelled_count += 1
                print(f"✅ Cancelled: {order_type} {side} order {order_id}")
            except BinanceAPIException as e:
                failed_count += 1
                print(f"❌ Failed to cancel order {order_id}: {e}")
        
        print(f"\n📊 Summary:")
        print(f"   Cancelled: {cancelled_count}")
        print(f"   Failed: {failed_count}")
        print(f"   Total: {len(open_orders)}")
        
        # Verify all orders cancelled
        remaining = client.futures_get_open_orders(symbol=symbol)
        if remaining:
            print(f"\n⚠️ Warning: {len(remaining)} orders still open")
        else:
            print(f"\n✅ All orders successfully cancelled!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    cancel_all_stop_orders()
