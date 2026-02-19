"""
Metrics Module
Initializes Prometheus metrics for the trading bot.
"""
import os
import logging
import importlib.util

logger = logging.getLogger(__name__)

PROM_AVAILABLE = False
OTEL_AVAILABLE = False
tracer = None

# Prometheus metrics placeholders
Gauge = None
Counter = None
Histogram = None
start_http_server = None

# OpenTelemetry placeholders
trace = None
SpanKind = None

# Initialize Prometheus
_prom_spec = importlib.util.find_spec('prometheus_client')
if _prom_spec is not None:
    try:
        prometheus_client = importlib.import_module('prometheus_client')
        Gauge = prometheus_client.Gauge
        Counter = prometheus_client.Counter
        Histogram = prometheus_client.Histogram
        start_http_server = prometheus_client.start_http_server
        PROM_AVAILABLE = True
    except Exception as _e:
        logger.warning(f"Prometheus import failed: {_e}")

# Initialize OpenTelemetry
try:
    _otel_base_spec = importlib.util.find_spec('opentelemetry')
    if _otel_base_spec is not None:
        _otel_trace_spec = importlib.util.find_spec('opentelemetry.trace')
    else:
        _otel_trace_spec = None
except ModuleNotFoundError:
    _otel_trace_spec = None

if _otel_trace_spec is not None:
    try:
        trace_mod = importlib.import_module('opentelemetry.trace')
        trace = trace_mod
        SpanKind = trace_mod.SpanKind
        tracer = trace.get_tracer(__name__)
        OTEL_AVAILABLE = True
    except Exception as _e:
        logger.warning(f"OpenTelemetry import failed: {_e}")
else:
    class SpanKind:  # Fallback dummy for type references
        INTERNAL = None

# Define metrics
price_age_gauge = None
heatmap_age_gauge = None
rl_conf_hist = None
sheets_error_counter = None
signal_quality_gauge = None
decisions_counter = None
guard_stale_counter = None
veto_context_counter = None
order_placed_counter = None
order_failed_counter = None
fill_total_counter = None
risk_daily_cap_hits_counter = None
ws_reconnects_counter = None
decision_latency_hist = None
order_latency_hist = None
positions_open_gauge = None
risk_used_pct_gauge = None
data_quality_score_gauge = None
guard_would_block_counter = None

def init_metrics(port=8000):
    """Initialize Prometheus metrics server and objects"""
    global price_age_gauge, heatmap_age_gauge, rl_conf_hist, sheets_error_counter
    global signal_quality_gauge, decisions_counter, guard_stale_counter, veto_context_counter
    global order_placed_counter, order_failed_counter, fill_total_counter, risk_daily_cap_hits_counter
    global ws_reconnects_counter, decision_latency_hist, order_latency_hist, positions_open_gauge
    global risk_used_pct_gauge, data_quality_score_gauge, guard_would_block_counter
    global PROM_AVAILABLE

    if PROM_AVAILABLE and start_http_server is not None:
        try:
            start_http_server(port)
            price_age_gauge = Gauge('price_age_seconds', 'Age of latest WebSocket price data in seconds')
            heatmap_age_gauge = Gauge('heatmap_age_seconds', 'Age of latest liquidation heatmap data in seconds')
            rl_conf_hist = Histogram('rl_confidence_score', 'RL model confidence scores', buckets=[0.0,0.2,0.4,0.6,0.8,1.0])
            sheets_error_counter = Counter('sheets_api_errors', 'Google Sheets API error occurrences')
            signal_quality_gauge = Gauge('signal_quality', 'Last generated signal combined confidence')
            decisions_counter = Counter('signal_decisions_total', 'Total signal decisions', ['action'])
            guard_stale_counter = Counter('guard_stale_total', 'Guard stale activations total')
            veto_context_counter = Counter('veto_context_total', 'Context veto activations', ['reason'])
            order_placed_counter = Counter('order_placed_total', 'Orders placed total')
            order_failed_counter = Counter('order_failed_total', 'Orders failed total')
            fill_total_counter = Counter('fill_total', 'Total fills')
            risk_daily_cap_hits_counter = Counter('risk_daily_cap_hits_total', 'Risk daily cap hits total')
            ws_reconnects_counter = Counter('ws_reconnects_total', 'WebSocket reconnect attempts total')
            decision_latency_hist = Histogram('decision_latency_ms', 'Decision latency milliseconds', buckets=[10,50,100,200,500,1000,2000,5000])
            order_latency_hist = Histogram('order_place_latency_ms', 'Order placement latency milliseconds', buckets=[5,10,20,50,100,200,500,1000])
            positions_open_gauge = Gauge('positions_open', 'Number of open positions')
            risk_used_pct_gauge = Gauge('risk_used_pct', 'Risk used percentage (drawdown proxy)')
            data_quality_score_gauge = Gauge('data_quality_score', 'Composite data quality score (0-1)')
            guard_would_block_counter = Counter('guard_would_block_total', 'Times a guard condition would have blocked', ['reason'])
            logger.info(f"Prometheus metrics server started on port {port}")
        except Exception as e:
            PROM_AVAILABLE = False
            logger.warning(f"Prometheus initialization failed: {e}")
