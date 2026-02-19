"""
Order Monitor - Tracks order fills and syncs virtual position state
Prevents virtual state drift when SL/TP orders are filled
"""

from exchange.binance_client import BinanceClient
from utils.logger import setup_logger
from utils.health_checker import get_health_checker
import json
from datetime import datetime

logger = setup_logger('order_monitor')

class OrderMonitor:
    """Monitor orders and sync virtual positions when SL/TP fills"""
    
    def __init__(self, strategy_name='multi_strategy'):
        self.client = BinanceClient()
        self.strategy_name = strategy_name
        self.health_checker = get_health_checker(strategy_name)
        logger.info("📊 Order monitor initialized")
    
    def check_order_status(self, symbol, order_id):
        """Check if an order has been filled"""
        try:
            order = self.client.futures_get_order(symbol=symbol, orderId=order_id)
            status = order['status']
            
            return {
                'orderId': order_id,
                'status': status,
                'filled': status in ['FILLED', 'PARTIALLY_FILLED'],
                'executedQty': float(order['executedQty']),
                'avgPrice': float(order['avgPrice']) if order['avgPrice'] else 0
            }
        except Exception as e:
            logger.error(f"❌ Failed to check order {order_id} status: {e}")
            return None
    
    def check_position_orders(self, position_data, storage_path):
        """
        Check if SL/TP orders for a position have been filled
        Returns: (position_closed, exit_type, exit_price, pnl)
        """
        try:
            symbol = position_data.get('symbol')
            entry_order_id = position_data.get('entry_order_id')
            sl_order_id = position_data.get('sl_order_id')
            tp_order_id = position_data.get('tp_order_id')
            
            if not symbol:
                return (False, None, None, None)
            
            # Check SL order
            if sl_order_id:
                sl_status = self.check_order_status(symbol, sl_order_id)
                if sl_status and sl_status['filled']:
                    exit_price = sl_status['avgPrice']
                    pnl = self._calculate_pnl(position_data, exit_price)
                    logger.warning(f"🛑 STOP-LOSS FILLED: {symbol} @ ${exit_price:.2f} | PnL: ${pnl:.2f}")
                    
                    # Increment orders_filled counter
                    self.health_checker.increment_orders_filled()
                    
                    return (True, 'stop_loss', exit_price, pnl)
            
            # Check TP order
            if tp_order_id:
                tp_status = self.check_order_status(symbol, tp_order_id)
                if tp_status and tp_status['filled']:
                    exit_price = tp_status['avgPrice']
                    pnl = self._calculate_pnl(position_data, exit_price)
                    logger.info(f"🎯 TAKE-PROFIT FILLED: {symbol} @ ${exit_price:.2f} | PnL: ${pnl:.2f}")
                    
                    # Increment orders_filled counter
                    self.health_checker.increment_orders_filled()
                    
                    return (True, 'take_profit', exit_price, pnl)
            
            return (False, None, None, None)
            
        except Exception as e:
            logger.error(f"❌ Failed to check position orders: {e}")
            return (False, None, None, None)
    
    def _calculate_pnl(self, position_data, exit_price):
        """Calculate PnL for a closed position"""
        try:
            entry_price = float(position_data.get('entry_price', 0))
            position_size = float(position_data.get('position_size', 0))
            side = position_data.get('side', 'LONG').upper()
            
            if side == 'LONG':
                pnl = (exit_price - entry_price) * position_size
            else:  # SHORT
                pnl = (entry_price - exit_price) * position_size
            
            return pnl
        except Exception as e:
            logger.error(f"❌ Failed to calculate PnL: {e}")
            return 0.0
    
    def update_position_closed(self, position_id, storage_path, exit_type, exit_price, pnl):
        """Update virtual position to closed state"""
        try:
            positions = []
            updated = False
            
            # Read all positions
            with open(storage_path, 'r') as f:
                for line in f:
                    pos = json.loads(line)
                    if pos['position_id'] == position_id and pos['status'] == 'open':
                        # Update to closed
                        pos['status'] = 'closed'
                        pos['closed_at'] = datetime.utcnow().isoformat()
                        pos['close_price'] = str(exit_price)
                        pos['exit_type'] = exit_type
                        pos['pnl'] = str(round(pnl, 2))
                        updated = True
                        logger.info(f"✅ Updated position {position_id} to CLOSED")
                        logger.info(f"   Exit: {exit_type} @ ${exit_price:.2f}")
                        logger.info(f"   PnL: ${pnl:.2f}")
                    positions.append(pos)
            
            # Write back all positions
            if updated:
                with open(storage_path, 'w') as f:
                    for pos in positions:
                        f.write(json.dumps(pos) + '\n')
                
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"❌ Failed to update position {position_id}: {e}")
            return False
    
    def cancel_remaining_orders(self, position_data):
        """Cancel remaining SL/TP orders when one fills"""
        try:
            symbol = position_data.get('symbol')
            sl_order_id = position_data.get('sl_order_id')
            tp_order_id = position_data.get('tp_order_id')
            
            cancelled = []
            
            # Try to cancel both orders
            for order_id in [sl_order_id, tp_order_id]:
                if order_id:
                    try:
                        result = self.client.futures_cancel_order(symbol=symbol, orderId=order_id)
                        if result['status'] in ['CANCELED', 'EXPIRED']:
                            cancelled.append(order_id)
                            logger.info(f"🗑️ Cancelled order {order_id}")
                    except Exception as e:
                        # Order might already be filled or cancelled
                        logger.debug(f"Could not cancel order {order_id}: {e}")
            
            return cancelled
            
        except Exception as e:
            logger.error(f"❌ Failed to cancel remaining orders: {e}")
            return []
    
    def sync_position(self, position_data, storage_path):
        """
        Complete sync workflow:
        1. Check if SL/TP filled
        2. Update virtual state if closed
        3. Cancel remaining orders
        """
        try:
            position_id = position_data.get('position_id')
            
            # Check order status
            closed, exit_type, exit_price, pnl = self.check_position_orders(position_data, storage_path)
            
            if closed:
                # Cancel remaining orders
                self.cancel_remaining_orders(position_data)
                
                # Update virtual state
                self.update_position_closed(position_id, storage_path, exit_type, exit_price, pnl)
                
                return {
                    'closed': True,
                    'exit_type': exit_type,
                    'exit_price': exit_price,
                    'pnl': pnl
                }
            
            return {'closed': False}
            
        except Exception as e:
            logger.error(f"❌ Failed to sync position: {e}")
            return {'closed': False}




def get_order_monitor(strategy_name='multi_strategy'):
    """Factory function to get order monitor instance"""
    return OrderMonitor(strategy_name)
