"""
Mainnet Price Provider - ONLY source of price data for strategies
STRICT RULE: This module ONLY connects to Binance MAINNET for price data
"""

import os
import re
from binance.client import Client
from binance.exceptions import BinanceAPIException
from dotenv import load_dotenv
from utils.logger import setup_logger
import time
from threading import Lock

load_dotenv()

logger = setup_logger('price_provider')


def _clean_symbol(symbol: str) -> str:
    """Strip TradingView perpetual suffixes (.P, .PERP) — Binance uses plain symbol."""
    return re.sub(r'\.(P|PERP)$', '', str(symbol).strip(), flags=re.IGNORECASE)

class MainnetPriceProvider:
    """
    MAINNET-ONLY price provider
    This is the SINGLE source of truth for all price data
    """
    
    def __init__(self, api_key=None, api_secret=None):
        self.api_key = api_key or os.getenv('BINANCE_API_KEY')
        self.api_secret = api_secret or os.getenv('BINANCE_API_SECRET')
        
        # CRITICAL: ALWAYS connect to MAINNET for prices
        self.client = Client(self.api_key, self.api_secret, testnet=False)
        self._price_cache = {}
        self._cache_lock = Lock()
        self._cache_ttl = 5  # 5 second cache
        
        logger.info("🌐 [MAINNET] Price provider initialized - MAINNET ONLY")
        
        # Test connection
        try:
            # Test with a simple price call
            test_price = self.client.futures_symbol_ticker(symbol='BTCUSDT')
            logger.info(f"✅ [MAINNET] Connected successfully - BTCUSDT: ${float(test_price['price']):.2f}")
        except BinanceAPIException as e:
            logger.error(f"❌ [MAINNET] Failed to connect: {e}")
            raise
    
    def get_current_price(self, symbol):
        """
        Get current MAINNET price for symbol
        This is the ONLY method that should be used for price data
        """
        symbol = _clean_symbol(symbol)
        try:
            # Check cache first
            with self._cache_lock:
                cache_key = f"{symbol}_price"
                if cache_key in self._price_cache:
                    price_data, timestamp = self._price_cache[cache_key]
                    if time.time() - timestamp < self._cache_ttl:
                        logger.debug(f"📊 [MAINNET CACHE] {symbol}: ${price_data:.2f}")
                        return price_data
            
            # Fetch from MAINNET
            ticker = self.client.futures_symbol_ticker(symbol=symbol)
            price = float(ticker['price'])
            
            # Update cache
            with self._cache_lock:
                self._price_cache[cache_key] = (price, time.time())
            
            logger.debug(f"📊 [MAINNET] {symbol}: ${price:.2f}")
            return price
            
        except Exception as e:
            logger.error(f"❌ [MAINNET] Failed to fetch price for {symbol}: {e}")
            return 0.0
    
    def get_orderbook(self, symbol, limit=5):
        """Get MAINNET orderbook for better limit order pricing"""
        symbol = _clean_symbol(symbol)
        try:
            # Binance futures supports limits: 5, 10, 20, 50, 100, 500, 1000
            valid_limits = [5, 10, 20, 50, 100, 500, 1000]
            if limit not in valid_limits:
                limit = min(valid_limits, key=lambda x: abs(x - limit))
            
            orderbook = self.client.futures_order_book(symbol=symbol, limit=limit)
            
            bids = [(float(bid[0]), float(bid[1])) for bid in orderbook['bids']]
            asks = [(float(ask[0]), float(ask[1])) for ask in orderbook['asks']]
            
            logger.debug(f"📖 [MAINNET] {symbol} orderbook - Best bid: ${bids[0][0]:.2f}, Best ask: ${asks[0][0]:.2f}")
            
            return {
                'bids': bids,
                'asks': asks,
                'best_bid': bids[0][0] if bids else 0.0,
                'best_ask': asks[0][0] if asks else 0.0
            }
            
        except Exception as e:
            logger.error(f"❌ [MAINNET] Failed to fetch orderbook for {symbol}: {e}")
            return {'bids': [], 'asks': [], 'best_bid': 0.0, 'best_ask': 0.0}
    
    def get_optimal_limit_price(self, symbol, side, aggressive=False):
        """
        Calculate optimal limit order price based on MAINNET orderbook
        
        Args:
            symbol: Trading symbol
            side: 'BUY' or 'SELL'
            aggressive: If True, use market price. If False, use best bid/ask
        
        Returns:
            Optimal limit price for the order
        """
        try:
            if aggressive:
                # Use current market price for immediate fill
                return self.get_current_price(symbol)
            else:
                # Use orderbook for better pricing
                orderbook = self.get_orderbook(symbol)
                
                if side.upper() == 'BUY':
                    # For BUY orders, use best bid (or slightly above)
                    optimal_price = orderbook['best_bid']
                    if optimal_price == 0.0:
                        optimal_price = self.get_current_price(symbol)
                else:
                    # For SELL orders, use best ask (or slightly below)  
                    optimal_price = orderbook['best_ask']
                    if optimal_price == 0.0:
                        optimal_price = self.get_current_price(symbol)
                
                logger.debug(f"🎯 [MAINNET] Optimal {side} price for {symbol}: ${optimal_price:.2f}")
                return optimal_price
                
        except Exception as e:
            logger.error(f"❌ [MAINNET] Failed to calculate optimal price for {symbol}: {e}")
            # Fallback to current price
            return self.get_current_price(symbol)
    
    def calculate_pnl(self, side, entry_price, exit_price, quantity):
        """
        Calculate P&L using MAINNET prices ONLY
        This ensures accurate P&L regardless of testnet fill prices
        """
        try:
            if side.upper() == 'LONG':
                pnl = (exit_price - entry_price) * quantity
            else:  # SHORT
                pnl = (entry_price - exit_price) * quantity
            
            logger.debug(f"💰 [MAINNET PNL] {side} {quantity} @ ${entry_price:.2f} -> ${exit_price:.2f} = ${pnl:.4f}")
            return pnl
            
        except Exception as e:
            logger.error(f"❌ Failed to calculate P&L: {e}")
            return 0.0
    
    def get_price_info(self, symbol):
        """Get comprehensive price information from MAINNET"""
        try:
            current_price = self.get_current_price(symbol)
            orderbook = self.get_orderbook(symbol)
            
            return {
                'symbol': symbol,
                'price': current_price,
                'best_bid': orderbook['best_bid'],
                'best_ask': orderbook['best_ask'],
                'spread': orderbook['best_ask'] - orderbook['best_bid'],
                'spread_pct': ((orderbook['best_ask'] - orderbook['best_bid']) / current_price * 100) if current_price > 0 else 0,
                'timestamp': time.time()
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to get price info for {symbol}: {e}")
            return None

# Global instance - single source of truth for prices
_mainnet_price_provider = None

def get_price_provider():
    """Get the global mainnet price provider instance"""
    global _mainnet_price_provider
    if _mainnet_price_provider is None:
        _mainnet_price_provider = MainnetPriceProvider()
    return _mainnet_price_provider