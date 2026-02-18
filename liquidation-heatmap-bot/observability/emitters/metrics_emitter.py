"""Enhanced Metrics facade for application code.

Provides a unified interface for metrics emission:
- incr(name, amount=1, **labels) - increment counter
- gauge(name, value, **labels) - set gauge value
- observe(name, value, **labels) - observe histogram value
- time(name) - context manager for timing operations

Backed by PrometheusExporter if available; otherwise logs debug messages.

Usage:
    from observability.emitters import MetricsEmitter
    
    metrics = MetricsEmitter()
    metrics.incr('decision_total')
    metrics.incr('decision_no_trade_total', reason='stale_feed')
    metrics.gauge('feed_price_age_seconds', 0.5)
    
    with metrics.time('decision_latency_ms'):
        # ... decision logic
"""
import logging
import time
from contextlib import contextmanager
from typing import Optional, Dict, Any

from .prometheus_exporter import PrometheusExporter, get_prometheus_exporter

logger = logging.getLogger(__name__)


class MetricsEmitter:
    """Unified metrics emission facade.
    
    Wraps PrometheusExporter and provides additional convenience methods.
    Falls back to debug logging if Prometheus is not available.
    """
    
    def __init__(self, port: Optional[int] = None, exporter: Optional[PrometheusExporter] = None):
        """Initialize the metrics emitter.
        
        Args:
            port: Optional port for Prometheus exporter
            exporter: Optional existing PrometheusExporter instance
        """
        try:
            self.prom = exporter or get_prometheus_exporter(port=port)
            self.enabled = getattr(self.prom, 'enabled', False)
        except Exception:
            self.prom = None
            self.enabled = False
            logger.info("Metrics emitter initialized in noop mode (Prometheus unavailable)")
    
    def incr(self, name: str, amount: float = 1, **labels):
        """Increment a counter metric.
        
        Args:
            name: Metric name (without liqbot_ prefix)
            amount: Amount to increment by (default: 1)
            **labels: Label key-value pairs
        """
        if self.enabled and self.prom:
            try:
                self.prom.incr(name, amount, labels=labels if labels else None)
            except Exception:
                logger.exception('metrics.incr failed for %s', name)
        else:
            logger.debug('metrics.incr noop %s=%s labels=%s', name, amount, labels)
    
    def gauge(self, name: str, value: float, **labels):
        """Set a gauge metric value.
        
        Args:
            name: Metric name (without liqbot_ prefix)
            value: Value to set
            **labels: Label key-value pairs
        """
        if self.enabled and self.prom:
            try:
                self.prom.gauge(name, value, labels=labels if labels else None)
            except Exception:
                logger.exception('metrics.gauge failed for %s', name)
        else:
            logger.debug('metrics.gauge noop %s=%s labels=%s', name, value, labels)
    
    def observe(self, name: str, value: float, **labels):
        """Observe a histogram value.
        
        Args:
            name: Metric name (without liqbot_ prefix)
            value: Value to observe
            **labels: Label key-value pairs
        """
        if self.enabled and self.prom:
            try:
                self.prom.observe(name, value, labels=labels if labels else None)
            except Exception:
                logger.exception('metrics.observe failed for %s', name)
        else:
            logger.debug('metrics.observe noop %s=%s labels=%s', name, value, labels)
    
    @contextmanager
    def time(self, name: str, **labels):
        """Context manager for timing operations and recording to histogram.
        
        Args:
            name: Histogram metric name (e.g., 'decision_latency_ms')
            **labels: Label key-value pairs
            
        Usage:
            with metrics.time('decision_latency_ms'):
                # ... timed operation
        """
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            self.observe(name, elapsed_ms, **labels)
    
    def record_decision(
        self,
        action: str,
        no_trade_reason: Optional[str] = None,
        latency_ms: float = 0.0
    ):
        """Record a decision event with appropriate metrics.
        
        Args:
            action: Decision action (PLACE, NO_TRADE, etc.)
            no_trade_reason: Reason if action is NO_TRADE
            latency_ms: Decision latency in milliseconds
        """
        self.incr('decision_total')
        
        if action == 'NO_TRADE' and no_trade_reason:
            self.incr('decision_no_trade_total', reason=no_trade_reason)
        
        if latency_ms > 0:
            self.observe('decision_latency_ms', latency_ms)
    
    def record_guard(self, kind: str):
        """Record a guard trigger.
        
        Args:
            kind: Guard type ('stale', 'edge', 'capacity', 'other')
        """
        if kind == 'stale':
            self.incr('guard_stale_total')
        elif kind == 'edge':
            self.incr('guard_edge_total')
    
    def record_veto(self, reason: str):
        """Record a context veto.
        
        Args:
            reason: Veto reason (funding_extreme, oi_misaligned, etc.)
        """
        self.incr('veto_context_total', reason=reason)
    
    def record_order_placed(self, latency_ms: float = 0.0):
        """Record a successful order placement."""
        self.incr('order_placed_total')
        if latency_ms > 0:
            self.observe('order_place_latency_ms', latency_ms)
    
    def record_order_failed(self):
        """Record an order failure."""
        self.incr('order_failed_total')
    
    def record_fill(self):
        """Record a fill event."""
        self.incr('fill_total')
    
    def record_daily_cap_hit(self):
        """Record a daily risk cap hit."""
        self.incr('risk_daily_cap_hits_total')
    
    def record_ws_reconnect(self):
        """Record a WebSocket reconnection."""
        self.incr('ws_reconnects_total')
    
    def update_feed_health(
        self,
        price_age_s: Optional[float] = None,
        heatmap_age_s: Optional[float] = None
    ):
        """Update feed health gauges.
        
        Args:
            price_age_s: Age of price feed in seconds
            heatmap_age_s: Age of heatmap data in seconds
        """
        if price_age_s is not None:
            self.gauge('feed_price_age_seconds', price_age_s)
        if heatmap_age_s is not None:
            self.gauge('feed_heatmap_age_seconds', heatmap_age_s)
    
    def update_position_health(
        self,
        positions_open: int = 0,
        risk_used_pct: float = 0.0,
        equity_usd: float = 0.0,
        pnl_realized_usd: float = 0.0
    ):
        """Update position and risk gauges.
        
        Args:
            positions_open: Number of open positions
            risk_used_pct: Percentage of daily risk used
            equity_usd: Current equity in USD
            pnl_realized_usd: Realized PnL in USD
        """
        self.gauge('positions_open', positions_open)
        self.gauge('risk_used_pct', risk_used_pct)
        self.gauge('equity_usd', equity_usd)
        self.gauge('pnl_realized_usd', pnl_realized_usd)


# Global singleton
_metrics: Optional[MetricsEmitter] = None


def get_metrics_emitter(port: Optional[int] = None) -> MetricsEmitter:
    """Get or create the global metrics emitter singleton."""
    global _metrics
    if _metrics is None:
        _metrics = MetricsEmitter(port=port)
    return _metrics

