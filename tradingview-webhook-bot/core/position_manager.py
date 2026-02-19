import json
import os
from datetime import datetime
from utils.logger import setup_logger, log_trade

logger = setup_logger('position_manager')

class PositionManager:
    """Track and manage open positions"""
    
    def __init__(self, config, positions_file, strategy_name=None):
        self.config = config
        self.positions_file = positions_file
        self.max_positions = config['risk']['max_positions']
        self.strategy_name = strategy_name  # Filter positions by strategy
        
        # Ensure file exists
        os.makedirs(os.path.dirname(positions_file), exist_ok=True)
        if not os.path.exists(positions_file):
            with open(positions_file, 'w') as f:
                pass
        
        logger.info(f"📁 Position manager initialized (max: {self.max_positions}, strategy: {strategy_name or 'all'})")
    
    def get_open_positions(self):
        """Get all open positions from file (filtered by strategy if specified)"""
        positions = []
        
        try:
            with open(self.positions_file, 'r') as f:
                for line in f:
                    try:
                        pos = json.loads(line.strip())
                        if pos.get('status') == 'open':
                            # Filter by strategy if specified
                            if self.strategy_name is None or pos.get('strategy') == self.strategy_name:
                                positions.append(pos)
                    except json.JSONDecodeError:
                        continue
        except FileNotFoundError:
            return []
        except Exception as e:
            logger.error(f"Failed to read positions: {e}")
            return []
        
        return positions
    
    def get_position(self, symbol, side):
        """Get specific open position"""
        positions = self.get_open_positions()
        for pos in positions:
            if pos['symbol'] == symbol and pos['side'] == side:
                return pos
        return None
    
    def count_open_positions(self):
        """Count total open positions"""
        return len(self.get_open_positions())
    
    def can_open_position(self):
        """Check if can open new position"""
        open_count = self.count_open_positions()
        if open_count >= self.max_positions:
            logger.warning(f"⚠️ Max positions reached ({open_count}/{self.max_positions})")
            return False
        return True
    
    def get_symbol_exposure(self, symbol):
        """Get total exposure for a symbol"""
        positions = self.get_open_positions()
        total_exposure = sum(
            float(pos.get('position_size', 0)) 
            for pos in positions 
            if pos['symbol'] == symbol
        )
        return total_exposure
    
    def add_position(self, signal, entry_order, bracket_orders):
        """Add new position"""
        try:
            # Safely extract SL/TP order IDs
            sl_order_id = None
            tp_order_id = None
            if bracket_orders:
                sl_order = bracket_orders.get('stop_loss')
                tp_order = bracket_orders.get('take_profit')
                sl_order_id = sl_order.get('orderId') if sl_order and isinstance(sl_order, dict) else None
                tp_order_id = tp_order.get('orderId') if tp_order and isinstance(tp_order, dict) else None
            
            # Extract entry price from signal - ensure it's properly converted
            entry_price = None
            
            # Try multiple sources for entry price in priority order
            if signal.get('entry_price') and float(signal['entry_price']) > 0:
                entry_price = float(signal['entry_price'])
            elif signal.get('price') and float(signal['price']) > 0:
                entry_price = float(signal['price'])
            elif entry_order and isinstance(entry_order, dict):
                # Use order response as fallback
                order_price = entry_order.get('avgPrice') or entry_order.get('price')
                if order_price and float(order_price) > 0:
                    entry_price = float(order_price)
            
            # Ensure we have a valid entry price
            if not entry_price or entry_price <= 0:
                logger.error(f"❌ Invalid entry price: {entry_price} for signal {signal.get('signal_id')}")
                logger.error(f"   Signal data: entry_price={signal.get('entry_price')}, price={signal.get('price')}")
                logger.error(f"   Order data: {entry_order}")
                return None
            
            # Extract position size from signal or order
            position_size = None
            if signal.get('position_size') and float(signal['position_size']) > 0:
                position_size = float(signal['position_size'])
            elif entry_order and isinstance(entry_order, dict):
                order_size = entry_order.get('executedQty') or entry_order.get('origQty') or entry_order.get('quantity')
                if order_size and float(order_size) > 0:
                    position_size = float(order_size)
            
            # Ensure we have a valid position size
            if not position_size or position_size <= 0:
                logger.error(f"❌ Invalid position size: {position_size} for signal {signal.get('signal_id')}")
                logger.error(f"   Signal data: position_size={signal.get('position_size')}")
                logger.error(f"   Order data: {entry_order}")
                return None
            
            position = {
                'position_id': f"{signal['signal_id']}_pos",
                'signal_id': signal['signal_id'],
                'strategy': signal['strategy'],
                'symbol': signal['symbol'],
                'side': signal['side'],
                'timeframe': signal['timeframe'],
                'entry_price': str(entry_price),
                'entry_time': datetime.utcnow().isoformat(),
                'position_size': str(position_size),
                'stop_loss': signal['stop_loss'],
                'take_profit': signal['take_profit'],
                'entry_order_id': entry_order.get('orderId'),
                'sl_order_id': sl_order_id,
                'tp_order_id': tp_order_id,
                'status': 'open',
                'opened_at': datetime.utcnow().isoformat()
            }
            
            # Write to file
            with open(self.positions_file, 'a') as f:
                f.write(json.dumps(position) + '\n')
            
            # Log trade
            log_trade('position_opened', position)
            
            logger.info(f"✅ Position added: {position['position_id']} | {signal['side']} {signal['symbol']} @ ${position['entry_price']}")
            
            return position
        except Exception as e:
            logger.error(f"Failed to add position: {e}")
            return None
    
    def close_position(self, position_id, reason='manual', pnl=None):
        """Close position"""
        try:
            # Read all positions
            positions = []
            updated = False
            
            with open(self.positions_file, 'r') as f:
                for line in f:
                    try:
                        pos = json.loads(line.strip())
                        if pos.get('position_id') == position_id and pos.get('status') == 'open':
                            pos['status'] = 'closed'
                            pos['closed_at'] = datetime.utcnow().isoformat()
                            pos['close_reason'] = reason
                            if pnl is not None:
                                pos['pnl'] = str(pnl)
                            updated = True
                            
                            # Log trade
                            log_trade('position_closed', pos)
                            
                            logger.info(f"✅ Position closed: {position_id} | Reason: {reason}")
                        
                        positions.append(pos)
                    except json.JSONDecodeError:
                        continue
            
            # Write back
            if updated:
                with open(self.positions_file, 'w') as f:
                    for pos in positions:
                        f.write(json.dumps(pos) + '\n')
            
            return updated
        except Exception as e:
            logger.error(f"Failed to close position: {e}")
            return False
    
    def update_position(self, position_id, updates):
        """Update position fields"""
        try:
            positions = []
            updated = False
            
            with open(self.positions_file, 'r') as f:
                for line in f:
                    try:
                        pos = json.loads(line.strip())
                        if pos.get('position_id') == position_id:
                            pos.update(updates)
                            updated = True
                        positions.append(pos)
                    except json.JSONDecodeError:
                        continue
            
            if updated:
                with open(self.positions_file, 'w') as f:
                    for pos in positions:
                        f.write(json.dumps(pos) + '\n')
            
            return updated
        except Exception as e:
            logger.error(f"Failed to update position: {e}")
            return False
