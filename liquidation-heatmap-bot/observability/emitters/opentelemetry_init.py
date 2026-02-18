"""Enhanced OpenTelemetry tracer for distributed tracing.

Provides spans for key operations:
- signal_eval: Signal evaluation and voting
- entry_check: Entry condition validation
- order_place: Order placement to exchange
- bracket_set: Stop-loss and take-profit bracket orders

Span attributes include:
- decision_id, venue, symbol, signal_strength, qty

If OpenTelemetry SDK is not installed, returns a noop tracer.

Usage:
    tracer = init_tracer('liquidation_service')
    
    with tracer.start_as_current_span('signal_eval', attributes={'decision_id': 'dec_123'}):
        # ... signal evaluation logic
"""
import os
import logging
from contextlib import contextmanager
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

try:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    
    # Optional OTLP exporter
    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        OTLP_AVAILABLE = True
    except ImportError:
        OTLP_AVAILABLE = False
    
    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False
    logger.info("OpenTelemetry SDK not installed - tracing disabled")


# Standard span names for the bot
SPAN_SIGNAL_EVAL = "signal_eval"
SPAN_ENTRY_CHECK = "entry_check"
SPAN_ORDER_PLACE = "order_place"
SPAN_BRACKET_SET = "bracket_set"
SPAN_DATA_LOAD = "data_load"
SPAN_CLUSTER_IDENTIFY = "cluster_identify"
SPAN_RISK_CALC = "risk_calc"


class NoopSpan:
    """No-op span for when OTel is not available."""
    
    def __init__(self, *args, **kwargs):
        pass
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc, tb):
        return False
    
    def set_attribute(self, key, value):
        pass
    
    def set_status(self, status):
        pass
    
    def record_exception(self, exc):
        pass
    
    def add_event(self, name, attributes=None):
        pass


class NoopTracer:
    """No-op tracer for when OTel is not available."""
    
    def start_as_current_span(self, name, attributes=None, **kwargs):
        return NoopSpan()
    
    def start_span(self, name, attributes=None, **kwargs):
        return NoopSpan()


class EnhancedTracer:
    """Enhanced tracer with convenience methods for common spans."""
    
    def __init__(self, tracer):
        self._tracer = tracer
        self.enabled = OTEL_AVAILABLE and tracer is not None
    
    def start_as_current_span(self, name: str, attributes: Optional[Dict[str, Any]] = None, **kwargs):
        """Start a span as the current span.
        
        Args:
            name: Span name
            attributes: Optional span attributes
            **kwargs: Additional span options
        """
        if not self.enabled:
            return NoopSpan()
        
        attrs = attributes or {}
        return self._tracer.start_as_current_span(name, attributes=attrs, **kwargs)
    
    def start_span(self, name: str, attributes: Optional[Dict[str, Any]] = None, **kwargs):
        """Start a new span (not necessarily current).
        
        Args:
            name: Span name
            attributes: Optional span attributes
            **kwargs: Additional span options
        """
        if not self.enabled:
            return NoopSpan()
        
        attrs = attributes or {}
        return self._tracer.start_span(name, attributes=attrs, **kwargs)
    
    @contextmanager
    def signal_eval(
        self,
        decision_id: str,
        venue: str = "binanceusdm",
        symbol: str = "BTCUSDT",
        **extra_attrs
    ):
        """Context manager for signal evaluation span.
        
        Args:
            decision_id: Decision identifier
            venue: Exchange venue
            symbol: Trading symbol
            **extra_attrs: Additional attributes
        """
        attrs = {
            "decision_id": decision_id,
            "venue": venue,
            "symbol": symbol,
            **extra_attrs
        }
        with self.start_as_current_span(SPAN_SIGNAL_EVAL, attributes=attrs) as span:
            yield span
    
    @contextmanager
    def entry_check(
        self,
        decision_id: str,
        signal_dir: str,
        signal_strength: str,
        **extra_attrs
    ):
        """Context manager for entry check span.
        
        Args:
            decision_id: Decision identifier
            signal_dir: Signal direction (LONG/SHORT/NONE)
            signal_strength: Signal strength (STRONG/MEDIUM/NONE)
            **extra_attrs: Additional attributes
        """
        attrs = {
            "decision_id": decision_id,
            "signal_dir": signal_dir,
            "signal_strength": signal_strength,
            **extra_attrs
        }
        with self.start_as_current_span(SPAN_ENTRY_CHECK, attributes=attrs) as span:
            yield span
    
    @contextmanager
    def order_place(
        self,
        decision_id: str,
        order_id: str,
        side: str,
        qty: float,
        **extra_attrs
    ):
        """Context manager for order placement span.
        
        Args:
            decision_id: Decision identifier
            order_id: Order identifier
            side: Order side (BUY/SELL)
            qty: Order quantity
            **extra_attrs: Additional attributes
        """
        attrs = {
            "decision_id": decision_id,
            "order_id": order_id,
            "side": side,
            "qty": qty,
            **extra_attrs
        }
        with self.start_as_current_span(SPAN_ORDER_PLACE, attributes=attrs) as span:
            yield span
    
    @contextmanager
    def bracket_set(
        self,
        decision_id: str,
        sl_price: float,
        tp_prices: list,
        **extra_attrs
    ):
        """Context manager for bracket order span.
        
        Args:
            decision_id: Decision identifier
            sl_price: Stop-loss price
            tp_prices: List of take-profit prices
            **extra_attrs: Additional attributes
        """
        attrs = {
            "decision_id": decision_id,
            "sl_price": sl_price,
            "tp_count": len(tp_prices) if tp_prices else 0,
            **extra_attrs
        }
        with self.start_as_current_span(SPAN_BRACKET_SET, attributes=attrs) as span:
            yield span


def init_tracer(
    service_name: str = 'liquidation_service',
    otlp_endpoint: Optional[str] = None,
    console_export: bool = False
) -> EnhancedTracer:
    """Initialize OpenTelemetry tracer with optional exporters.
    
    Args:
        service_name: Service name for traces
        otlp_endpoint: Optional OTLP collector endpoint (e.g., 'localhost:4317')
        console_export: Whether to export spans to console
        
    Returns:
        EnhancedTracer instance (or noop if OTel unavailable)
    """
    if not OTEL_AVAILABLE:
        logger.info("OpenTelemetry not available - returning noop tracer")
        return EnhancedTracer(NoopTracer())
    
    try:
        # Create resource with service name
        resource = Resource.create({
            "service.name": service_name,
            "service.version": os.getenv('SERVICE_VERSION', '1.0.0'),
            "deployment.environment": os.getenv('ENV', 'dev')
        })
        
        # Create tracer provider
        provider = TracerProvider(resource=resource)
        
        # Add OTLP exporter if endpoint provided
        otlp_endpoint = otlp_endpoint or os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT')
        if otlp_endpoint and OTLP_AVAILABLE:
            try:
                otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
                provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
                logger.info(f"OpenTelemetry OTLP exporter configured for {otlp_endpoint}")
            except Exception as e:
                logger.warning(f"Failed to configure OTLP exporter: {e}")
        
        # Add console exporter if requested
        if console_export or os.getenv('OTEL_CONSOLE_EXPORT', '0') == '1':
            console_exporter = ConsoleSpanExporter()
            provider.add_span_processor(BatchSpanProcessor(console_exporter))
            logger.info("OpenTelemetry console exporter enabled")
        
        # Set as global tracer provider
        trace.set_tracer_provider(provider)
        
        # Get tracer
        tracer = trace.get_tracer(__name__)
        logger.info(f'OpenTelemetry tracer initialized for {service_name}')
        
        return EnhancedTracer(tracer)
        
    except Exception as e:
        logger.exception(f'Failed to initialize OpenTelemetry tracer: {e}')
        return EnhancedTracer(NoopTracer())


# Global singleton
_tracer: Optional[EnhancedTracer] = None


def get_tracer(service_name: str = 'liquidation_service') -> EnhancedTracer:
    """Get or create the global tracer singleton."""
    global _tracer
    if _tracer is None:
        _tracer = init_tracer(service_name=service_name)
    return _tracer

