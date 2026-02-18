"""Observability emitters package.

This package provides a comprehensive observability stack for the liquidation bot:

1. ObservabilityHub (emitters.py)
   - Unified coordinator for all observability components
   - Single entry point for all event emission
   - Automatic routing to JSONL, Prometheus, CSV, PostgreSQL, Slack

2. Event Schemas (event_schemas.py)
   - Canonical event structures: DecisionEvent, OrderEvent, FillEvent, HealthEvent, etc.
   - Enums: SignalDirection, SignalStrength, Action, NoTradeReason, etc.
   - Helper functions for ID generation

3. JSONL Logger (stdout_json_logger.py)
   - Rotating file handlers per event type
   - Gzip compression on rotation
   - 1:10 sampling for decision events

4. Prometheus Exporter (prometheus_exporter.py)
   - Full metric set with liqbot_ prefix
   - Counters, gauges, histograms per spec

5. Metrics Facade (metrics_emitter.py)
   - Thin wrapper for metrics calls
   - Context manager for timing

6. OpenTelemetry Tracer (opentelemetry_init.py)
   - Spans for signal_eval, entry_check, order_place, bracket_set
   - OTLP exporter support

7. Slack Notifier (slack_notifier.py)
   - Threshold-based alerting
   - Alert throttling

8. CSV Emitter (sheets_emitter.py)
   - Full decision schema
   - Daily rotation with compression

9. PostgreSQL Emitter (postgres_emitter.py)
   - JSONB storage for all events
   - Async batch inserts
   - Falls back to CSV

Usage:
    # Recommended: Use the unified ObservabilityHub
    from observability.emitters import ObservabilityHub, get_observability_hub
    
    hub = get_observability_hub(run_id='r_123', mode='PAPER')
    
    # Emit decision
    hub.emit_decision(
        signal_dir='LONG',
        signal_strength='STRONG',
        action='PLACE',
        latency_ms=15.3
    )
    
    # Record metrics
    hub.incr('decision_total')
    hub.gauge('equity_usd', 10500.0)
    
    # Trace operations
    with hub.trace_signal_eval(decision_id='dec_123'):
        # ... signal evaluation
        pass
    
    # Or use individual components directly
    from observability.emitters import (
        get_event_logger,
        get_metrics_emitter,
        get_tracer,
        get_slack_notifier,
        get_csv_emitter,
        get_postgres_emitter,
        DecisionEvent, OrderEvent, HealthEvent
    )
"""

# Main coordinator
from .emitters import (
#    ObservabilityHub,
#    get_observability_hub,
    Emitters,  # Legacy compatibility
)

# Event schemas and enums
from .event_schemas import (
    # Base
    BaseEvent,
    # Events
    DecisionEvent,
    GuardEvent,
    VetoEvent,
    OrderEvent,
    FillEvent,
    HealthEvent,
    ErrorEvent,
    # Sub-objects
    ClusterInfo,
    ContextInfo,
    CostsInfo,
    RiskInfo,
    OrderabilityInfo,
    VotesInfo,
    # Enums
    SignalDirection,
    SignalStrength,
    Action,
    NoTradeReason,
    GuardKind,
    VetoReason,
    OrderSide,
    OrderType,
    OrderStatus,
    Severity,
    TradingMode,
    # Helpers
    generate_run_id,
    generate_session_id,
    generate_decision_id,
    slim_decision,
    SLIM_DECISION_FIELDS,
)

# JSONL logger
from .stdout_json_logger import (
    setup_json_logger,
    JSONLEventLogger,
    get_event_logger,
)

# Prometheus exporter
from .prometheus_exporter import (
    PrometheusExporter,
    get_prometheus_exporter,
    PROM_AVAILABLE,
)

# Metrics facade
from .metrics_emitter import (
    MetricsEmitter,
    get_metrics_emitter,
)

# OpenTelemetry tracer
from .opentelemetry_init import (
    init_tracer,
    get_tracer,
    EnhancedTracer,
    SPAN_SIGNAL_EVAL,
    SPAN_ENTRY_CHECK,
    SPAN_ORDER_PLACE,
    SPAN_BRACKET_SET,
)

# Slack notifier
from .slack_notifier import (
    SlackNotifier,
    get_slack_notifier,
)

# CSV emitter
from .sheets_emitter import (
    CSVEmitter,
    get_csv_emitter,
)

# PostgreSQL emitter
from .postgres_emitter import (
    PostgresEmitter,
    get_postgres_emitter,
)

__all__ = [
    # Main coordinator
    "ObservabilityHub",
    "get_observability_hub",
    "Emitters",  # Legacy compatibility
    # Event schemas
    "BaseEvent",
    "DecisionEvent",
    "GuardEvent",
    "VetoEvent",
    "OrderEvent",
    "FillEvent",
    "HealthEvent",
    "ErrorEvent",
    "ClusterInfo",
    "ContextInfo",
    "CostsInfo",
    "RiskInfo",
    "OrderabilityInfo",
    "VotesInfo",
    # Enums
    "SignalDirection",
    "SignalStrength",
    "Action",
    "NoTradeReason",
    "GuardKind",
    "VetoReason",
    "OrderSide",
    "OrderType",
    "OrderStatus",
    "Severity",
    "TradingMode",
    # Helpers
    "generate_run_id",
    "generate_session_id",
    "generate_decision_id",
    "slim_decision",
    "SLIM_DECISION_FIELDS",
    # JSONL
    "setup_json_logger",
    "JSONLEventLogger",
    "get_event_logger",
    # Prometheus
    "PrometheusExporter",
    "get_prometheus_exporter",
    "PROM_AVAILABLE",
    # Metrics
    "MetricsEmitter",
    "get_metrics_emitter",
    # Tracer
    "init_tracer",
    "get_tracer",
    "EnhancedTracer",
    "SPAN_SIGNAL_EVAL",
    "SPAN_ENTRY_CHECK",
    "SPAN_ORDER_PLACE",
    "SPAN_BRACKET_SET",
    # Slack
    "SlackNotifier",
    "get_slack_notifier",
    # CSV
    "CSVEmitter",
    "get_csv_emitter",
    # PostgreSQL
    "PostgresEmitter",
    "get_postgres_emitter",
]

