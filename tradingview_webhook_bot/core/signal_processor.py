import json
import os
from datetime import datetime
from utils.logger import setup_logger
from utils.helpers import (
    validate_symbol, validate_timeframe, validate_price, 
    is_signal_expired, generate_signal_id
)
from storage.idempotency_store import IdempotencyStore
from storage.jsonl_consumer import JsonlOffsetConsumer
from utils.event_logger import get_event_logger
from utils.health_checker import get_health_checker

logger = setup_logger('signal_processor')

class SignalProcessor:
    """Process and validate incoming TradingView signals"""
    
    def __init__(self, config, client, strategy_name=None, price_provider=None):
        self.config = config
        self.client = client
        self.price_provider = price_provider  # Mainnet price provider for validation
        self.strategy_name = strategy_name  # Filter signals by strategy
        
        # Get enabled strategies from config
        enabled = config['strategies']['enabled']
        
        # If strategy_name is specified, only enable that one
        if strategy_name:
            self.enabled_strategies = [strategy_name] if strategy_name in enabled else []
        else:
            self.enabled_strategies = enabled
        
        self.allowed_symbols = config['trading']['symbols_allowed']
        self.allowed_timeframes = config['trading']['timeframes_allowed']
        self.signal_expiry = config['strategies']['signal_expiry_seconds']
        
        # Initialize idempotency store (prevents duplicate processing)
        db_path = os.path.join('storage', 'idempotency.db')
        self.idempotency = IdempotencyStore(db_path)
        
        # Initialize event logger
        self.event_logger = get_event_logger()
        
        # Initialize health checker
        self.health_checker = get_health_checker(strategy_name or 'multi_strategy')
        
        logger.info(f"📊 Signal processor initialized (strategy: {strategy_name or 'all'})")
        logger.info(f"   Enabled strategies: {', '.join(self.enabled_strategies)}")
        logger.info(f"   Allowed symbols: {', '.join(self.allowed_symbols)}")
        logger.info(f"   🔒 Idempotency protection: ENABLED")
        if price_provider:
            logger.info(f"   💰 Using MAINNET price provider for validation")
    
    def read_signals(self, queue_file):
        """Read unprocessed signals from queue"""
        signals = []
        
        if not os.path.exists(queue_file):
            return signals
        
        try:
            with open(queue_file, 'r') as f:
                for line in f:
                    try:
                        signal = json.loads(line.strip())
                        if not signal.get('processed', False):
                            signals.append(signal)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"Failed to read signals: {e}")
        
        return signals
    
    def validate_signal(self, signal):
        """Validate signal data"""
        errors = []
        
        # Check strategy
        if signal['strategy'] not in self.enabled_strategies:
            errors.append(f"Strategy '{signal['strategy']}' not enabled")
        
        # Check symbol
        if signal['symbol'] not in self.allowed_symbols:
            errors.append(f"Symbol '{signal['symbol']}' not allowed")
        
        if not validate_symbol(signal['symbol']):
            errors.append(f"Invalid symbol format: {signal['symbol']}")
        
        # Normalize timeframe: Convert numeric-only to minutes format (e.g., "3" -> "3m")
        if signal['timeframe'].isdigit():
            signal['timeframe'] = f"{signal['timeframe']}m"
            logger.info(f"🔧 Normalized timeframe to: {signal['timeframe']}")
        
        # Check timeframe
        if signal['timeframe'] not in self.allowed_timeframes:
            errors.append(f"Timeframe '{signal['timeframe']}' not allowed")
        
        if not validate_timeframe(signal['timeframe']):
            errors.append(f"Invalid timeframe format: {signal['timeframe']}")
        
        # Normalize side: Convert BUY/SELL to LONG/SHORT
        if signal['side'] == 'BUY':
            signal['side'] = 'LONG'
        elif signal['side'] == 'SELL':
            signal['side'] = 'SHORT'
        
        # Check side
        if signal['side'] not in ['LONG', 'SHORT']:
            errors.append(f"Invalid side: {signal['side']}")
        
        # Check price validity using MAINNET price provider if available
        try:
            # Use mainnet price provider for accurate validation, fallback to client
            if self.price_provider:
                current_price = self.price_provider.get_current_price(signal['symbol'])
                price_source = "MAINNET"
            else:
                current_price = self.client.get_current_price(signal['symbol'])
                price_source = "TESTNET"
            
            if current_price > 0:
                if not validate_price(signal['price'], current_price, max_deviation_pct=5.0):
                    errors.append(f"Signal price {signal['price']} deviates >5% from {price_source} ${current_price:.2f}")
                else:
                    logger.debug(f"✓ Price validated: Signal ${signal['price']:.2f} vs {price_source} ${current_price:.2f}")
        except Exception as e:
            logger.warning(f"Could not validate price: {e}")
        
        # Check if expired
        if is_signal_expired(signal['timestamp'], self.signal_expiry):
            errors.append(f"Signal expired (>{self.signal_expiry}s old)")
        
        # Check stop-loss and take-profit
        try:
            price = float(signal['price'])
            sl = float(signal.get('stop_loss', 0))
            tp = float(signal.get('take_profit', 0))
            
            if sl <= 0 or tp <= 0:
                errors.append("Missing or invalid SL/TP")
            elif signal['side'] == 'LONG':
                if sl >= price:
                    errors.append(f"LONG: Stop-loss ${sl:.2f} must be < entry ${price:.2f}")
                if tp <= price:
                    errors.append(f"LONG: Take-profit ${tp:.2f} must be > entry ${price:.2f}")
            elif signal['side'] == 'SHORT':
                if sl <= price:
                    errors.append(f"SHORT: Stop-loss ${sl:.2f} must be > entry ${price:.2f}")
                if tp >= price:
                    errors.append(f"SHORT: Take-profit ${tp:.2f} must be < entry ${price:.2f}")
        except (ValueError, TypeError) as e:
            errors.append(f"Invalid numeric values: {e}")
        
        return len(errors) == 0, errors
    
    def process_signal_with_idempotency(self, signal):
        """
        Process a single signal with idempotency check.
        
        Returns:
            tuple: (is_valid, should_execute, errors)
        """
        signal_id = signal.get('signal_id', 'unknown')
        
        # STEP 1: Check idempotency (have we seen this before?)
        if self.idempotency.seen(
            signal_id=signal_id,
            strategy=signal.get('strategy'),
            side=signal.get('side'),
            symbol=signal.get('symbol'),
            ttl=3600  # Consider duplicates within 1 hour
        ):
            logger.warning(f"🔒 DUPLICATE signal detected: {signal_id} (skipping)")
            # Log duplicate detection event
            self.event_logger.log_duplicate_detected(
                signal_id=signal_id,
                strategy=signal.get('strategy')
            )
            return False, False, ['Duplicate signal (already processed)']
        
        # STEP 2: Validate signal
        is_valid, errors = self.validate_signal(signal)
        
        # Log validation result
        self.event_logger.log_signal_validated(
            signal_id=signal_id,
            valid=is_valid,
            errors=errors if not is_valid else None
        )
        
        if not is_valid:
            logger.warning(f"❌ Invalid signal {signal_id}: {', '.join(errors)}")
            # Mark as seen even if invalid (don't retry invalid signals)
            self.idempotency.seen(signal_id, signal.get('strategy'))
            return False, False, errors
        
        # STEP 3: Mark as seen BEFORE execution (prevents race conditions)
        self.idempotency.seen(
            signal_id=signal_id,
            strategy=signal.get('strategy'),
            side=signal.get('side'),
            symbol=signal.get('symbol'),
            details=f"{signal.get('side')} {signal.get('symbol')} @ {signal.get('price')}"
        )
        
        logger.info(f"✅ Valid signal: {signal_id} | {signal['strategy']} | {signal['side']} {signal['symbol']}")
        return True, True, []
    
    def process_signals_with_consumer(self, queue_file):
        """
        Process signals using offset-based consumer (restart-safe).
        
        Returns:
            list: Validated signals ready for execution
        """
        # Create consumer for this queue
        consumer = JsonlOffsetConsumer(queue_file)
        
        # Check pending signals
        pending = consumer.get_pending_count()
        if pending == 0:
            return []
        
        logger.info(f"📥 Processing {pending} pending signals from queue")
        
        validated_signals = []
        
        def signal_handler(signal):
            """Handler function passed to consumer."""
            is_valid, should_execute, errors = self.process_signal_with_idempotency(signal)
            
            if should_execute:
                validated_signals.append(signal)
                # Increment processed counter
                self.health_checker.increment_signals_processed()
            elif not is_valid:
                # Increment failed counter for invalid signals
                self.health_checker.increment_signals_failed()
            
            # Return True to mark as successfully processed (even if invalid/duplicate)
            return True
        
        # Poll consumer (processes all pending signals)
        stats = consumer.poll(signal_handler, batch_size=100)
        
        logger.info(f"📊 Consumer stats: {stats}")
        
        return validated_signals
    
    def mark_processed(self, signal, queue_file):
        """
        DEPRECATED: Old method that rewrites entire file.
        Use process_signals_with_consumer() instead.
        
        Kept for backward compatibility but should not be used.
        """
        logger.warning("⚠️ mark_processed() is deprecated, use process_signals_with_consumer()")
        try:
            # Read all signals
            signals = []
            with open(queue_file, 'r') as f:
                for line in f:
                    try:
                        s = json.loads(line.strip())
                        if s['signal_id'] == signal['signal_id']:
                            s['processed'] = True
                            s['processed_at'] = datetime.utcnow().isoformat()
                        signals.append(s)
                    except json.JSONDecodeError:
                        continue
            
            # Write back
            with open(queue_file, 'w') as f:
                for s in signals:
                    f.write(json.dumps(s) + '\n')
            
            logger.debug(f"✓ Marked signal {signal['signal_id']} as processed")
        except Exception as e:
            logger.error(f"Failed to mark signal as processed: {e}")
    
    def process_signals(self, queue_file):
        """
        Process all unprocessed signals.
        
        This method now uses the new offset-based consumer + idempotency checks.
        
        Returns:
            list: Validated signals ready for execution
        """
        return self.process_signals_with_consumer(queue_file)
