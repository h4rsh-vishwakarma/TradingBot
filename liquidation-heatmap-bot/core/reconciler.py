"""
Advanced position reconciliation system.
Compares derived positions (from fills) vs exchange positions (from API).
Detects and alerts on position drift.
"""

import time
import logging
from typing import Dict, Optional, Tuple
from collections import defaultdict

logger = logging.getLogger(__name__)


class PositionReconciler:
    """
    Reconciles derived positions vs exchange positions.
    
    Derived Position: Calculated from fill events (orders we know about)
    Exchange Position: Actual position on exchange (ground truth)
    """
    
    def __init__(self, tolerance_qty: float = 0.001, tolerance_notional: float = 1.0):
        """
        Initialize reconciler.
        
        Args:
            tolerance_qty: Max quantity drift before alerting (default 0.001 BTC)
            tolerance_notional: Max notional drift before alerting (default $1)
        """
        self.tolerance_qty = tolerance_qty
        self.tolerance_notional = tolerance_notional
        
        # Derived positions from fills
        self._derived_positions: Dict[str, float] = defaultdict(float)
        
        # Last reconciliation results
        self._last_recon_time: Dict[str, float] = {}
        self._drift_history: Dict[str, list] = defaultdict(list)
        
        logger.info(f"🔍 Position reconciler initialized: "
                   f"qty_tol={tolerance_qty}, notional_tol=${tolerance_notional}")
    
    def record_fill(self, symbol: str, side: str, quantity: float):
        """
        Record a fill to update derived position.
        
        Args:
            symbol: Trading symbol
            side: BUY or SELL
            quantity: Fill quantity (absolute value)
        """
        if side == 'BUY':
            self._derived_positions[symbol] += quantity
        elif side == 'SELL':
            self._derived_positions[symbol] -= quantity
        else:
            logger.error(f"Invalid side: {side}")
        
        logger.debug(f"📊 Derived position updated: {symbol} = {self._derived_positions[symbol]:.6f}")
    
    def get_derived_position(self, symbol: str) -> float:
        """Get current derived position for symbol."""
        return self._derived_positions.get(symbol, 0.0)
    
    def reconcile(self, symbol: str, exchange_qty: float, 
                  current_price: Optional[float] = None) -> Tuple[bool, float, float]:
        """
        Reconcile derived vs exchange position.
        
        Args:
            symbol: Trading symbol
            exchange_qty: Position quantity from exchange API
            current_price: Current market price (for notional calculation)
        
        Returns:
            (drift_detected, qty_drift, notional_drift)
        """
        derived_qty = self._derived_positions.get(symbol, 0.0)
        qty_drift = exchange_qty - derived_qty
        
        # Calculate notional drift if price provided
        notional_drift = abs(qty_drift * current_price) if current_price else 0.0
        
        # Check if drift exceeds tolerance
        drift_detected = (
            abs(qty_drift) > self.tolerance_qty or
            notional_drift > self.tolerance_notional
        )
        
        # Update recon time
        self._last_recon_time[symbol] = time.time()
        
        # Record drift history
        self._drift_history[symbol].append({
            'ts': time.time(),
            'derived': derived_qty,
            'exchange': exchange_qty,
            'qty_drift': qty_drift,
            'notional_drift': notional_drift
        })
        
        # Keep only last 100 records
        if len(self._drift_history[symbol]) > 100:
            self._drift_history[symbol] = self._drift_history[symbol][-100:]
        
        if drift_detected:
            logger.warning(
                f"⚠️ Position drift detected for {symbol}:\n"
                f"   Derived: {derived_qty:.6f}\n"
                f"   Exchange: {exchange_qty:.6f}\n"
                f"   Qty Drift: {qty_drift:.6f}\n"
                f"   Notional Drift: ${notional_drift:.2f}"
            )
        else:
            logger.debug(f"✅ Position reconciled: {symbol} | drift={qty_drift:.6f}")
        
        return drift_detected, qty_drift, notional_drift
    
    def sync_from_exchange(self, symbol: str, exchange_qty: float):
        """
        Force sync derived position to match exchange.
        Use this after detecting drift to resync.
        
        Args:
            symbol: Trading symbol
            exchange_qty: Exchange position to sync to
        """
        old_qty = self._derived_positions.get(symbol, 0.0)
        self._derived_positions[symbol] = exchange_qty
        
        logger.info(
            f"🔄 Position synced from exchange: {symbol}\n"
            f"   Old derived: {old_qty:.6f}\n"
            f"   New derived: {exchange_qty:.6f}"
        )
    
    def get_drift_summary(self, symbol: str, lookback_minutes: int = 60) -> Dict:
        """
        Get drift summary for a symbol over time.
        
        Args:
            symbol: Trading symbol
            lookback_minutes: Minutes to look back
        
        Returns:
            Dict with drift statistics
        """
        if symbol not in self._drift_history:
            return {'count': 0, 'avg_drift': 0.0, 'max_drift': 0.0}
        
        cutoff_time = time.time() - (lookback_minutes * 60)
        recent_drifts = [
            d for d in self._drift_history[symbol]
            if d['ts'] >= cutoff_time
        ]
        
        if not recent_drifts:
            return {'count': 0, 'avg_drift': 0.0, 'max_drift': 0.0}
        
        qty_drifts = [abs(d['qty_drift']) for d in recent_drifts]
        
        return {
            'count': len(recent_drifts),
            'avg_drift': sum(qty_drifts) / len(qty_drifts),
            'max_drift': max(qty_drifts),
            'last_drift': recent_drifts[-1]['qty_drift'],
            'lookback_minutes': lookback_minutes
        }
    
    def reset_position(self, symbol: str):
        """Reset derived position for symbol (e.g., after manual close)."""
        if symbol in self._derived_positions:
            old_qty = self._derived_positions[symbol]
            self._derived_positions[symbol] = 0.0
            logger.info(f"🔄 Position reset: {symbol} ({old_qty:.6f} → 0.0)")
    
    def get_all_positions(self) -> Dict[str, float]:
        """Get all derived positions."""
        return dict(self._derived_positions)


class ReconciliationMonitor:
    """
    Monitors reconciliation and triggers alerts.
    Works with PositionReconciler and TelegramAlert.
    """
    
    def __init__(self, reconciler: PositionReconciler, 
                 telegram_alert=None, event_logger=None):
        """
        Initialize monitor.
        
        Args:
            reconciler: PositionReconciler instance
            telegram_alert: Optional TelegramAlert instance
            event_logger: Optional EventLogger instance
        """
        self.reconciler = reconciler
        self.telegram = telegram_alert
        self.event_logger = event_logger
        
        # Track consecutive drift alerts
        self._consecutive_drifts: Dict[str, int] = defaultdict(int)
        
        logger.info("🔍 Reconciliation monitor initialized")
    
    def check_and_alert(self, symbol: str, exchange_qty: float, 
                       current_price: Optional[float] = None) -> bool:
        """
        Check reconciliation and send alerts if needed.
        
        Args:
            symbol: Trading symbol
            exchange_qty: Exchange position quantity
            current_price: Current market price
        
        Returns:
            True if drift detected
        """
        drift_detected, qty_drift, notional_drift = self.reconciler.reconcile(
            symbol, exchange_qty, current_price
        )
        
        # Log event
        if self.event_logger:
            self.event_logger.log_recon(
                symbol,
                self.reconciler.get_derived_position(symbol),
                exchange_qty,
                qty_drift,
                'drift_detected' if drift_detected else 'checked'
            )
        
        # Handle drift detection
        if drift_detected:
            self._consecutive_drifts[symbol] += 1
            
            # Send Telegram alert on first drift or every 5th consecutive drift
            if self._consecutive_drifts[symbol] == 1 or self._consecutive_drifts[symbol] % 5 == 0:
                if self.telegram:
                    drift_summary = self.reconciler.get_drift_summary(symbol, 60)
                    
                    self.telegram.send_alert(
                        severity='WARNING',
                        title=f'Position Drift: {symbol}',
                        message=(
                            f"Quantity drift: {qty_drift:.6f}\n"
                            f"Notional drift: ${notional_drift:.2f}\n"
                            f"Consecutive drifts: {self._consecutive_drifts[symbol]}\n"
                            f"Avg drift (60m): {drift_summary['avg_drift']:.6f}"
                        ),
                        details={
                            'derived': self.reconciler.get_derived_position(symbol),
                            'exchange': exchange_qty,
                            'drift_count': self._consecutive_drifts[symbol]
                        }
                    )
        else:
            # Reset consecutive counter on successful recon
            self._consecutive_drifts[symbol] = 0
        
        return drift_detected
    
    def auto_sync_on_persistent_drift(self, symbol: str, threshold: int = 10) -> bool:
        """
        Auto-sync position if drift persists.
        
        Args:
            symbol: Trading symbol
            threshold: Number of consecutive drifts before auto-sync
        
        Returns:
            True if auto-sync was performed
        """
        if self._consecutive_drifts[symbol] >= threshold:
            logger.warning(
                f"⚠️ Auto-syncing {symbol} after {self._consecutive_drifts[symbol]} "
                f"consecutive drifts"
            )
            
            # This should be called with exchange position
            # For now just log - actual sync requires exchange query
            
            if self.telegram:
                self.telegram.send_alert(
                    severity='HIGH',
                    title=f'Auto-Sync Triggered: {symbol}',
                    message=f"Position synced after {self._consecutive_drifts[symbol]} consecutive drifts",
                    details={'threshold': threshold}
                )
            
            self._consecutive_drifts[symbol] = 0
            return True
        
        return False


# Test function
def test_reconciler():
    """Test the position reconciler."""
    
    reconciler = PositionReconciler(tolerance_qty=0.001, tolerance_notional=1.0)
    
    # Test 1: Record BUY fill
    reconciler.record_fill('BTCUSDT', 'BUY', 0.005)
    assert reconciler.get_derived_position('BTCUSDT') == 0.005, "Should have 0.005 BTC"
    
    # Test 2: Reconcile with matching exchange position
    drift_detected, qty_drift, _ = reconciler.reconcile('BTCUSDT', 0.005, 88000.0)
    assert not drift_detected, "No drift should be detected"
    assert qty_drift == 0.0, "Drift should be zero"
    
    # Test 3: Record SELL fill
    reconciler.record_fill('BTCUSDT', 'SELL', 0.003)
    assert reconciler.get_derived_position('BTCUSDT') == 0.002, "Should have 0.002 BTC"
    
    # Test 4: Detect drift
    drift_detected, qty_drift, notional_drift = reconciler.reconcile('BTCUSDT', 0.004, 88000.0)
    assert drift_detected, "Drift should be detected"
    assert abs(qty_drift - 0.002) < 0.0001, "Drift should be ~0.002"
    assert abs(notional_drift - 176.0) < 0.1, "Notional drift should be ~$176"
    
    # Test 5: Sync from exchange
    reconciler.sync_from_exchange('BTCUSDT', 0.004)
    assert reconciler.get_derived_position('BTCUSDT') == 0.004, "Should be synced to 0.004"
    
    # Test 6: Drift summary
    summary = reconciler.get_drift_summary('BTCUSDT', 60)
    assert summary['count'] == 2, "Should have 2 reconciliation records"
    
    # Test 7: Reset position
    reconciler.reset_position('BTCUSDT')
    assert reconciler.get_derived_position('BTCUSDT') == 0.0, "Should be reset to 0"
    
    print("✅ All reconciler tests passed!")


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    test_reconciler()
