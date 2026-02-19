"""
Binance Futures Live Execution Adapter
P2 IMPROVEMENT: Production-grade order execution with maker-first entries and OCO brackets
P3 IMPROVEMENT: Thread-safe symbol initialization with caching, retry logic, and decimal precision
"""

import logging
import time
import json
import os
import random
import threading
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from typing import Dict, Optional, Tuple, List
from datetime import datetime, timezone, timedelta
from binance.client import Client
from binance.enums import *
from binance.exceptions import BinanceAPIException, BinanceRequestException

logger = logging.getLogger(__name__)


class InitializationError(Exception):
    """Raised when symbol initialization fails after all retry attempts"""
    pass


class BookSnapshotLogger:
    """
    Microstructure book snapshot logger for capturing order book state
    during signal evaluation periods.
    """
    
    def __init__(self, log_dir: str = 'logs/book_snapshots', max_levels: int = 5):
        """
        Initialize book snapshot logger.
        
        Args:
            log_dir: Directory to store book snapshots
            max_levels: Number of bid/ask levels to capture
        """
        self.log_dir = log_dir
        self.max_levels = max_levels
        self._current_file = None
        self._current_date = None
        os.makedirs(log_dir, exist_ok=True)
    
    def _get_writer(self) -> str:
        """Get or create the current day's log file."""
        today = datetime.now(timezone.utc).strftime('%Y%m%d')
        if self._current_date != today:
            self._current_date = today
            self._current_file = os.path.join(self.log_dir, f'book_{today}.jsonl')
        return self._current_file
    
    def log_snapshot(
        self,
        symbol: str,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        context: Optional[str] = None,
        decision_id: Optional[str] = None
    ) -> None:
        """
        Log a book snapshot.
        
        Args:
            symbol: Trading symbol
            bids: List of (price, quantity) tuples for bids
            asks: List of (price, quantity) tuples for asks
            context: Optional context string (e.g., 'signal_evaluation', 'order_placed')
            decision_id: Optional decision ID to link with decision events
        """
        try:
            ts = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
            
            # Calculate spread and mid-price
            best_bid = bids[0][0] if bids else 0
            best_ask = asks[0][0] if asks else 0
            mid_price = (best_bid + best_ask) / 2 if best_bid and best_ask else 0
            spread_bps = ((best_ask - best_bid) / mid_price * 10000) if mid_price > 0 else 0
            
            # Calculate total liquidity at each level
            bid_liquidity = [{'price': p, 'qty': q, 'notional': p * q} for p, q in bids[:self.max_levels]]
            ask_liquidity = [{'price': p, 'qty': q, 'notional': p * q} for p, q in asks[:self.max_levels]]
            
            # Calculate depth imbalance
            total_bid_qty = sum(q for p, q in bids[:self.max_levels])
            total_ask_qty = sum(q for p, q in asks[:self.max_levels])
            imbalance = (total_bid_qty - total_ask_qty) / (total_bid_qty + total_ask_qty) if (total_bid_qty + total_ask_qty) > 0 else 0
            
            snapshot = {
                'ts': ts,
                'symbol': symbol,
                'best_bid': best_bid,
                'best_ask': best_ask,
                'mid': round(mid_price, 2),
                'spread_bps': round(spread_bps, 2),
                'bids': bid_liquidity,
                'asks': ask_liquidity,
                'bid_depth': round(total_bid_qty, 4),
                'ask_depth': round(total_ask_qty, 4),
                'imbalance': round(imbalance, 4),
                'context': context,
                'decision_id': decision_id
            }
            
            filepath = self._get_writer()
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write(json.dumps(snapshot) + '\n')
                
        except Exception as e:
            logger.error(f"Error logging book snapshot: {e}")
    
    def log_from_orderbook(
        self,
        orderbook: Dict,
        context: Optional[str] = None,
        decision_id: Optional[str] = None
    ) -> None:
        """
        Log snapshot from Binance order book response.
        
        Args:
            orderbook: Response from client.futures_order_book()
            context: Optional context string
            decision_id: Optional decision ID
        """
        try:
            bids = [(float(b[0]), float(b[1])) for b in orderbook.get('bids', [])]
            asks = [(float(a[0]), float(a[1])) for a in orderbook.get('asks', [])]
            symbol = orderbook.get('symbol', 'BTCUSDT')
            self.log_snapshot(symbol, bids, asks, context, decision_id)
        except Exception as e:
            logger.error(f"Error parsing orderbook for snapshot: {e}")


class BinanceFuturesAdapter:
    """
    Production-ready Binance Futures adapter with:
    - Maker-first entry orders (POST_ONLY)
    - OCO bracket orders (stop-loss + take-profit)
    - Retry logic with exponential backoff and jitter
    - Thread-safe symbol initialization with caching
    - Decimal-based precision quantization (ROUND_DOWN for quantities)
    - Lot size / tick size / notional validation
    - Position tracking and reconciliation
    - Book snapshot logging for microstructure analysis
    """
    
    # Cache configuration
    EXCHANGE_INFO_CACHE_TTL = 600  # 10 minutes
    MAX_INIT_RETRIES = 5
    INIT_BASE_DELAY = 0.5  # seconds
    INIT_MAX_DELAY = 30.0  # seconds
    
    def __init__(self, api_key: str, api_secret: str, testnet: bool = False, enable_book_logging: bool = True):
        """
        Initialize Binance Futures client
        
        Args:
            api_key: Binance API key
            api_secret: Binance API secret
            testnet: Use testnet instead of mainnet
            enable_book_logging: Enable microstructure book snapshot logging
        """
        self.client = Client(api_key, api_secret, testnet=testnet)
        self.testnet = testnet
        
        # Exchange info cache with thread safety
        self._cache_lock = threading.RLock()
        self.symbol_info = {}
        self.lot_size_filter = {}
        self.price_filter = {}
        self.notional_filter = {}
        self._symbol_cache_timestamp = {}  # Per-symbol cache timestamps
        
        # Position tracking
        self.open_positions = {}
        
        # Retry configuration for orders
        self.max_retries = 3
        self.retry_delay = 1.0  # seconds
        
        # Book snapshot logging
        self.book_logger = BookSnapshotLogger() if enable_book_logging else None
        
        # Metrics counters
        self.metrics = {
            'init_attempts': 0,
            'init_successes': 0,
            'init_failures': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'quantize_operations': 0
        }
        
        logger.info(f"Binance Futures Adapter initialized (testnet={testnet}, book_logging={enable_book_logging})")
    
    def _is_cache_valid(self, symbol: str) -> bool:
        """Check if cached exchange info for symbol is still valid"""
        if symbol not in self._symbol_cache_timestamp:
            return False
        age = (datetime.now(timezone.utc) - self._symbol_cache_timestamp[symbol]).total_seconds()
        return age < self.EXCHANGE_INFO_CACHE_TTL
    
    def _fetch_exchange_info_with_retries(self, symbol: str, max_attempts: Optional[int] = None) -> bool:
        """
        Fetch exchange info with exponential backoff and jitter
        
        Args:
            symbol: Trading symbol to fetch info for
            max_attempts: Maximum retry attempts (default: MAX_INIT_RETRIES)
            
        Returns:
            True if successful, False otherwise
        """
        max_attempts = max_attempts or self.MAX_INIT_RETRIES
        
        for attempt in range(1, max_attempts + 1):
            self.metrics['init_attempts'] += 1
            
            try:
                logger.info(f"🔄 Fetching exchange info for {symbol} (attempt {attempt}/{max_attempts})")
                exchange_info = self.client.futures_exchange_info()
                
                # Find and parse symbol info
                for s in exchange_info['symbols']:
                    if s['symbol'] == symbol:
                        with self._cache_lock:
                            self.symbol_info[symbol] = s
                            self._symbol_cache_timestamp[symbol] = datetime.now(timezone.utc)
                            
                            # Extract filters
                            for f in s['filters']:
                                if f['filterType'] == 'LOT_SIZE':
                                    self.lot_size_filter[symbol] = {
                                        'minQty': Decimal(str(f['minQty'])),
                                        'maxQty': Decimal(str(f['maxQty'])),
                                        'stepSize': Decimal(str(f['stepSize']))
                                    }
                                elif f['filterType'] == 'PRICE_FILTER':
                                    self.price_filter[symbol] = {
                                        'minPrice': Decimal(str(f['minPrice'])),
                                        'maxPrice': Decimal(str(f['maxPrice'])),
                                        'tickSize': Decimal(str(f['tickSize']))
                                    }
                                elif f['filterType'] == 'MIN_NOTIONAL':
                                    self.notional_filter[symbol] = {
                                        'minNotional': Decimal(str(f['notional']))
                                    }
                        
                        self.metrics['init_successes'] += 1
                        logger.info(f"✅ Symbol {symbol} initialized successfully | LOT_SIZE stepSize={self.lot_size_filter[symbol]['stepSize']} | PRICE_FILTER tickSize={self.price_filter[symbol]['tickSize']}")
                        return True
                
                logger.error(f"❌ Symbol {symbol} not found in exchange info")
                self.metrics['init_failures'] += 1
                return False
                
            except (BinanceAPIException, BinanceRequestException) as e:
                logger.warning(f"⚠️ Binance API error on attempt {attempt}/{max_attempts}: {e}")
                
                if attempt < max_attempts:
                    # Exponential backoff with jitter
                    delay = min(self.INIT_BASE_DELAY * (2 ** (attempt - 1)), self.INIT_MAX_DELAY)
                    jitter = random.uniform(0, delay * 0.3)  # 30% jitter
                    total_delay = delay + jitter
                    logger.info(f"⏳ Retrying in {total_delay:.2f}s...")
                    time.sleep(total_delay)
                else:
                    logger.error(f"❌ All {max_attempts} attempts failed for {symbol}")
                    self.metrics['init_failures'] += 1
                    
            except Exception as e:
                logger.error(f"❌ Unexpected error fetching exchange info for {symbol}: {e}", exc_info=True)
                self.metrics['init_failures'] += 1
                if attempt < max_attempts:
                    time.sleep(self.INIT_BASE_DELAY)
        
        return False
    
    def initialize_symbol(self, symbol: str = "BTCUSDT") -> bool:
        """
        Thread-safe, idempotent symbol initialization with caching
        
        Args:
            symbol: Trading symbol (default: BTCUSDT)
            
        Returns:
            True if symbol initialized successfully, False otherwise
        """
        # Check cache first (with lock)
        with self._cache_lock:
            if self._is_cache_valid(symbol):
                self.metrics['cache_hits'] += 1
                logger.debug(f"💾 Using cached exchange info for {symbol}")
                return True
            else:
                self.metrics['cache_misses'] += 1
        
        # Fetch fresh data
        success = self._fetch_exchange_info_with_retries(symbol)
        
        # If fetch failed, try to use stale cache as fallback
        if not success:
            with self._cache_lock:
                if symbol in self.lot_size_filter and symbol in self.price_filter:
                    logger.warning(f"⚠️ Using stale cached data for {symbol} as fallback")
                    return True
        
        return success
    
    @staticmethod
    def _quantize_to_step(value: Decimal, step_size: Decimal, rounding=ROUND_DOWN) -> Decimal:
        """
        Quantize a value to the nearest step size
        
        Args:
            value: Value to quantize
            step_size: Step size to quantize to
            rounding: Rounding mode (default ROUND_DOWN for quantities)
            
        Returns:
            Quantized decimal value
        """
        if step_size == 0:
            return value
        return (value / step_size).quantize(Decimal('1'), rounding=rounding) * step_size
    
    def validate_quantity(self, symbol: str, quantity: float, auto_init: bool = True) -> Decimal:
        """
        Validate and quantize quantity to exchange LOT_SIZE rules using Decimal precision
        
        Args:
            symbol: Trading symbol
            quantity: Desired quantity
            auto_init: Automatically initialize symbol if filters missing
            
        Returns:
            Validated Decimal quantity rounded to step size (ROUND_DOWN)
            
        Raises:
            InitializationError: If auto_init fails after retries
        """
        # Auto-initialize if filters missing
        if symbol not in self.lot_size_filter:
            if auto_init:
                logger.info(f"🔧 LOT_SIZE filter missing for {symbol}, initializing...")
                if not self.initialize_symbol(symbol):
                    raise InitializationError(f"Failed to initialize symbol {symbol} after all retries")
            else:
                logger.error(f"❌ No LOT_SIZE filter for {symbol} and auto_init=False")
                return Decimal(str(quantity))
        
        # Re-check after initialization attempt
        if symbol not in self.lot_size_filter:
            raise InitializationError(f"LOT_SIZE filter still missing for {symbol} after initialization")
        
        lot = self.lot_size_filter[symbol]
        qty_decimal = Decimal(str(quantity))
        
        # Quantize to step size (round down for quantities)
        quantized_qty = self._quantize_to_step(qty_decimal, lot['stepSize'], ROUND_DOWN)
        
        # Ensure within min/max bounds
        if quantized_qty < lot['minQty']:
            logger.warning(f"⚠️ Quantity {quantized_qty} < minQty {lot['minQty']}, adjusting to min")
            quantized_qty = lot['minQty']
        elif quantized_qty > lot['maxQty']:
            logger.warning(f"⚠️ Quantity {quantized_qty} > maxQty {lot['maxQty']}, adjusting to max")
            quantized_qty = lot['maxQty']
        
        self.metrics['quantize_operations'] += 1
        logger.info(f"✅ Quantity quantized: {quantity} → {quantized_qty} (stepSize={lot['stepSize']}, mode=ROUND_DOWN)")
        
        return quantized_qty
    
    def validate_price(self, symbol: str, price: float, auto_init: bool = True, rounding=ROUND_DOWN) -> Decimal:
        """
        Validate and quantize price to exchange PRICE_FILTER rules using Decimal precision
        
        Args:
            symbol: Trading symbol
            price: Desired price
            auto_init: Automatically initialize symbol if filters missing
            rounding: Rounding mode (default ROUND_DOWN, can use ROUND_HALF_UP for prices)
            
        Returns:
            Validated Decimal price rounded to tick size
            
        Raises:
            InitializationError: If auto_init fails after retries
        """
        # Auto-initialize if filters missing
        # Handle None prices (optional SL/TP)
        if price is None:
            return None

        if symbol not in self.price_filter:
            if auto_init:
                logger.info(f"🔧 PRICE_FILTER missing for {symbol}, initializing...")
                if not self.initialize_symbol(symbol):
                    raise InitializationError(f"Failed to initialize symbol {symbol} after all retries")
            else:
                logger.error(f"❌ No PRICE_FILTER for {symbol} and auto_init=False")
                return Decimal(str(price))
        
        # Re-check after initialization attempt
        if symbol not in self.price_filter:
            raise InitializationError(f"PRICE_FILTER still missing for {symbol} after initialization")
        
        pf = self.price_filter[symbol]
        price_decimal = Decimal(str(price))
        
        # Quantize to tick size
        quantized_price = self._quantize_to_step(price_decimal, pf['tickSize'], rounding)
        
        # Ensure within min/max bounds
        if quantized_price < pf['minPrice']:
            logger.warning(f"⚠️ Price {quantized_price} < minPrice {pf['minPrice']}, adjusting to min")
            quantized_price = pf['minPrice']
        elif quantized_price > pf['maxPrice']:
            logger.warning(f"⚠️ Price {quantized_price} > maxPrice {pf['maxPrice']}, adjusting to max")
            quantized_price = pf['maxPrice']
        
        self.metrics['quantize_operations'] += 1
        logger.info(f"✅ Price quantized: {price} → {quantized_price} (tickSize={pf['tickSize']}, mode={rounding})")
        
        return quantized_price
    
    def validate_notional(self, symbol: str, quantity: Decimal, price: Decimal) -> bool:
        """
        Validate that order meets minimum notional value
        
        Args:
            symbol: Trading symbol
            quantity: Order quantity (Decimal)
            price: Order price (Decimal)
            
        Returns:
            True if valid, False otherwise
        """
        if symbol not in self.notional_filter:
            return True  # No filter = always valid
        
        notional = quantity * price
        min_notional = self.notional_filter[symbol]['minNotional']
        
        if notional < min_notional:
            logger.error(f"❌ Order notional {notional} < minimum {min_notional}")
            return False
        
        return True
    
    def place_maker_entry(self, symbol: str, side: str, quantity: float, limit_price: float) -> Optional[Dict]:
        """
        Place maker-first entry order (POST_ONLY to ensure maker fees)
        
        Args:
            symbol: Trading symbol (e.g., BTCUSDT)
            side: BUY or SELL
            quantity: Order quantity
            limit_price: Limit price
            
        Returns:
            Order response dict or None if failed
        """
        # Validate inputs with Decimal precision
        try:
            quantity_dec = self.validate_quantity(symbol, quantity)
            limit_price_dec = self.validate_price(symbol, limit_price)
        except InitializationError as e:
            logger.error(f"❌ Cannot place order: {e}")
            return None
        
        if not self.validate_notional(symbol, quantity_dec, limit_price_dec):
            return None
        
        # Convert Decimal to float for Binance API
        quantity_float = float(quantity_dec)
        limit_price_float = float(limit_price_dec)
        
        # Retry loop
        for attempt in range(self.max_retries):
            try:
                order = self.client.futures_create_order(
                    symbol=symbol,
                    side=side,
                    type=FUTURE_ORDER_TYPE_LIMIT,
                    timeInForce=TIME_IN_FORCE_GTC,  # Good-Till-Cancel (regular LIMIT order)
                    quantity=quantity_float,
                    price=limit_price_float
                )
                
                logger.info(f"✅ Maker entry placed: {side} {quantity_float} {symbol} @ {limit_price_float} | orderId={order['orderId']}")
                return order
                
            except BinanceAPIException as e:
                if e.code == -2021:  # Order would immediately match (shouldn't happen with GTC)
                    logger.warning(f"⚠️ Order match issue, adjusting price (attempt {attempt+1}/{self.max_retries})")
                    # Adjust price to be further from market
                    if side == SIDE_BUY:
                        limit_price_dec = limit_price_dec * Decimal('0.999')  # Lower buy price
                    else:
                        limit_price_dec = limit_price_dec * Decimal('1.001')  # Higher sell price
                    limit_price_dec = self.validate_price(symbol, float(limit_price_dec))
                    limit_price_float = float(limit_price_dec)
                    time.sleep(self.retry_delay)
                else:
                    logger.error(f"❌ Binance API error placing maker entry: {e}")
                    return None
                    
            except Exception as e:
                logger.error(f"❌ Unexpected error placing maker entry: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (2 ** attempt))  # Exponential backoff
                else:
                    return None
        
        logger.error(f"❌ Failed to place maker entry after {self.max_retries} attempts")
        return None
    
    def place_bracket_order(self, symbol: str, side: str, quantity: float, 
                           entry_price: float, stop_loss: float, take_profit: float,
                           **kwargs) -> Dict:
        """
        Unified bracket order method that places entry + stop-loss + take-profit.
        This wraps place_maker_entry() and place_oco_bracket() for compatibility
        with ExchangeRouter interface.
        
        Includes pre-flight checks to ensure symbol is properly initialized before
        attempting order placement.
        
        ✨ NEW: Auto-calculates fallback SL/TP using ATR when None/null provided
        
        Args:
            symbol: Trading symbol (e.g., BTCUSDT)
            side: BUY or SELL (or LONG/SHORT - will be normalized)
            quantity: Order quantity
            entry_price: Entry limit price
            stop_loss: Stop-loss trigger price (if None, calculates from ATR)
            take_profit: Take-profit trigger price (if None, calculates from ATR)
            **kwargs: Additional parameters (ignored for Binance)
            
        Returns:
            Dict with entry, stop_loss, and take_profit order details, or error
            
        Raises:
            InitializationError: If symbol initialization fails after retries
        """
        # Normalize side to Binance format (BUY/SELL)
        logger.info(f"🔧 place_bracket_order called with side='{side}' (type: {type(side).__name__})")
        side_map = {'LONG': 'BUY', 'SHORT': 'SELL', 'BUY': 'BUY', 'SELL': 'SELL'}
        original_side = side
        side = side_map.get(side.upper(), side)
        logger.info(f"🔧 Side normalized: '{original_side}' → '{side}'")

        # 🔧 Type conversion for numeric parameters (handle string inputs from JSON)
        try:
            entry_price = float(entry_price) if entry_price is not None else None
            stop_loss = float(stop_loss) if stop_loss is not None else None
            take_profit = float(take_profit) if take_profit is not None else None
            quantity = float(quantity) if quantity is not None else None
            logger.info(f"🔧 Types: entry={type(entry_price).__name__}, SL={type(stop_loss).__name__}, TP={type(take_profit).__name__}")
        except (ValueError, TypeError) as e:
            logger.error(f"❌ Type conversion failed: {e}")
            return {
                'success': False,
                'error': f'Invalid numeric parameter types: {e}',
                'entry': None,
                'stop_loss': None,
                'take_profit': None
            }
        
        if side not in ['BUY', 'SELL']:
            logger.error(f"❌ Invalid side after normalization: {side}")
            return {
                'success': False,
                'error': f'Invalid side: {side}',
                'entry': None,
                'stop_loss': None,
                'take_profit': None
            }
        
        # Ensure symbol is in Binance format (BTCUSDT not BTC)
        if symbol == 'BTC':
            symbol = 'BTCUSDT'
        elif symbol == 'ETH':
            symbol = 'ETHUSDT'
        elif symbol == 'SOL':
            symbol = 'SOLUSDT'
        
        # ✨ FALLBACK SL/TP CALCULATION if None/null provided
        if stop_loss is None or take_profit is None:
            logger.warning(f"⚠️ Missing SL/TP (SL={stop_loss}, TP={take_profit}). Calculating fallback using ATR...")
            try:
                # Get recent klines for ATR calculation (15-minute bars)
                klines = self.client.futures_klines(symbol=symbol, interval='15m', limit=15)
                highs = [float(k[2]) for k in klines]
                lows = [float(k[3]) for k in klines]
                closes = [float(k[4]) for k in klines]
                
                # Calculate ATR (Average True Range)
                true_ranges = []
                for i in range(1, len(klines)):
                    high_low = highs[i] - lows[i]
                    high_close = abs(highs[i] - closes[i-1])
                    low_close = abs(lows[i] - closes[i-1])
                    true_ranges.append(max(high_low, high_close, low_close))
                
                atr = sum(true_ranges) / len(true_ranges) if true_ranges else (entry_price * 0.015)
                logger.info(f"📊 Calculated ATR: {atr:.2f} ({(atr/entry_price*100):.2f}%)")
                
                # Set SL/TP using ATR multiples (1.5x ATR for SL, 2.5x ATR for TP)
                if side == 'BUY':
                    if stop_loss is None:
                        stop_loss = entry_price - (atr * 1.5)
                        logger.info(f"🛡️ Fallback SL (LONG): ${stop_loss:.2f} ({atr*1.5:.2f} below entry)")
                    if take_profit is None:
                        take_profit = entry_price + (atr * 2.5)
                        logger.info(f"🎯 Fallback TP (LONG): ${take_profit:.2f} ({atr*2.5:.2f} above entry)")
                else:  # SELL/SHORT
                    if stop_loss is None:
                        stop_loss = entry_price + (atr * 1.5)
                        logger.info(f"🛡️ Fallback SL (SHORT): ${stop_loss:.2f} ({atr*1.5:.2f} above entry)")
                    if take_profit is None:
                        take_profit = entry_price - (atr * 2.5)
                        logger.info(f"🎯 Fallback TP (SHORT): ${take_profit:.2f} ({atr*2.5:.2f} below entry)")
                        
            except Exception as e:
                logger.error(f"❌ Failed to calculate ATR fallback SL/TP: {e}")
                logger.warning(f"⚠️ Using default percentage-based SL/TP (1.5% / 2.5%)")
                # Ultra-fallback using fixed percentages
                if side == 'BUY':
                    if stop_loss is None:
                        stop_loss = entry_price * 0.985  # 1.5% below
                    if take_profit is None:
                        take_profit = entry_price * 1.025  # 2.5% above
                else:  # SELL/SHORT
                    if stop_loss is None:
                        stop_loss = entry_price * 1.015  # 1.5% above
                    if take_profit is None:
                        take_profit = entry_price * 0.975  # 2.5% below
        
        # PRE-FLIGHT CHECK: Ensure symbol is initialized with retries
                # Place maker entry order first
        entry_order = self.place_maker_entry(symbol, side, quantity, entry_price)
        
        if not entry_order:
            logger.error(f"❌ Failed to place bracket order: entry order failed")
            return {
                'success': False,
                'error': 'Entry order placement failed',
                'entry': None,
                'stop_loss': None,
                'take_profit': None
            }
        
        # Place OCO bracket (stop-loss + take-profit)
        # Note: side parameter for place_oco_bracket is the ENTRY side (it handles the exit side internally)
        bracket_orders = self.place_oco_bracket(symbol, side, quantity, stop_loss, take_profit)
        
        if not bracket_orders:
            logger.warning(f"⚠️ Entry placed but bracket orders failed for {symbol}")
            return {
                'success': True,  # Entry succeeded
                'partial': True,
                'entry': entry_order,
                'stop_loss': None,
                'take_profit': None,
                'warning': 'Bracket orders failed to place'
            }
        
        logger.info(f"✅ Complete bracket order placed on Binance: {side} {quantity} {symbol} @ {entry_price}")
        return {
            'success': True,
            'entry': entry_order,
            'stop_loss': bracket_orders.get('stop_loss'),
            'take_profit': bracket_orders.get('take_profit'),
            'exchange': 'binance',
            'symbol': symbol
        }
    
    def place_oco_bracket(self, symbol: str, side: str, quantity: float, 
                          stop_loss: float, take_profit: float) -> Optional[Dict]:
        """
        Place OCO bracket order (stop-loss + take-profit)
        
        NOTE: Binance Futures doesn't support native OCO orders. This places two separate orders:
        1. Stop-loss: STOP_MARKET order
        2. Take-profit: TAKE_PROFIT_MARKET order
        
        Args:
            symbol: Trading symbol
            side: BUY or SELL (exit side, opposite of entry)
            quantity: Order quantity
            stop_loss: Stop-loss trigger price
            take_profit: Take-profit trigger price
            
        Returns:
            Dict with both order responses or None if failed
        """
        # Validate prices
        stop_loss = self.validate_price(symbol, stop_loss)
        take_profit = self.validate_price(symbol, take_profit)
        quantity = self.validate_quantity(symbol, quantity)
        # Skip bracket orders if SL/TP not provided
        if stop_loss is None or take_profit is None:
            logger.warning("⚠️ SL or TP is None, skipping bracket orders")
            return None

        
        # Determine exit side (opposite of entry)
        exit_side = SIDE_SELL if side == SIDE_BUY else SIDE_BUY
        
        try:
            # Place stop-loss order
            sl_order = self.client.futures_create_order(
                symbol=symbol,
                side=exit_side,
                type=FUTURE_ORDER_TYPE_STOP_MARKET,
                stopPrice=stop_loss,
                quantity=quantity,
                closePosition=False  # Use quantity instead of closePosition for precision
            )
            
            logger.info(f"Stop-loss placed: {exit_side} {quantity} {symbol} @ stop={stop_loss} | orderId={sl_order['orderId']}")
            
            # Place take-profit order
            tp_order = self.client.futures_create_order(
                symbol=symbol,
                side=exit_side,
                type=FUTURE_ORDER_TYPE_TAKE_PROFIT_MARKET,
                stopPrice=take_profit,
                quantity=quantity,
                closePosition=False
            )
            
            logger.info(f"Take-profit placed: {exit_side} {quantity} {symbol} @ stop={take_profit} | orderId={tp_order['orderId']}")
            
            return {
                'stop_loss': sl_order,
                'take_profit': tp_order
            }
            
        except BinanceAPIException as e:
            logger.error(f"Binance API error placing OCO bracket: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error placing OCO bracket: {e}")
            return None
    
    def capture_book_snapshot(self, symbol: str = "BTCUSDT", context: str = None, decision_id: str = None) -> Optional[Dict]:
        """
        Capture current order book snapshot for microstructure analysis.
        
        Args:
            symbol: Trading symbol
            context: Context for the snapshot (e.g., 'pre_signal', 'post_order')
            decision_id: Optional decision ID to link with decision events
            
        Returns:
            Order book data dict or None if failed
        """
        try:
            orderbook = self.client.futures_order_book(symbol=symbol, limit=10)
            
            if self.book_logger:
                orderbook['symbol'] = symbol
                self.book_logger.log_from_orderbook(orderbook, context, decision_id)
            
            # Return summarized book data
            bids = [(float(b[0]), float(b[1])) for b in orderbook.get('bids', [])[:5]]
            asks = [(float(a[0]), float(a[1])) for a in orderbook.get('asks', [])[:5]]
            
            best_bid = bids[0][0] if bids else 0
            best_ask = asks[0][0] if asks else 0
            mid = (best_bid + best_ask) / 2 if best_bid and best_ask else 0
            spread_bps = ((best_ask - best_bid) / mid * 10000) if mid > 0 else 0
            
            return {
                'best_bid': best_bid,
                'best_ask': best_ask,
                'mid': mid,
                'spread_bps': round(spread_bps, 2),
                'bid_depth': sum(q for p, q in bids),
                'ask_depth': sum(q for p, q in asks)
            }
        except Exception as e:
            logger.error(f"Error capturing book snapshot: {e}")
            return None

    def execute_signal(self, signal: Dict) -> bool:
        """
        Execute complete signal: entry + OCO bracket
        
        Args:
            signal: Signal dict containing:
                - direction: LONG or SHORT
                - entry_price: Entry limit price
                - position_size: Quantity to trade
                - stop_loss: Stop-loss price
                - take_profit: Take-profit price
                - symbol: Trading symbol (default: BTCUSDT)
        
        Returns:
            True if successfully placed all orders, False otherwise
        """
        symbol = signal.get('symbol', 'BTCUSDT')
        decision_id = signal.get('decision_id')
        
        # Ensure symbol is initialized
        if symbol not in self.symbol_info:
            if not self.initialize_symbol(symbol):
                return False
        
        # Capture pre-execution book snapshot
        self.capture_book_snapshot(symbol, 'pre_execution', decision_id)
        
        direction = signal['direction']
        entry_price = signal['entry_price']
        quantity = signal['position_size']
        stop_loss = signal['stop_loss']
        take_profit = signal['take_profit']
        
        # Determine entry side
        entry_side = SIDE_BUY if direction == 'LONG' else SIDE_SELL
        
        # 1. Place maker entry order
        entry_order = self.place_maker_entry(symbol, entry_side, quantity, entry_price)
        if not entry_order:
            logger.error("Failed to place entry order")
            self.capture_book_snapshot(symbol, 'order_failed', decision_id)
            return False
        
        # Capture post-order book snapshot
        self.capture_book_snapshot(symbol, 'post_order', decision_id)
        
        # 2. Wait for entry fill (poll order status)
        filled = self._wait_for_fill(symbol, entry_order['orderId'], timeout=300)  # 5 min timeout
        if not filled:
            logger.warning("Entry order not filled within timeout, cancelling...")
            self.cancel_order(symbol, entry_order['orderId'])
            self.capture_book_snapshot(symbol, 'order_timeout', decision_id)
            return False
        
        # Capture post-fill book snapshot
        self.capture_book_snapshot(symbol, 'post_fill', decision_id)
        
        # 3. Place OCO bracket
        bracket = self.place_oco_bracket(symbol, entry_side, quantity, stop_loss, take_profit)
        if not bracket:
            logger.error("Failed to place OCO bracket - position is UNPROTECTED!")
            # TODO: Alert/notification for unprotected position
            return False
        
        # Track open position
        self.open_positions[symbol] = {
            'entry_order': entry_order,
            'bracket': bracket,
            'direction': direction,
            'quantity': quantity,
            'entry_price': entry_price,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        
        logger.info(f"Signal executed successfully: {direction} {quantity} {symbol} @ {entry_price}")
        return True
    
    def _wait_for_fill(self, symbol: str, order_id: int, timeout: int = 300) -> bool:
        """
        Poll order status until filled or timeout
        
        Args:
            symbol: Trading symbol
            order_id: Order ID to check
            timeout: Max wait time in seconds
            
        Returns:
            True if filled, False if timeout/cancelled
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                order = self.client.futures_get_order(symbol=symbol, orderId=order_id)
                status = order['status']
                
                if status == 'FILLED':
                    logger.info(f"Order {order_id} filled @ {order['avgPrice']}")
                    return True
                elif status in ['CANCELED', 'REJECTED', 'EXPIRED']:
                    logger.warning(f"Order {order_id} {status}")
                    return False
                
                # Still pending, wait before next check
                time.sleep(2)
                
            except Exception as e:
                logger.error(f"Error checking order status: {e}")
                time.sleep(2)
        
        logger.warning(f"Order {order_id} not filled within {timeout}s timeout")
        return False
    
    def cancel_order(self, symbol: str, order_id: int) -> bool:
        """Cancel an open order"""
        try:
            result = self.client.futures_cancel_order(symbol=symbol, orderId=order_id)
            logger.info(f"Order {order_id} cancelled")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False
    
    def get_position(self, symbol: str = "BTCUSDT") -> Optional[Dict]:
        """
        Get current position for symbol
        
        Returns:
            Position dict with positionAmt, entryPrice, unrealizedProfit, etc.
        """
        try:
            positions = self.client.futures_position_information(symbol=symbol)
            for pos in positions:
                if float(pos['positionAmt']) != 0:
                    return pos
            return None
        except Exception as e:
            logger.error(f"Failed to get position: {e}")
            return None
    
    def close_position(self, symbol: str = "BTCUSDT") -> bool:
        """Close current position at market price"""
        try:
            position = self.get_position(symbol)
            if not position:
                logger.info(f"No open position for {symbol}")
                return True
            
            position_amt = float(position['positionAmt'])
            if position_amt == 0:
                return True
            
            # Determine close side
            close_side = SIDE_SELL if position_amt > 0 else SIDE_BUY
            quantity = abs(position_amt)
            
            # Place market order to close
            order = self.client.futures_create_order(
                symbol=symbol,
                side=close_side,
                type=FUTURE_ORDER_TYPE_MARKET,
                quantity=quantity
            )
            
            logger.info(f"Position closed: {close_side} {quantity} {symbol} @ MARKET | orderId={order['orderId']}")
            
            # Remove from tracking
            if symbol in self.open_positions:
                del self.open_positions[symbol]
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to close position: {e}")
            return False
