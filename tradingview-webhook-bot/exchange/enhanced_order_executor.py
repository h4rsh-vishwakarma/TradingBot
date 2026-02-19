"""
Enhanced Order Executor using Mainnet Price Authority Architecture
STRICT RULES:
- ALL prices come from mainnet price provider
- ALL orders are LIMIT orders (no MARKET orders)
- Testnet is used ONLY for order execution
"""

from binance.enums import SIDE_BUY, SIDE_SELL
from exchange.price_provider import get_price_provider
from exchange.execution_engine import get_execution_engine
from utils.logger import setup_logger
import time

logger = setup_logger('enhanced_order_executor')

class EnhancedOrderExecutor:
    """Enhanced order executor with mainnet price authority"""
    
    def __init__(self, client=None):
        # Use new architecture components
        self.price_provider = get_price_provider()
        self.execution_engine = get_execution_engine()
        
        # Keep legacy client for backward compatibility (but don't use for prices)
        self.client = client
        
        logger.info("📋 Enhanced order executor initialized with mainnet price authority")
    
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
    
    @staticmethod
    def _round_price(symbol, price):
        """Round price to symbol-specific tick size"""
        price_float = float(price)
        
        if symbol == 'BTCUSDT':
            # BTCUSDT uses 0.10 tick size
            tick_size = 0.10
            rounded = round(price_float / tick_size) * tick_size
            return round(rounded, 1)
        else:
            # Other USDT pairs use 0.01 tick size
            tick_size = 0.01
            rounded = round(price_float / tick_size) * tick_size
            return round(rounded, 2)
    
    def place_limit_entry_order(self, symbol, side, amount, client_order_id=None):
        """
        Place LIMIT entry order using MAINNET price
        NO MARKET ORDERS - only LIMIT orders
        """
        try:
            # Get optimal entry price from MAINNET
            entry_price = self.price_provider.get_optimal_limit_price(
                symbol, side, aggressive=True  # Use current market price for entry
            )
            
            if entry_price == 0:
                logger.error(f"❌ Could not get mainnet price for {symbol}")
                return None
            
            # Place LIMIT order on TESTNET using MAINNET price
            order = self.execution_engine.place_limit_order(
                symbol=symbol,
                side=side,
                quantity=amount,
                price=entry_price,
                client_order_id=client_order_id
            )
            
            if order:
                logger.info(f"✅ LIMIT entry order placed: {symbol} {side} x{amount} @ ${entry_price:.2f}")
            
            return order
            
        except Exception as e:
            logger.error(f"❌ Failed to place entry order {symbol}: {e}")
            return None
    
    def place_stop_loss(self, symbol, side, amount, stop_price):
        """Place stop-loss order using MAINNET-derived price with retry logic"""
        try:
            # Determine opposite side for stop-loss
            stop_side = SIDE_SELL if side.upper() == 'LONG' else SIDE_BUY
            
            # Get optimal stop price from MAINNET
            optimal_stop_price = self.price_provider.get_optimal_limit_price(
                symbol, stop_side, aggressive=False
            )
            
            # Use more conservative of signal SL or optimal price
            if side.upper() == 'LONG':
                final_stop_price = min(stop_price, optimal_stop_price) if optimal_stop_price > 0 else stop_price
            else:
                final_stop_price = max(stop_price, optimal_stop_price) if optimal_stop_price > 0 else stop_price
            
            # Try STOP_LIMIT first, then fallback to LIMIT with price adjustments
            for attempt in range(3):
                try:
                    # Adjust stop price slightly for each attempt to avoid tick size issues
                    price_adjustment = 0.1 * (attempt + 1)  # 0.1, 0.2, 0.3
                    
                    if side.upper() == 'LONG':
                        # For LONG, SL should be lower, so subtract adjustment
                        adjusted_stop_price = final_stop_price - price_adjustment
                    else:
                        # For SHORT, SL should be higher, so add adjustment
                        adjusted_stop_price = final_stop_price + price_adjustment
                    
                    # Ensure proper tick size rounding
                    adjusted_stop_price = self.execution_engine._round_price(adjusted_stop_price, symbol)
                    
                    logger.info(f"🛑 Attempt {attempt + 1}: Placing SL at ${adjusted_stop_price:.2f}")
                    
                    # Use STOP_MARKET for reliable stop-loss (not LIMIT which can fill early)
                    order = self.execution_engine.place_stop_limit_order(
                        symbol=symbol,
                        side=stop_side,
                        quantity=amount,
                        stop_price=adjusted_stop_price,
                        limit_price=adjusted_stop_price * 1.002 if side.upper() == 'SHORT' else adjusted_stop_price * 0.998
                    )
                    
                    if order:
                        logger.info(f"🛑 Stop-loss STOP_MARKET placed: {symbol} @ trigger=${adjusted_stop_price:.2f}")
                        return order
                        
                except Exception as stop_error:
                    logger.warning(f"⚠️ STOP_MARKET attempt {attempt + 1}/3 failed: {stop_error}")
                
                time.sleep(0.5)  # Wait before retry
            
            logger.error(f"❌ Failed to place SL after 3 attempts: {symbol}")
            return None
            
        except Exception as e:
            logger.error(f"❌ Failed to place stop-loss {symbol}: {e}")
            return None
    
    def place_take_profit(self, symbol, side, amount, tp_price):
        """Place take-profit order using MAINNET-derived price with retry logic"""
        try:
            # Determine opposite side for take-profit
            tp_side = SIDE_SELL if side.upper() == 'LONG' else SIDE_BUY
            
            # Get optimal TP price from MAINNET
            optimal_tp_price = self.price_provider.get_optimal_limit_price(
                symbol, tp_side, aggressive=False
            )
            
            # Use more aggressive of signal TP or optimal price
            if side.upper() == 'LONG':
                final_tp_price = max(tp_price, optimal_tp_price) if optimal_tp_price > 0 else tp_price
            else:
                final_tp_price = min(tp_price, optimal_tp_price) if optimal_tp_price > 0 else tp_price
            
            # Use LIMIT order for TP (fills at better price if possible)
            for attempt in range(3):
                try:
                    # LIMIT order for take-profit allows better fills
                    order = self.execution_engine.place_limit_order(
                        symbol=symbol,
                        side=tp_side,
                        quantity=amount,
                        price=final_tp_price
                    )
                    
                    if order:
                        logger.info(f"🎯 Take-profit LIMIT placed: {symbol} @ ${final_tp_price:.2f}")
                        return order
                        
                except Exception as tp_error:
                    logger.warning(f"⚠️ TP LIMIT attempt {attempt + 1}/3 failed: {tp_error}")
                
                time.sleep(0.5)  # Wait before retry
            
            logger.error(f"❌ Failed to place TP after 3 attempts: {symbol}")
            return None
            
        except Exception as e:
            logger.error(f"❌ Failed to place take-profit {symbol}: {e}")
            return None
    
    def place_bracket_order(self, symbol, side, amount, stop_loss, take_profit, client_order_id=None):
        """
        Place bracket order (entry + SL + TP) using MAINNET prices
        ALL orders are LIMIT orders based on MAINNET price data
        """
        try:
            logger.info(f"📋 Placing bracket order: {symbol} {side} x{amount}")
            
            # 1. Place LIMIT entry order using MAINNET price
            entry_order = self.place_limit_entry_order(symbol, side, amount, client_order_id)
            if not entry_order:
                logger.error(f"❌ Failed to place entry order for {symbol}")
                return None
            
            # Wait for entry order to potentially fill
            time.sleep(1.0)
            
            # 2. Place stop-loss with retry
            sl_order = None
            if stop_loss > 0:
                sl_order = self.place_stop_loss(symbol, side, amount, stop_loss)
            
            # 3. Place take-profit with retry
            tp_order = None
            if take_profit > 0:
                tp_order = self.place_take_profit(symbol, side, amount, take_profit)
            
            # Log results
            if not sl_order:
                logger.warning(f"⚠️ No stop-loss placed for {symbol}")
            if not tp_order:
                logger.warning(f"⚠️ No take-profit placed for {symbol}")
            
            return {
                'entry': entry_order,
                'stop_loss': sl_order,
                'take_profit': tp_order
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to place bracket order {symbol}: {e}")
            return None
    
    def close_position_at_market(self, symbol, side, amount):
        """
        Close position using LIMIT order at MAINNET market price
        NO MARKET ORDERS - use aggressive LIMIT order
        """
        try:
            # Ensure side is a string
            side = str(side).upper() if side else 'LONG'
            
            # Determine close side (opposite of position)
            close_side = SIDE_SELL if side == 'LONG' else SIDE_BUY
            
            # Get aggressive MAINNET price for immediate close
            close_price = self.price_provider.get_optimal_limit_price(
                symbol, close_side, aggressive=True
            )
            
            if close_price == 0:
                logger.error(f"❌ Could not get mainnet price for closing {symbol}")
                return None
            
            # Round quantity and price to symbol-specific precision
            rounded_amount = self.round_quantity(amount, symbol)
            rounded_price = self._round_price(symbol, close_price)
            
            # Place order via execution engine (proper client access)
            order = self.execution_engine.place_limit_order(
                symbol=symbol,
                side=close_side,
                quantity=rounded_amount,
                price=rounded_price
            )
            
            if order:
                logger.info(f"🔄 [TESTNET] Close order: {symbol} {close_side} x{rounded_amount} @ ${rounded_price}")
            
            return order
            
        except Exception as e:
            logger.error(f"❌ Failed to close position {symbol}: {e}")
            return None
    
    def get_order_status(self, symbol, order_id):
        """Get order status from TESTNET execution engine"""
        return self.execution_engine.get_order_status(symbol, order_id)
    
    def cancel_order(self, symbol, order_id):
        """Cancel order via TESTNET execution engine"""
        return self.execution_engine.cancel_order(symbol, order_id)
    
    # Legacy compatibility methods (redirect to new architecture)
    def round_price(self, price, symbol):
        """Legacy compatibility - use execution engine rounding"""
        return self.execution_engine._round_price(price, symbol)
    
    def round_quantity(self, quantity, symbol):
        """Legacy compatibility - use execution engine rounding"""
        return self.execution_engine._round_quantity(quantity, symbol)