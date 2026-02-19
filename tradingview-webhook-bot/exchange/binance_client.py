import os
from binance.client import Client
from binance.exceptions import BinanceAPIException
from dotenv import load_dotenv
from utils.logger import setup_logger

load_dotenv()

logger = setup_logger('binance_client')

class BinanceClient:
    """Binance Futures API Client using python-binance library"""
    
    def __init__(self, api_key=None, api_secret=None, testnet=False):
        self.api_key = api_key or os.getenv('BINANCE_API_KEY')
        self.api_secret = api_secret or os.getenv('BINANCE_API_SECRET')
        self.testnet = testnet or os.getenv('BINANCE_TESTNET', 'False').lower() == 'true'
        
        # Initialize python-binance Client
        self.client = Client(self.api_key, self.api_secret, testnet=self.testnet)
        
        if self.testnet:
            logger.info("[TESTNET] Binance Futures TESTNET mode enabled")
        else:
            logger.info("[LIVE] Binance Futures LIVE mode enabled")
        
        # Test connection
        try:
            # Test with futures_account() call
            account = self.client.futures_account()
            logger.info(f"[OK] Connected to Binance Futures")
        except BinanceAPIException as e:
            logger.error(f"[ERROR] Failed to connect to Binance: {e}")
            raise
    
    def get_balance(self):
        """Get USDT balance"""
        try:
            account = self.client.futures_account()
            for asset in account['assets']:
                if asset['asset'] == 'USDT':
                    return float(asset['availableBalance'])
            return 0.0
        except Exception as e:
            logger.error(f"Failed to fetch balance: {e}")
            return 0.0
    
    def get_current_price(self, symbol):
        """Get current market price"""
        try:
            ticker = self.client.futures_symbol_ticker(symbol=symbol)
            return float(ticker['price'])
        except Exception as e:
            logger.error(f"Failed to fetch price for {symbol}: {e}")
            return 0.0
    
    def get_positions(self):
        """Get all open positions"""
        try:
            positions = self.client.futures_position_information()
            # Filter only positions with non-zero size
            open_positions = [
                p for p in positions 
                if float(p.get('positionAmt', 0)) != 0
            ]
            return open_positions
        except Exception as e:
            logger.error(f"Failed to fetch positions: {e}")
            return []
    
    def get_position(self, symbol):
        """Get specific position"""
        try:
            positions = self.client.futures_position_information(symbol=symbol)
            for pos in positions:
                if float(pos.get('positionAmt', 0)) != 0:
                    return pos
            return None
        except Exception as e:
            logger.error(f"Failed to get position for {symbol}: {e}")
            return None
    
    def set_leverage(self, symbol, leverage):
        """Set leverage for symbol"""
        try:
            self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
            logger.info(f"[OK] Set leverage to {leverage}x for {symbol}")
            return True
        except Exception as e:
            logger.error(f"Failed to set leverage for {symbol}: {e}")
            return False
    
    def set_margin_mode(self, symbol, margin_mode='CROSSED'):
        """Set margin mode (CROSSED or ISOLATED)"""
        try:
            self.client.futures_change_margin_type(symbol=symbol, marginType=margin_mode)
            logger.info(f"[OK] Set margin mode to {margin_mode} for {symbol}")
            return True
        except BinanceAPIException as e:
            # Ignore if already set
            if 'No need to change' in str(e) or e.code == -4046:
                return True
            logger.warning(f"Could not set margin mode for {symbol}: {e}")
            return False
    
    def futures_get_order(self, symbol, orderId):
        """Get order status"""
        try:
            return self.client.futures_get_order(symbol=symbol, orderId=orderId)
        except Exception as e:
            logger.error(f"Error getting order {orderId} for {symbol}: {e}")
            raise
    
    def futures_create_order(self, **params):
        """Create futures order"""
        try:
            return self.client.futures_create_order(**params)
        except Exception as e:
            logger.error(f"Error creating order: {e}")
            raise
    
    def futures_cancel_order(self, symbol, orderId):
        """Cancel futures order"""
        try:
            return self.client.futures_cancel_order(symbol=symbol, orderId=orderId)
        except Exception as e:
            logger.error(f"Error canceling order {orderId} for {symbol}: {e}")
            raise
    
    def futures_get_open_orders(self, symbol=None):
        """Get open orders"""
        try:
            if symbol:
                return self.client.futures_get_open_orders(symbol=symbol)
            return self.client.futures_get_open_orders()
        except Exception as e:
            logger.error(f"Error getting open orders: {e}")
            return []
    
    def futures_cancel_all_open_orders(self, symbol):
        """Cancel all open orders for symbol"""
        try:
            return self.client.futures_cancel_all_open_orders(symbol=symbol)
        except Exception as e:
            logger.error(f"Error canceling all orders for {symbol}: {e}")
            raise
