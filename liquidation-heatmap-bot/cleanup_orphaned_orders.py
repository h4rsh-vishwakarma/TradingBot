#!/usr/bin/env python3
"""
Cleanup script to cancel orphaned SL/TP orders.
Run this via cron every 5 minutes.
"""
from binance.client import Client
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def cleanup_orphaned_orders():
    config = json.load(open('/home/ubuntu/trading_bot/credentials_multi_exchange.json'))['binance']
    client = Client(config['api_key'], config['api_secret'], testnet=config['testnet'])
    
    # Get current positions
    positions = client.futures_position_information(symbol='BTCUSDT')
    active_positions = [p for p in positions if float(p['positionAmt']) != 0]
    
    # Get all open orders
    orders = client.futures_get_open_orders(symbol='BTCUSDT')
    
    if len(orders) == 0:
        logger.info("✅ No orphaned orders")
        return
    
    # If we have orders but no position, they're all orphaned
    if len(active_positions) == 0:
        logger.info(f"⚠️  Found {len(orders)} orphaned orders with no position - cancelling all")
        for order in orders:
            try:
                client.futures_cancel_order(symbol='BTCUSDT', orderId=order['orderId'])
                logger.info(f"  Cancelled {order['type']} (ID: {order['orderId']})")
            except Exception as e:
                logger.warning(f"  Failed to cancel {order['orderId']}: {e}")
        return
    
    # If we have 1 position but many orders (>4), clean up extras
    # Normal: 1 position should have max 2 orders (1 SL + 1 TP)
    expected_max_orders = len(active_positions) * 2
    
    if len(orders) > expected_max_orders:
        excess = len(orders) - expected_max_orders
        logger.info(f"⚠️  Found {len(orders)} orders for {len(active_positions)} position(s) - {excess} excess orders")
        logger.info(f"  Keeping only newest {expected_max_orders} orders, cancelling rest")
        
        # Sort by orderId (newer = higher ID), keep newest N, cancel rest
        orders_sorted = sorted(orders, key=lambda x: x['orderId'], reverse=True)
        orders_to_cancel = orders_sorted[expected_max_orders:]
        
        for order in orders_to_cancel:
            try:
                client.futures_cancel_order(symbol='BTCUSDT', orderId=order['orderId'])
                logger.info(f"  Cancelled old {order['type']} (ID: {order['orderId']})")
            except Exception as e:
                logger.warning(f"  Failed to cancel {order['orderId']}: {e}")
    else:
        logger.info(f"✅ Order count normal: {len(orders)} orders for {len(active_positions)} position(s)")

if __name__ == "__main__":
    try:
        cleanup_orphaned_orders()
    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        import traceback
        traceback.print_exc()
