"""
EventLogger - Comprehensive Event Tracking for Production Trading System

Tracks all events in the signal-to-execution pipeline with structured logging:
- Signal reception (webhook hits)
- Signal validation (pass/fail with reasons)
- Idempotency checks (duplicate detection)
- Order placement (entry, SL, TP)
- Order execution (fills, rejections)
- Position updates (P&L tracking)
- Critical failures (exceptions, API errors)

Storage: JSONL format (one event per line) for easy parsing and analysis
Benefits:
- Full audit trail for debugging and compliance
- Performance metrics (latency tracking)
- Error analysis (failure patterns)
- Reconciliation support (position drift detection)
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional
import threading
import logging

logger = logging.getLogger(__name__)


class EventLogger:
    """
    Thread-safe event logger for tracking all trading system events.
    
    Events are written to JSONL files (one JSON object per line) for:
    - Easy parsing with jq or Python
    - Streaming analysis
    - Time-series querying
    - Audit compliance
    """
    
    def __init__(self, log_dir: str = "storage/events"):
        """
        Initialize event logger.
        
        Args:
            log_dir: Directory to store event logs
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Thread lock for atomic writes
        self._lock = threading.Lock()
        
        # Current log file (rotates daily)
        self._current_date = None
        self._current_file = None
        
        logger.info(f"📊 EventLogger initialized: {self.log_dir}")
    
    def _get_log_file(self) -> Path:
        """
        Get current log file path (rotates daily).
        
        Returns:
            Path to current day's event log
        """
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        
        if today != self._current_date:
            self._current_date = today
            self._current_file = self.log_dir / f"events_{today}.jsonl"
        
        return self._current_file
    
    def _write_event(self, event: Dict[str, Any]):
        """
        Write event to JSONL log file (thread-safe).
        
        Args:
            event: Event dictionary to log
        """
        with self._lock:
            log_file = self._get_log_file()
            
            try:
                with open(log_file, 'a', encoding='utf-8') as f:
                    json.dump(event, f, ensure_ascii=False)
                    f.write('\n')
                    f.flush()
            except Exception as e:
                logger.error(f"❌ Failed to write event: {e}")
    
    def log_signal_received(self, signal_id: str, strategy: str, side: str, 
                           symbol: str, metadata: Optional[Dict] = None):
        """
        Log when a signal is received from webhook.
        
        Args:
            signal_id: Unique signal identifier
            strategy: Strategy name
            side: LONG or SHORT
            symbol: Trading symbol
            metadata: Additional signal data
        """
        event = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'event_type': 'signal_received',
            'signal_id': signal_id,
            'strategy': strategy,
            'side': side,
            'symbol': symbol,
            'metadata': metadata or {}
        }
        self._write_event(event)
    
    def log_signal_validated(self, signal_id: str, valid: bool, 
                            errors: Optional[list] = None):
        """
        Log signal validation result.
        
        Args:
            signal_id: Signal identifier
            valid: Whether signal passed validation
            errors: List of validation errors (if any)
        """
        event = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'event_type': 'signal_validated',
            'signal_id': signal_id,
            'valid': valid,
            'errors': errors or []
        }
        self._write_event(event)
    
    def log_duplicate_detected(self, signal_id: str, strategy: str, 
                               first_seen: Optional[str] = None):
        """
        Log when idempotency check detects a duplicate signal.
        
        Args:
            signal_id: Signal identifier
            strategy: Strategy name
            first_seen: When signal was first processed
        """
        event = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'event_type': 'duplicate_detected',
            'signal_id': signal_id,
            'strategy': strategy,
            'first_seen': first_seen,
            'status': 'blocked'
        }
        self._write_event(event)
    
    def log_order_placed(self, signal_id: str, client_order_id: str, 
                        symbol: str, side: str, amount: float, 
                        price: float, order_type: str, venue: str):
        """
        Log when an order is placed.
        
        Args:
            signal_id: Originating signal ID
            client_order_id: Deterministic client order ID
            symbol: Trading symbol
            side: BUY or SELL
            amount: Order quantity
            price: Order price
            order_type: LIMIT, MARKET, STOP, etc.
            venue: entry, sl, or tp
        """
        event = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'event_type': 'order_placed',
            'signal_id': signal_id,
            'client_order_id': client_order_id,
            'symbol': symbol,
            'side': side,
            'amount': amount,
            'price': price,
            'order_type': order_type,
            'venue': venue
        }
        self._write_event(event)
    
    def log_order_filled(self, client_order_id: str, symbol: str, 
                        filled_qty: float, avg_price: float, 
                        exchange_order_id: str):
        """
        Log when an order is filled.
        
        Args:
            client_order_id: Our deterministic order ID
            symbol: Trading symbol
            filled_qty: Quantity filled
            avg_price: Average fill price
            exchange_order_id: Exchange's order ID
        """
        # Extract signal_id from client_order_id (format: signal_id:venue:leg:attempt)
        signal_id = client_order_id.split(':')[0] if ':' in client_order_id else None
        
        event = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'event_type': 'order_filled',
            'client_order_id': client_order_id,
            'signal_id': signal_id,  # Add signal_id for query filtering
            'symbol': symbol,
            'filled_qty': filled_qty,
            'avg_price': avg_price,
            'exchange_order_id': exchange_order_id
        }
        self._write_event(event)
    
    def log_order_rejected(self, client_order_id: str, symbol: str, 
                          reason: str, error_code: Optional[str] = None):
        """
        Log when an order is rejected by exchange.
        
        Args:
            client_order_id: Our deterministic order ID
            symbol: Trading symbol
            reason: Rejection reason
            error_code: Exchange error code
        """
        # Extract signal_id from client_order_id (format: signal_id:venue:leg:attempt)
        signal_id = client_order_id.split(':')[0] if ':' in client_order_id else None
        
        event = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'event_type': 'order_rejected',
            'client_order_id': client_order_id,
            'signal_id': signal_id,  # Add signal_id for query filtering
            'symbol': symbol,
            'reason': reason,
            'error_code': error_code,
            'severity': 'error'
        }
        self._write_event(event)
    
    def log_position_opened(self, signal_id: str, symbol: str, side: str, 
                           size: float, entry_price: float, 
                           virtual_balance_before: float, 
                           virtual_balance_after: float):
        """
        Log when a position is opened.
        
        Args:
            signal_id: Originating signal ID
            symbol: Trading symbol
            side: LONG or SHORT
            size: Position size
            entry_price: Entry price
            virtual_balance_before: Balance before position
            virtual_balance_after: Balance after position
        """
        event = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'event_type': 'position_opened',
            'signal_id': signal_id,
            'symbol': symbol,
            'side': side,
            'size': size,
            'entry_price': entry_price,
            'virtual_balance_before': virtual_balance_before,
            'virtual_balance_after': virtual_balance_after
        }
        self._write_event(event)
    
    def log_position_closed(self, signal_id: str, symbol: str, 
                           exit_price: float, pnl: float, 
                           virtual_balance_before: float,
                           virtual_balance_after: float,
                           reason: str):
        """
        Log when a position is closed.
        
        Args:
            signal_id: Originating signal ID
            symbol: Trading symbol
            exit_price: Exit price
            pnl: Realized P&L
            virtual_balance_before: Balance before close
            virtual_balance_after: Balance after close
            reason: Close reason (tp, sl, manual, etc.)
        """
        event = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'event_type': 'position_closed',
            'signal_id': signal_id,
            'symbol': symbol,
            'exit_price': exit_price,
            'pnl': pnl,
            'virtual_balance_before': virtual_balance_before,
            'virtual_balance_after': virtual_balance_after,
            'reason': reason
        }
        self._write_event(event)
    
    def log_critical_failure(self, component: str, error: str, 
                            context: Optional[Dict] = None):
        """
        Log critical system failures.
        
        Args:
            component: Component where failure occurred
            error: Error message
            context: Additional context (signal_id, symbol, etc.)
        """
        event = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'event_type': 'critical_failure',
            'component': component,
            'error': error,
            'context': context or {},
            'severity': 'critical'
        }
        self._write_event(event)
        logger.critical(f"🚨 CRITICAL FAILURE: {component} - {error}")
    
    def log_api_error(self, endpoint: str, error: str, 
                     status_code: Optional[int] = None,
                     retry_count: int = 0):
        """
        Log API errors (Binance, Sheets, Telegram).
        
        Args:
            endpoint: API endpoint that failed
            error: Error message
            status_code: HTTP status code
            retry_count: Number of retries attempted
        """
        event = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'event_type': 'api_error',
            'endpoint': endpoint,
            'error': error,
            'status_code': status_code,
            'retry_count': retry_count,
            'severity': 'error'
        }
        self._write_event(event)
    
    def log_reconciliation(self, virtual_balance: float, testnet_balance: float, 
                          drift: float, drift_pct: float, threshold_exceeded: bool):
        """
        Log balance reconciliation check.
        
        Args:
            virtual_balance: Our calculated balance
            testnet_balance: Binance testnet balance
            drift: Absolute difference
            drift_pct: Percentage difference
            threshold_exceeded: Whether drift exceeds acceptable threshold
        """
        event = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'event_type': 'reconciliation',
            'virtual_balance': virtual_balance,
            'testnet_balance': testnet_balance,
            'drift': drift,
            'drift_pct': drift_pct,
            'threshold_exceeded': threshold_exceeded,
            'severity': 'warning' if threshold_exceeded else 'info'
        }
        self._write_event(event)
    
    def query_events(self, event_type: Optional[str] = None, 
                    signal_id: Optional[str] = None,
                    since: Optional[datetime] = None,
                    max_results: int = 100) -> list:
        """
        Query events from log files.
        
        Args:
            event_type: Filter by event type
            signal_id: Filter by signal ID
            since: Only return events after this time
            max_results: Maximum results to return
            
        Returns:
            List of matching events
        """
        results = []
        
        try:
            # Get all event log files
            log_files = sorted(self.log_dir.glob("events_*.jsonl"), reverse=True)
            
            for log_file in log_files:
                if len(results) >= max_results:
                    break
                
                with open(log_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        if len(results) >= max_results:
                            break
                        
                        try:
                            event = json.loads(line)
                            
                            # Apply filters
                            if event_type and event.get('event_type') != event_type:
                                continue
                            
                            if signal_id and event.get('signal_id') != signal_id:
                                continue
                            
                            if since:
                                event_time = datetime.fromisoformat(event['timestamp'])
                                if event_time < since:
                                    continue
                            
                            results.append(event)
                            
                        except json.JSONDecodeError:
                            continue
            
            return results[:max_results]
            
        except Exception as e:
            logger.error(f"❌ Failed to query events: {e}")
            return []


# Singleton instance
_event_logger = None

def get_event_logger(log_dir: str = "storage/events") -> EventLogger:
    """
    Get singleton EventLogger instance.
    
    Args:
        log_dir: Directory for event logs
        
    Returns:
        EventLogger instance
    """
    global _event_logger
    if _event_logger is None:
        _event_logger = EventLogger(log_dir)
    return _event_logger
