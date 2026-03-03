"""
Testnet Execution Engine - ONLY for order execution and balance management
STRICT RULE: This module NEVER provides price data - only executes orders
"""

import os
from binance.client import Client
from binance.exceptions import BinanceAPIException
from dotenv import load_dotenv
from utils.logger import setup_logger
import time

load_dotenv()

logger = setup_logger('execution_engine')

class TestnetExecutionEngine:
    """
    TESTNET-ONLY execution engine
    Handles ONLY: balance checks, order placement, order status
    NEVER provides price data
    """
    
    def __init__(self, api_key=None, api_secret=None):
        self.api_key = api_key or os.getenv('BINANCE_API_KEY')
        self.api_secret = api_secret or os.getenv('BINANCE_API_SECRET')
        
        # CRITICAL: ALWAYS connect to TESTNET for execution
        self.client = Client(self.api_key, self.api_secret, testnet=True)
        
        logger.info("🧪 [TESTNET] Execution engine initialized - TESTNET ONLY")
        
        # Test connection
        try:
            account = self.client.futures_account()
            logger.info("✅ [TESTNET] Connected successfully - Ready for order execution")
        except BinanceAPIException as e:
            logger.error(f"❌ [TESTNET] Failed to connect: {e}")
            raise
    
    def get_balance(self):
        """Get TESTNET USDT balance"""
        try:
            account = self.client.futures_account()
            for asset in account['assets']:
                if asset['asset'] == 'USDT':
                    balance = float(asset['availableBalance'])
                    logger.debug(f"💰 [TESTNET] Balance: ${balance:.2f}")
                    return balance
            return 0.0
        except Exception as e:
            logger.error(f"❌ [TESTNET] Failed to fetch balance: {e}")
            return 0.0
    
    def place_limit_order(self, symbol, side, quantity, price, client_order_id=None):
        """
        Place LIMIT order on TESTNET
        Price MUST come from mainnet price provider
        """
        try:
            # Debug logging
            logger.info(f"🔍 place_limit_order received: symbol={symbol} (type={type(symbol).__name__}), side={side} (type={type(side).__name__}), quantity={quantity} (type={type(quantity).__name__}), price={price} (type={type(price).__name__})")
            
            # Convert side to proper Binance format
            if side.upper() == 'SHORT':
                side = 'SELL'
            elif side.upper() == 'LONG':
                side = 'BUY'
            
            # Round price and quantity for Binance precision
            price = self._round_price(price, symbol)
            quantity = self._round_quantity(quantity, symbol)
            
            order_params = {
                'symbol': symbol,
                'side': side,
                'type': 'LIMIT',
                'quantity': quantity,
                'price': price,
                'timeInForce': 'GTC'
            }
            
            if client_order_id:
                order_params['newClientOrderId'] = client_order_id
            
            order = self.client.futures_create_order(**order_params)
            
            logger.info(f"📤 [TESTNET] LIMIT {side} order placed: {symbol} x{quantity} @ ${price:.2f} | Order ID: {order['orderId']}")
            return order
            
        except (BinanceAPIException, ValueError, KeyError) as e:
            logger.error(f"❌ [TESTNET] Failed to place LIMIT order {symbol}: {e}", exc_info=True)
            return None
    
    def place_stop_limit_order(self, symbol, side, quantity, stop_price, limit_price, client_order_id=None):
        """
        Place STOP_LIMIT order on TESTNET
        Prices MUST come from mainnet price provider
        """
        try:
            # Round prices and quantity
            stop_price = self._round_price(stop_price, symbol)
            limit_price = self._round_price(limit_price, symbol)
            quantity = self._round_quantity(quantity, symbol)
            
            # Use STOP_MARKET for reliable stop-loss execution
            order_params = {
                'symbol': symbol,
                'side': side,
                'type': 'STOP_MARKET',
                'quantity': quantity,
                'stopPrice': stop_price,
                'reduceOnly': 'true',
                'workingType': 'CONTRACT_PRICE'  # Required for TESTNET compatibility
            }
            
            if client_order_id:
                order_params['newClientOrderId'] = client_order_id
            
            try:
                order = self.client.futures_create_order(**order_params)
                logger.info(f"🛑 [TESTNET] STOP_MARKET {side} order placed: {symbol} @ stop=${stop_price:.2f} | Order ID: {order['orderId']}")
                return order
            except Exception as stop_error:
                # If STOP_MARKET fails, try STOP with limit price
                logger.warning(f"⚠️ [TESTNET] STOP_MARKET failed, trying STOP: {stop_error}")
                try:
                    order_params['type'] = 'STOP'
                    order_params['price'] = limit_price
                    order_params['timeInForce'] = 'GTC'  # Required for STOP with limit price
                    order = self.client.futures_create_order(**order_params)
                    logger.info(f"🛑 [TESTNET] STOP {side} order placed: {symbol} @ stop=${stop_price:.2f}, limit=${limit_price:.2f} | Order ID: {order['orderId']}")
                    return order
                except Exception as stop2_error:
                    logger.error(f"❌ [TESTNET] STOP order also failed: {stop2_error}")
                    return None
                
        except (BinanceAPIException, ValueError, KeyError) as e:
            logger.error(f"❌ [TESTNET] Failed to place STOP_LIMIT order {symbol}: {e}", exc_info=True)
            return None
    
    def get_order_status(self, symbol, order_id):
        """Get order status from TESTNET"""
        try:
            order = self.client.futures_get_order(symbol=symbol, orderId=order_id)
            status = order['status']
            
            logger.debug(f"📋 [TESTNET] Order {order_id} status: {status}")
            return order
            
        except Exception as e:
            logger.error(f"❌ [TESTNET] Failed to get order status {order_id}: {e}")
            return None
    
    def cancel_order(self, symbol, order_id):
        """Cancel order on TESTNET"""
        try:
            result = self.client.futures_cancel_order(symbol=symbol, orderId=order_id)
            logger.info(f"❌ [TESTNET] Order cancelled: {order_id}")
            return result
            
        except Exception as e:
            logger.error(f"❌ [TESTNET] Failed to cancel order {order_id}: {e}")
            return None
    
    def get_positions(self):
        """Get TESTNET positions (for status only, NOT for price data)"""
        try:
            positions = self.client.futures_position_information()
            # Filter only positions with non-zero size
            open_positions = [
                p for p in positions 
                if float(p.get('positionAmt', 0)) != 0
            ]
            
            logger.debug(f"📊 [TESTNET] Found {len(open_positions)} open positions")
            return open_positions
            
        except Exception as e:
            logger.error(f"❌ [TESTNET] Failed to fetch positions: {e}")
            return []
    
    def get_position(self, symbol):
        """Get specific TESTNET position (for status only)"""
        try:
            positions = self.client.futures_position_information(symbol=symbol)
            for pos in positions:
                if float(pos.get('positionAmt', 0)) != 0:
                    logger.debug(f"📊 [TESTNET] Position found: {symbol} size={pos.get('positionAmt')}")
                    return pos
            return None
        except Exception as e:
            logger.error(f"❌ [TESTNET] Failed to get position for {symbol}: {e}")
            return None
    
    def set_leverage(self, symbol, leverage):
        """Set leverage on TESTNET"""
        try:
            self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
            logger.info(f"⚡ [TESTNET] Set leverage to {leverage}x for {symbol}")
            return True
        except Exception as e:
            logger.error(f"❌ [TESTNET] Failed to set leverage for {symbol}: {e}")
            return False
    
    def set_margin_mode(self, symbol, margin_mode='CROSSED'):
        """Set margin mode on TESTNET"""
        try:
            self.client.futures_change_margin_type(symbol=symbol, marginType=margin_mode)
            logger.info(f"📊 [TESTNET] Set margin mode to {margin_mode} for {symbol}")
            return True
        except BinanceAPIException as e:
            # Ignore if already set
            if 'No need to change' in str(e) or e.code == -4046:
                return True
            logger.warning(f"⚠️ [TESTNET] Could not set margin mode for {symbol}: {e}")
            return False
    
    def _round_price(self, price, symbol):
        """Round price to symbol precision with proper tick size handling"""
        try:
            price_float = float(price)
            
            if 'USDT' in symbol:
                # For BTCUSDT, use 0.10 tick size (round to nearest 0.10)
                if symbol == 'BTCUSDT':
                    tick_size = 0.10
                    rounded = round(price_float / tick_size) * tick_size
                    # Ensure proper decimal precision
                    return round(rounded, 1)  # 1 decimal place for BTCUSDT
                else:
                    # For other USDT pairs, use 0.01 tick size
                    tick_size = 0.01
                    rounded = round(price_float / tick_size) * tick_size
                    return round(rounded, 2)  # 2 decimal places
            else:
                return round(price_float, 8)
        except Exception as e:
            logger.error(f"❌ Error rounding price {price}: {e}")
            # Fallback with proper BTCUSDT handling
            if symbol == 'BTCUSDT':
                return round(float(price), 1)
            return round(float(price), 2)
    
    def _round_quantity(self, quantity, symbol):
        """Round quantity to symbol precision"""
        try:
            # Ensure symbol is a string (not float/int)
            symbol_str = str(symbol) if symbol else ''
            quantity_float = float(quantity)
            
            # Symbol-specific precision (must match Binance Futures requirements)
            if symbol_str == 'SOLUSDT':
                return int(round(quantity_float, 0))  # SOLUSDT requires whole numbers only
            elif symbol_str.startswith('BTC') or symbol_str == 'ETHUSDT':
                return round(quantity_float, 3)
            return round(quantity_float, 6)
        except (ValueError, TypeError) as e:
            logger.error(f"❌ _round_quantity error: quantity={quantity} (type={type(quantity)}), symbol={symbol} (type={type(symbol)}), error={e}")
            raise

# Global instance
_testnet_execution_engine = None

def get_execution_engine():
    """Get the global testnet execution engine instance"""
    global _testnet_execution_engine
    if _testnet_execution_engine is None:
        _testnet_execution_engine = TestnetExecutionEngine()
    return _testnet_execution_engine