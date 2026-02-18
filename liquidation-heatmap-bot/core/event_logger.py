"""
Structured event logging system.
Creates append-only JSONL logs for signals, orders, fills, and reconciliation events.
"""

import json
import time
from pathlib import Path
from typing import Dict, Optional
import threading
import logging

logger = logging.getLogger(__name__)


class EventLogger:
    """Thread-safe structured event logger using JSONL format."""
    
    def __init__(self, log_dir: str = "logs"):
        """
        Initialize event logger.
        
        Args:
            log_dir: Directory for log files
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # File paths
        self.signals_log = self.log_dir / "signals.jsonl"
        self.orders_log = self.log_dir / "orders.jsonl"
        self.fills_log = self.log_dir / "fills.jsonl"
        self.recon_log = self.log_dir / "recon.jsonl"
        self.alerts_log = self.log_dir / "alerts.jsonl"
        
        # Thread locks for safe concurrent writes
        self._locks = {
            'signals': threading.Lock(),
            'orders': threading.Lock(),
            'fills': threading.Lock(),
            'recon': threading.Lock(),
            'alerts': threading.Lock()
        }
        
        logger.info(f"📝 Event logger initialized: {self.log_dir}")
    
    def _append_jsonl(self, file_path: Path, record: Dict, lock_name: str):
        """
        Append a record to JSONL file with thread safety.
        
        Args:
            file_path: Path to JSONL file
            record: Dict to append as JSON line
            lock_name: Name of lock to use
        """
        try:
            with self._locks[lock_name]:
                with open(file_path, 'a', encoding='utf-8') as f:
                    json.dump(record, f)
                    f.write('\n')
                    f.flush()  # Ensure written to disk
        except Exception as e:
            logger.error(f"Failed to write to {file_path}: {e}")
    
    def log_signal(self, signal_id: str, strategy: str, side: str, symbol: str,
                   price: float, timeframe: str, status: str = 'received',
                   details: Optional[Dict] = None):
        """
        Log a signal event.
        
        Args:
            signal_id: Unique signal identifier
            strategy: Strategy name
            side: BUY/SELL
            symbol: Trading symbol
            price: Signal price
            timeframe: Chart timeframe
            status: Signal status (received, validated, rejected, executed)
            details: Additional details dict
        """
        record = {
            'ts': time.time(),
            'type': 'signal',
            'signal_id': signal_id,
            'strategy': strategy,
            'side': side,
            'symbol': symbol,
            'price': price,
            'timeframe': timeframe,
            'status': status
        }
        
        if details:
            record['details'] = details
        
        self._append_jsonl(self.signals_log, record, 'signals')
        logger.debug(f"📝 Logged signal: {signal_id} | {status}")
    
    def log_order(self, signal_id: str, order_id: str, symbol: str, side: str,
                  order_type: str, quantity: float, price: Optional[float] = None,
                  status: str = 'placed', exchange_order_id: Optional[str] = None,
                  details: Optional[Dict] = None):
        """
        Log an order event.
        
        Args:
            signal_id: Related signal ID
            order_id: Internal order ID
            symbol: Trading symbol
            side: BUY/SELL
            order_type: MARKET/LIMIT/STOP_LOSS/TAKE_PROFIT
            quantity: Order quantity
            price: Order price (if applicable)
            status: Order status (placed, filled, cancelled, failed)
            exchange_order_id: Exchange's order ID
            details: Additional details
        """
        record = {
            'ts': time.time(),
            'type': 'order',
            'signal_id': signal_id,
            'order_id': order_id,
            'exchange_order_id': exchange_order_id,
            'symbol': symbol,
            'side': side,
            'order_type': order_type,
            'quantity': quantity,
            'status': status
        }
        
        if price is not None:
            record['price'] = price
        
        if details:
            record['details'] = details
        
        self._append_jsonl(self.orders_log, record, 'orders')
        logger.debug(f"📝 Logged order: {order_id} | {status}")
    
    def log_fill(self, signal_id: str, order_id: str, exchange_order_id: str,
                 symbol: str, side: str, quantity: float, fill_price: float,
                 fee: float = 0.0, details: Optional[Dict] = None):
        """
        Log a fill event.
        
        Args:
            signal_id: Related signal ID
            order_id: Internal order ID
            exchange_order_id: Exchange's order ID
            symbol: Trading symbol
            side: BUY/SELL
            quantity: Filled quantity
            fill_price: Actual fill price
            fee: Trading fee
            details: Additional details
        """
        record = {
            'ts': time.time(),
            'type': 'fill',
            'signal_id': signal_id,
            'order_id': order_id,
            'exchange_order_id': exchange_order_id,
            'symbol': symbol,
            'side': side,
            'quantity': quantity,
            'fill_price': fill_price,
            'fee': fee
        }
        
        if details:
            record['details'] = details
        
        self._append_jsonl(self.fills_log, record, 'fills')
        logger.debug(f"📝 Logged fill: {order_id} | {quantity} @ ${fill_price}")
    
    def log_recon(self, symbol: str, expected_qty: float, exchange_qty: float,
                  drift: float, status: str = 'checked', details: Optional[Dict] = None):
        """
        Log a reconciliation event.
        
        Args:
            symbol: Trading symbol
            expected_qty: Expected position quantity
            exchange_qty: Actual exchange position quantity
            drift: Difference between expected and actual
            status: Reconciliation status (checked, drift_detected, corrected)
            details: Additional details
        """
        record = {
            'ts': time.time(),
            'type': 'reconciliation',
            'symbol': symbol,
            'expected_qty': expected_qty,
            'exchange_qty': exchange_qty,
            'drift': drift,
            'status': status
        }
        
        if details:
            record['details'] = details
        
        self._append_jsonl(self.recon_log, record, 'recon')
        
        if abs(drift) > 0.001:  # Log warning if drift detected
            logger.warning(f"📝 Logged drift: {symbol} drift={drift}")
        else:
            logger.debug(f"📝 Logged recon: {symbol} | OK")
    
    def log_alert(self, severity: str, title: str, message: str,
                  details: Optional[Dict] = None):
        """
        Log an alert event.
        
        Args:
            severity: Alert severity (INFO, WARNING, HIGH, CRITICAL)
            title: Alert title
            message: Alert message
            details: Additional details
        """
        record = {
            'ts': time.time(),
            'type': 'alert',
            'severity': severity,
            'title': title,
            'message': message
        }
        
        if details:
            record['details'] = details
        
        self._append_jsonl(self.alerts_log, record, 'alerts')
        logger.debug(f"📝 Logged alert: [{severity}] {title}")
    
    def read_recent_signals(self, limit: int = 100) -> list:
        """Read recent signal events."""
        return self._read_recent(self.signals_log, limit)
    
    def read_recent_orders(self, limit: int = 100) -> list:
        """Read recent order events."""
        return self._read_recent(self.orders_log, limit)
    
    def read_recent_fills(self, limit: int = 100) -> list:
        """Read recent fill events."""
        return self._read_recent(self.fills_log, limit)
    
    def _read_recent(self, file_path: Path, limit: int) -> list:
        """Read recent records from JSONL file."""
        if not file_path.exists():
            return []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # Get last N lines
            recent_lines = lines[-limit:] if len(lines) > limit else lines
            
            # Parse JSON
            records = []
            for line in recent_lines:
                try:
                    records.append(json.loads(line.strip()))
                except json.JSONDecodeError:
                    continue
            
            return records
        except Exception as e:
            logger.error(f"Failed to read {file_path}: {e}")
            return []


# Test function
def test_event_logger():
    """Test the event logger."""
    import tempfile
    import shutil
    
    # Create temp directory
    temp_dir = Path(tempfile.mkdtemp())
    
    try:
        el = EventLogger(str(temp_dir))
        
        # Test 1: Log signal
        el.log_signal(
            'TEST-001', 'smc_luxalgo', 'BUY', 'BTCUSDT',
            88000.0, '15m', 'received'
        )
        
        # Test 2: Log order
        el.log_order(
            'TEST-001', 'ORD-001', 'BTCUSDT', 'BUY',
            'MARKET', 0.001, status='placed',
            exchange_order_id='12345'
        )
        
        # Test 3: Log fill
        el.log_fill(
            'TEST-001', 'ORD-001', '12345', 'BTCUSDT',
            'BUY', 0.001, 88100.0, 0.05
        )
        
        # Test 4: Log reconciliation
        el.log_recon('BTCUSDT', 0.001, 0.001, 0.0, 'checked')
        
        # Test 5: Log alert
        el.log_alert('WARNING', 'Test Alert', 'This is a test')
        
        # Test 6: Read back
        signals = el.read_recent_signals(10)
        assert len(signals) == 1, "Should have 1 signal"
        assert signals[0]['signal_id'] == 'TEST-001', "Signal ID should match"
        
        orders = el.read_recent_orders(10)
        assert len(orders) == 1, "Should have 1 order"
        
        fills = el.read_recent_fills(10)
        assert len(fills) == 1, "Should have 1 fill"
        
        # Verify files exist
        assert el.signals_log.exists(), "Signals log should exist"
        assert el.orders_log.exists(), "Orders log should exist"
        assert el.fills_log.exists(), "Fills log should exist"
        
        print("✅ All event logger tests passed!")
        
    finally:
        # Cleanup
        shutil.rmtree(temp_dir)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    test_event_logger()
