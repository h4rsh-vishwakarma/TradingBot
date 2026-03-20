"""
Enhanced Order Manager using Mainnet Price Authority Architecture
STRICT RULES:
- Uses strategy engine for all price-based decisions
- Uses enhanced order executor for LIMIT-only orders
- All P&L calculations use MAINNET prices
"""

from exchange.binance_client import BinanceClient
from exchange.enhanced_order_executor import EnhancedOrderExecutor
from core.strategy_engine import StrategyEngine
from core.position_manager import PositionManager
from core.risk_manager import RiskManager
from exchange.execution_engine import get_execution_engine
from utils.logger import setup_logger, log_trade
from utils.client_order_id_generator import ClientOrderIdGenerator
from utils.health_checker import get_health_checker
import time
import random
import string

logger = setup_logger('enhanced_order_manager')

class EnhancedOrderManager:
    """Enhanced order manager with mainnet price authority"""
    
    def __init__(self, config, client: BinanceClient, position_manager: PositionManager, 
                 balance_manager=None, strategy_name=None):
        self.config = config
        self.client = client  # Keep for legacy compatibility
        
        # Use new architecture components
        self.strategy_engine = StrategyEngine(config)
        self.executor = EnhancedOrderExecutor(client)
        self.execution_engine = get_execution_engine()
        
        self.position_manager = position_manager
        self.risk_manager = RiskManager(config)
        self.balance_manager = balance_manager
        self.strategy_name = strategy_name or 'multi'
        self.allow_opposite = config['strategies']['allow_opposite_signals']
        
        # Initialize health checker
        self.health_checker = get_health_checker(self.strategy_name)
        
        logger.info(f"🚀 Enhanced order manager initialized with mainnet price authority (strategy: {self.strategy_name})")
    
    @staticmethod
    def round_quantity(symbol, quantity):
        """Round quantity to symbol-specific precision"""
        SYMBOL_PRECISION = {
            'BTCUSDT': 3,
            'ETHUSDT': 3,
            'SOLUSDT': 1
        }
        precision = SYMBOL_PRECISION.get(symbol, 3)
        return round(quantity, precision)
    
    def execute_signal(self, signal):
        """Execute signal using MAINNET price authority"""
        try:
            symbol = signal['symbol']
            side = signal['side']
            
            logger.info(f"🎯 Executing signal: {signal['signal_id']} | {side} {symbol}")
            
            # 1. Check if max positions reached
            if not self.position_manager.can_open_position():
                logger.warning(f"⚠️ Cannot open position: max positions reached")
                return False
            
            # 2. Check for existing opposite position
            opposite_side = 'SHORT' if side == 'LONG' else 'LONG'
            existing_opposite = self.position_manager.get_position(symbol, opposite_side)
            
            if existing_opposite:
                if self.allow_opposite:
                    logger.info(f"🔄 Closing opposite {opposite_side} position before opening {side}")
                    self.close_existing_position(existing_opposite)
                else:
                    logger.warning(f"⚠️ Opposite {opposite_side} position exists, skipping {side} signal")
                    return False
            
            # 3. Check for existing same-side position
            existing_same = self.position_manager.get_position(symbol, side)
            if existing_same:
                logger.warning(f"⚠️ {side} position already open for {symbol}, skipping")
                return False
            
            # 4. Validate signal entry using MAINNET price
            entry_price, is_valid = self.strategy_engine.validate_signal_entry(signal)
            if not is_valid or entry_price is None:
                logger.error(f"❌ Signal validation failed for {symbol}")
                return False
            
            # 5. Calculate position size using VIRTUAL balance
            testnet_balance = self.execution_engine.get_balance()
            virtual_balance = self.balance_manager.get_balance() if self.balance_manager else testnet_balance
            
            # Use virtual balance for sizing (this is the bot's trading capital)
            # Only check testnet has minimum required for the actual order
            balance_to_use = virtual_balance
            
            if balance_to_use < self.risk_manager.min_position_usd:
                logger.error(f"❌ Insufficient virtual balance: ${balance_to_use:.2f}")
                return False
            
            position_size = self.risk_manager.calculate_position_size(balance_to_use, entry_price)
            if position_size <= 0:
                logger.error(f"❌ Invalid position size: {position_size}")
                return False
            
            # Check if testnet has enough for the actual order (position_size * entry_price)
            required_testnet_balance = position_size * entry_price / self.config['trading']['leverage']
            if testnet_balance < required_testnet_balance:
                logger.error(f"❌ Insufficient testnet balance: ${testnet_balance:.2f} < ${required_testnet_balance:.2f}")
                return False
            
            # 6. Calculate SL/TP using MAINNET prices
            stop_loss_price = self.strategy_engine.calculate_stop_loss_price(signal, entry_price)
            take_profit_price = self.strategy_engine.calculate_take_profit_price(signal, entry_price)
            
            # 7. Validate minimum SL distance for timeframe
            timeframe = signal.get('timeframe', '15m')
            if stop_loss_price:
                sl_valid, suggested_sl = self.risk_manager.validate_minimum_sl_distance(
                    side, entry_price, stop_loss_price, timeframe
                )
                if not sl_valid:
                    logger.warning(f"⚠️ Using suggested SL: ${suggested_sl:.2f}")
                    stop_loss_price = suggested_sl
            
            # 8. Apply SL buffer with timeframe consideration
            if stop_loss_price:
                stop_loss_price = self.risk_manager.apply_sl_buffer(side, stop_loss_price, timeframe)
            
            # 9. Reserve virtual balance (only the margin amount, not full position value)
            position_value_usd = position_size * entry_price
            leverage = self.config['trading']['leverage']
            margin_required = position_value_usd / leverage  # Only reserve the margin
            
            if self.balance_manager:
                if not self.balance_manager.reserve_balance(margin_required):
                    logger.error(f"❌ Failed to reserve virtual balance: ${margin_required:.2f} (margin for ${position_value_usd:.2f} position)")
                    return False
            
            # 10. Set leverage on TESTNET
            leverage = self.config['trading']['leverage']
            self.execution_engine.set_leverage(symbol, leverage)
            self.execution_engine.set_margin_mode(symbol, 'CROSSED')
            
            # 11. Generate deterministic client order ID (exchange-level idempotency)
            signal_id = signal.get('signal_id', f'SIG{int(time.time())}')
            bracket_ids = ClientOrderIdGenerator.generate_for_bracket(signal_id, attempt=1)
            client_order_id = bracket_ids['entry']  # Use entry ID for the main order
            
            # 12. Place bracket order using MAINNET prices
            rounded_qty = self.round_quantity(symbol, position_size)
            logger.info(f"📤 Placing LIMIT bracket order: {symbol} {side} x{rounded_qty:.4f}")
            logger.info(f"   Entry: ${entry_price:.2f} (MAINNET)")
            logger.info(f"   SL: ${stop_loss_price:.2f} (MAINNET)" if stop_loss_price else "   SL: None")
            logger.info(f"   TP: ${take_profit_price:.2f} (MAINNET)" if take_profit_price else "   TP: None")
            logger.info(f"   Order IDs: Entry={bracket_ids['entry']}, SL={bracket_ids['sl']}, TP={bracket_ids['tp']}")
            
            orders = self.executor.place_bracket_order(
                symbol=symbol,
                side=side,
                amount=rounded_qty,
                stop_loss=stop_loss_price or 0,
                take_profit=take_profit_price or 0,
                client_order_id=client_order_id
            )
            
            if not orders or not orders.get('entry'):
                logger.error(f"❌ Failed to place orders for {symbol}")
                if self.balance_manager:
                    self.balance_manager.release_balance(margin_required)
                return False
            
            # Increment orders_placed counter (bracket order = 3 orders: entry + SL + TP)
            self.health_checker.increment_orders_placed()
            if orders.get('sl'):
                self.health_checker.increment_orders_placed()
            if orders.get('tp'):
                self.health_checker.increment_orders_placed()
            
            # 13. Create position record with MAINNET entry price
            enhanced_signal = signal.copy()
            enhanced_signal['entry_price'] = entry_price  # Use MAINNET price
            enhanced_signal['position_size'] = position_size  # Add calculated position size
            enhanced_signal['stop_loss'] = str(stop_loss_price) if stop_loss_price else '0'
            enhanced_signal['take_profit'] = str(take_profit_price) if take_profit_price else '0'
            enhanced_signal['price'] = str(entry_price)  # Ensure price field is set correctly
            
            # Log the enhanced signal data for debugging
            logger.info(f"📋 Enhanced signal data:")
            logger.info(f"   entry_price: {enhanced_signal['entry_price']}")
            logger.info(f"   position_size: {enhanced_signal['position_size']}")
            logger.info(f"   price: {enhanced_signal['price']}")
            
            position = self.position_manager.add_position(enhanced_signal, orders['entry'], orders)
            
            if position:
                # Double-check position data is correct
                if float(position.get('entry_price', 0)) <= 0:
                    logger.warning(f"⚠️ Position entry price is invalid, updating with mainnet price")
                    self.position_manager.update_position(position['position_id'], {
                        'entry_price': str(entry_price),
                        'position_size': str(position_size)
                    })
                
                logger.info(f"✅ Position opened: {position['position_id']} | {side} {symbol} @ ${entry_price:.2f} (MAINNET)")
                
                # Increment positions_opened counter
                self.health_checker.increment_positions_opened()
                
                return True
            else:
                logger.error(f"❌ Failed to track position for {symbol}")
                if self.balance_manager:
                    self.balance_manager.release_balance(margin_required)
                return False
            
        except Exception as e:
            logger.error(f"❌ Failed to execute signal: {e}")
            return False
    
    def close_existing_position(self, position):
        """Close existing position using MAINNET price for P&L calculation"""
        try:
            symbol = position['symbol']
            side = position['side']
            amount = float(position['position_size'])
            
            logger.info(f"🔄 Closing position: {symbol} {side} x{amount}")
            
            # Get current MAINNET price for P&L calculation
            current_mainnet_price = self.strategy_engine.price_provider.get_current_price(symbol)
            
            # Close position using LIMIT order at MAINNET price
            close_order = self.executor.close_position_at_market(symbol, side, amount)
            
            if close_order:
                # Calculate P&L using MAINNET prices
                entry_price = float(position['entry_price'])
                pnl = self.strategy_engine.calculate_position_pnl(position, current_mainnet_price)
                
                # Update position status
                self.position_manager.update_position(position['position_id'], {
                    'status': 'closed',
                    'exit_type': 'MANUAL_CLOSE',
                    'exit_price': str(current_mainnet_price),
                    'exit_time': time.time(),
                    'pnl': pnl,
                    'closed_at': time.time()
                })
                
                # Update balance with MAINNET-calculated P&L
                if self.balance_manager:
                    position_value = entry_price * amount
                    self.balance_manager.update_on_close(position_value, pnl)
                
                # Increment positions_closed counter with PnL
                self.health_checker.increment_positions_closed(pnl)
                
                logger.info(f"✅ Position closed: {symbol} @ ${current_mainnet_price:.2f} | P&L: ${pnl:.4f} (MAINNET)")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"❌ Failed to close position: {e}")
            return False
    
    def monitor_positions_with_mainnet_prices(self):
        """Monitor positions using MAINNET prices for exit decisions"""
        try:
            positions = self.position_manager.get_open_positions()
            
            for position in positions:
                symbol = position['symbol']
                
                # Check if position should close based on MAINNET price
                should_close, close_reason = self.strategy_engine.should_close_position(position)
                
                if should_close:
                    logger.info(f"🎯 Position exit triggered: {symbol} - {close_reason}")
                    
                    # Get current MAINNET price for exit
                    exit_price = self.strategy_engine.price_provider.get_current_price(symbol)
                    
                    # Close position
                    side = position['side']
                    amount = float(position['position_size'])
                    close_order = self.executor.close_position_at_market(symbol, side, amount)
                    
                    if close_order:
                        # Calculate P&L using MAINNET prices
                        pnl = self.strategy_engine.calculate_position_pnl(position, exit_price)
                        
                        # Update position
                        self.position_manager.update_position(position['position_id'], {
                            'status': 'closed',
                            'exit_type': close_reason,
                            'exit_price': str(exit_price),
                            'exit_time': time.time(),
                            'pnl': pnl,
                            'closed_at': time.time()
                        })
                        
                        # Update balance
                        if self.balance_manager:
                            entry_price = float(position['entry_price'])
                            position_value = entry_price * amount
                            self.balance_manager.update_on_close(position_value, pnl)
                        
                        # Increment positions_closed counter with PnL
                        self.health_checker.increment_positions_closed(pnl)
                        
                        logger.info(f"✅ Position closed: {symbol} | {close_reason} @ ${exit_price:.2f} | P&L: ${pnl:.4f} (MAINNET)")
            
        except Exception as e:
            logger.error(f"❌ Error monitoring positions: {e}")
    
    def process_signals(self, signals):
        """Process multiple signals"""
        executed_count = 0
        
        for signal in signals:
            try:
                if self.execute_signal(signal):
                    executed_count += 1
                time.sleep(0.5)  # Small delay between orders
            except Exception as e:
                logger.error(f"❌ Error processing signal {signal.get('signal_id', 'unknown')}: {e}")
        
        logger.info(f"📊 Processed {len(signals)} signals, executed {executed_count} orders")
        return executed_count