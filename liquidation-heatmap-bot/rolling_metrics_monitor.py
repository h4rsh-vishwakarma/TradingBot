"""
Rolling Metrics Monitor

Computes windowed metrics like error_rate_15m, guard_rate_15m, veto_rate_15m
for alerting on spikes without scanning raw JSONL files.
"""

import threading
import time
import logging
from collections import deque, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
import metrics

logger = logging.getLogger(__name__)


class RollingMetricsMonitor:
    """
    Monitors rolling window metrics for errors, guards, and vetoes.
    
    Maintains time-windowed counters and computes rates periodically.
    """
    
    def __init__(
        self,
        error_window_s: int = 900,  # 15 minutes
        guard_window_s: int = 900,  # 15 minutes
        veto_window_s: int = 900,  # 15 minutes
        decision_window_s: int = 3600,  # 1 hour
        update_interval_s: int = 60  # 1 minute
    ):
        """
        Initialize rolling metrics monitor.
        
        Args:
            error_window_s: Error rate window in seconds
            guard_window_s: Guard rate window in seconds
            veto_window_s: Veto rate window in seconds
            decision_window_s: Decision rate window in seconds
            update_interval_s: How often to compute rates
        """
        self.error_window_s = error_window_s
        self.guard_window_s = guard_window_s
        self.veto_window_s = veto_window_s
        self.decision_window_s = decision_window_s
        self.update_interval_s = update_interval_s
        
        # Timestamped event queues (deque for efficient popleft)
        self.error_timestamps = deque()
        self.guard_timestamps = deque()
        self.veto_timestamps = deque()
        self.decision_timestamps = deque()
        
        # Current rates (computed periodically)
        self.error_rate_15m = 0.0
        self.guard_rate_15m = 0.0
        self.veto_rate_15m = 0.0
        self.decision_rate_1h = 0.0
        
        # Reason breakdowns
        self.veto_reasons = defaultdict(int)
        self.guard_kinds = defaultdict(int)
        self.error_types = defaultdict(int)
        
        # Threading
        self._running = False
        self._thread = None
        self._lock = threading.Lock()
    
    def start(self):
        """Start background monitoring thread."""
        if self._running:
            logger.warning("Rolling metrics monitor already running")
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._monitoring_loop, daemon=True)
        self._thread.start()
        logger.info("Rolling metrics monitor started")
    
    def stop(self):
        """Stop background monitoring thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Rolling metrics monitor stopped")
    
    def record_error(self, error_type: str = "UNKNOWN"):
        """Record an error event."""
        with self._lock:
            now = datetime.now(timezone.utc)
            self.error_timestamps.append(now)
            self.error_types[error_type] += 1
    
    def record_guard(self, guard_kind: str = "UNKNOWN"):
        """Record a guard event."""
        with self._lock:
            now = datetime.now(timezone.utc)
            self.guard_timestamps.append(now)
            self.guard_kinds[guard_kind] += 1
    
    def record_veto(self, veto_reason: str = "UNKNOWN"):
        """Record a veto event."""
        with self._lock:
            now = datetime.now(timezone.utc)
            self.veto_timestamps.append(now)
            self.veto_reasons[veto_reason] += 1
    
    def record_decision(self):
        """Record a decision event."""
        with self._lock:
            now = datetime.now(timezone.utc)
            self.decision_timestamps.append(now)
    
    def _monitoring_loop(self):
        """Background loop that computes rates periodically."""
        while self._running:
            try:
                time.sleep(self.update_interval_s)
                self._compute_rates()
                self._update_prometheus_metrics()
                
            except Exception as e:
                logger.error(f"Rolling metrics monitor error: {e}")
                time.sleep(5)  # Prevent tight loop on error
    
    def _compute_rates(self):
        """Compute rolling window rates."""
        now = datetime.now(timezone.utc)
        
        with self._lock:
            # Remove old events outside windows
            self._prune_old_events(
                self.error_timestamps,
                now - timedelta(seconds=self.error_window_s)
            )
            self._prune_old_events(
                self.guard_timestamps,
                now - timedelta(seconds=self.guard_window_s)
            )
            self._prune_old_events(
                self.veto_timestamps,
                now - timedelta(seconds=self.veto_window_s)
            )
            self._prune_old_events(
                self.decision_timestamps,
                now - timedelta(seconds=self.decision_window_s)
            )
            
            # Compute rates (events per minute)
            error_count = len(self.error_timestamps)
            guard_count = len(self.guard_timestamps)
            veto_count = len(self.veto_timestamps)
            decision_count = len(self.decision_timestamps)
            
            self.error_rate_15m = (error_count / (self.error_window_s / 60)) if self.error_window_s > 0 else 0.0
            self.guard_rate_15m = (guard_count / (self.guard_window_s / 60)) if self.guard_window_s > 0 else 0.0
            self.veto_rate_15m = (veto_count / (self.veto_window_s / 60)) if self.veto_window_s > 0 else 0.0
            self.decision_rate_1h = (decision_count / (self.decision_window_s / 60)) if self.decision_window_s > 0 else 0.0
    
    def _prune_old_events(self, event_deque: deque, cutoff_time: datetime):
        """Remove events older than cutoff time."""
        while event_deque and event_deque[0] < cutoff_time:
            event_deque.popleft()
    
    def _update_prometheus_metrics(self):
        """Update Prometheus gauges with computed rates."""
        if not metrics.PROM_AVAILABLE:
            return
        
        try:
            # Update rate gauges
            metrics.error_rate_15m_gauge.set(self.error_rate_15m)
            metrics.guard_rate_15m_gauge.set(self.guard_rate_15m)
            metrics.veto_rate_15m_gauge.set(self.veto_rate_15m)
            metrics.decision_rate_1h_gauge.set(self.decision_rate_1h)
            
        except Exception as e:
            logger.debug(f"Error updating Prometheus metrics: {e}")
    
    def get_metrics(self) -> Dict:
        """
        Get current rolling metrics.
        
        Returns:
            Dict with current rates and breakdowns
        """
        with self._lock:
            return {
                'error_rate_15m': self.error_rate_15m,
                'guard_rate_15m': self.guard_rate_15m,
                'veto_rate_15m': self.veto_rate_15m,
                'decision_rate_1h': self.decision_rate_1h,
                'error_count_15m': len(self.error_timestamps),
                'guard_count_15m': len(self.guard_timestamps),
                'veto_count_15m': len(self.veto_timestamps),
                'decision_count_1h': len(self.decision_timestamps),
                'top_veto_reasons': dict(sorted(self.veto_reasons.items(), key=lambda x: x[1], reverse=True)[:5]),
                'top_guard_kinds': dict(sorted(self.guard_kinds.items(), key=lambda x: x[1], reverse=True)[:5]),
                'top_error_types': dict(sorted(self.error_types.items(), key=lambda x: x[1], reverse=True)[:5])
            }
    
    def should_alert(
        self,
        error_threshold: float = 5.0,  # errors per minute
        guard_threshold: float = 10.0,  # guards per minute
        veto_threshold: float = 5.0  # vetoes per minute
    ) -> tuple[bool, List[str]]:
        """
        Check if any rate exceeds alert thresholds.
        
        Args:
            error_threshold: Errors per minute threshold
            guard_threshold: Guards per minute threshold
            veto_threshold: Vetoes per minute threshold
        
        Returns:
            Tuple of (should_alert, reasons)
        """
        reasons = []
        
        if self.error_rate_15m > error_threshold:
            reasons.append(f"Error rate spike: {self.error_rate_15m:.1f}/min (threshold: {error_threshold}/min)")
        
        if self.guard_rate_15m > guard_threshold:
            reasons.append(f"Guard rate spike: {self.guard_rate_15m:.1f}/min (threshold: {guard_threshold}/min)")
        
        if self.veto_rate_15m > veto_threshold:
            reasons.append(f"Veto rate spike: {self.veto_rate_15m:.1f}/min (threshold: {veto_threshold}/min)")
        
        return len(reasons) > 0, reasons


# Global instance for easy access
_monitor_instance: Optional[RollingMetricsMonitor] = None


def get_monitor() -> RollingMetricsMonitor:
    """Get or create global rolling metrics monitor instance."""
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = RollingMetricsMonitor()
        _monitor_instance.start()
    return _monitor_instance


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    monitor = RollingMetricsMonitor()
    monitor.start()
    
    # Simulate some events
    import random
    for i in range(50):
        if random.random() < 0.1:
            monitor.record_error("WEBSOCKET_DISCONNECT")
        if random.random() < 0.2:
            monitor.record_guard("STALE_PRICE")
        if random.random() < 0.15:
            monitor.record_veto("EDGE_TOO_SMALL")
        monitor.record_decision()
        time.sleep(0.1)
    
    time.sleep(2)
    
    # Get metrics
    metrics_dict = monitor.get_metrics()
    print("\n=== Rolling Metrics ===")
    for k, v in metrics_dict.items():
        print(f"{k}: {v}")
    
    # Check alerts
    should_alert, reasons = monitor.should_alert()
    if should_alert:
        print("\n⚠️ ALERTS:")
        for reason in reasons:
            print(f"  - {reason}")
    
    monitor.stop()
