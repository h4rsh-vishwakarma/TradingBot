# observability/config_observability.py
"""
Observability configuration with dev vs prod profiles.
Tunes log rotation, sampling, and LLM summary parameters.
"""

import os
from observability.emitters.stdout_json_logger import JSONLEventLogger
from observability.emitters.llm_summary_emitter import LLMSummaryEmitter


def build_observability(env: str = None):
    """
    Build observability components tuned for dev vs prod.
    
    Args:
        env: Environment ('dev' or 'prod'). Defaults to ENV variable or 'prod'.
    
    Returns:
        Tuple of (jsonl_logger, llm_emitter)
    """
    env = env or os.getenv("ENV", "prod")
    
    if env == "dev":
        # Dev profile: smaller files, higher sampling, faster debugging
        jsonl_logger = JSONLEventLogger(
            log_dir="logs/events/dev",
            max_bytes=32 * 1024 * 1024,  # 32MB per file
            backup_count=5,
            sample_rate=0.3  # 30% full decisions for debugging
        )
        llm_emitter = LLMSummaryEmitter(
            output_dir="logs/llm_summaries/dev",
            chunk_max_lines=500  # Small chunks for quick inspection
        )
        
    else:  # prod
        # Prod profile: larger files, lower sampling, storage-efficient
        jsonl_logger = JSONLEventLogger(
            log_dir="logs/events",
            max_bytes=128 * 1024 * 1024,  # 128MB per file
            backup_count=20,
            sample_rate=0.05  # 5% full decisions, rest are slim
        )
        llm_emitter = LLMSummaryEmitter(
            output_dir="logs/llm_summaries",
            chunk_max_lines=5000  # Larger but still LLM-friendly (~5-10MB)
        )
    
    return jsonl_logger, llm_emitter


def get_log_rotation_config(env: str = None) -> dict:
    """
    Get log rotation configuration based on environment.
    
    Returns:
        Dict with max_bytes, backup_count, sample_rate
    """
    env = env or os.getenv("ENV", "prod")
    
    if env == "dev":
        return {
            "max_bytes": 32 * 1024 * 1024,  # 32MB
            "backup_count": 5,
            "sample_rate": 0.3,
            "chunk_max_lines": 500
        }
    else:  # prod
        return {
            "max_bytes": 128 * 1024 * 1024,  # 128MB
            "backup_count": 20,
            "sample_rate": 0.05,
            "chunk_max_lines": 5000
        }


# Rolling rate metrics configuration
ROLLING_METRICS_CONFIG = {
    "error_window_s": 900,  # 15 minutes for error rate
    "guard_window_s": 900,  # 15 minutes for guard rate
    "veto_window_s": 900,  # 15 minutes for veto rate
    "decision_window_s": 3600,  # 1 hour for decision rate
    "compute_interval_s": 60,  # Compute rates every 60 seconds
    "alert_thresholds": {
        "error_rate_15m": 5.0,  # 5 errors per minute = alert
        "guard_rate_15m": 10.0,  # 10 guards per minute = alert
        "veto_rate_15m": 20.0   # 20 vetoes per minute = alert
    }
}


def build_prometheus_exporter(port: int | None = None):
    """Build Prometheus exporter if available.
    
    Args:
        port: HTTP server port. Defaults to PROMETHEUS_PORT env var or 8000.
    
    Returns:
        PrometheusExporter instance if available, else None.
    """
    try:
        from observability.emitters.prometheus_exporter import PrometheusExporter, PROM_AVAILABLE
        if not PROM_AVAILABLE:
            return None
        port = port or int(os.getenv('PROMETHEUS_PORT', '8000'))
        return PrometheusExporter(port=port)
    except Exception:
        return None


def build_postgres_emitter():
    """Build PostgreSQL emitter if enabled and configured.
    
    Requires environment variables:
        - ENABLE_POSTGRES=1
        - POSTGRES_HOST
        - POSTGRES_PORT
        - POSTGRES_DATABASE
        - POSTGRES_USER
        - POSTGRES_PASSWORD
    
    Returns:
        PostgresEmitter instance if enabled, else None.
    """
    if os.getenv('ENABLE_POSTGRES', '0') != '1':
        return None
    
    required_vars = ['POSTGRES_HOST', 'POSTGRES_DATABASE', 'POSTGRES_USER', 'POSTGRES_PASSWORD']
    if not all(os.getenv(var) for var in required_vars):
        return None
    
    try:
        from observability.emitters.postgres_emitter import PostgresEmitter
        return PostgresEmitter(
            host=os.getenv('POSTGRES_HOST'),
            port=int(os.getenv('POSTGRES_PORT', '5432')),
            database=os.getenv('POSTGRES_DATABASE'),
            user=os.getenv('POSTGRES_USER'),
            password=os.getenv('POSTGRES_PASSWORD')
        )
    except Exception:
        return None


def build_slack_notifier():
    """Build Slack notifier with webhook URL.
    
    Requires environment variable:
        - SLACK_WEBHOOK_URL (optional)
    
    Returns:
        SlackNotifier instance (disabled if no webhook configured).
    """
    try:
        from observability.emitters.slack_notifier import SlackNotifier
        webhook_url = os.getenv('SLACK_WEBHOOK_URL')
        return SlackNotifier(webhook_url=webhook_url)
    except Exception:
        # Return a dummy notifier that does nothing
        class DummyNotifier:
            def __init__(self): pass
            def alert_stale_price(self, *args, **kwargs): pass
            def alert_stale_heatmap(self, *args, **kwargs): pass
            def alert_daily_cap_hit(self, *args, **kwargs): pass
            def alert_kill_switch(self, *args, **kwargs): pass
        return DummyNotifier()


def get_observability_config() -> dict:
    """Get complete observability configuration for current environment.
    
    Returns:
        Dictionary with all observability settings.
    """
    env = os.getenv('ENV', 'prod')
    rotation = get_log_rotation_config(env)
    
    return {
        'environment': env,
        'is_production': env == 'prod',
        'event_logger': {
            'log_dir': 'logs/events/dev' if env == 'dev' else 'logs/events',
            'max_bytes': rotation['max_bytes'],
            'backup_count': rotation['backup_count'],
            'sample_rate': rotation['sample_rate'],
            'console_output': env != 'prod'
        },
        'llm_emitter': {
            'output_dir': f"logs/llm_summaries/{env}" if env == 'dev' else 'logs/llm_summaries',
            'chunk_max_lines': rotation['chunk_max_lines']
        },
        'prometheus': {
            'enabled': os.getenv('PROMETHEUS_PORT') is not None,
            'port': int(os.getenv('PROMETHEUS_PORT', '8000'))
        },
        'postgres': {
            'enabled': os.getenv('ENABLE_POSTGRES', '0') == '1',
            'host': os.getenv('POSTGRES_HOST'),
            'database': os.getenv('POSTGRES_DATABASE')
        },
        'slack': {
            'enabled': os.getenv('SLACK_WEBHOOK_URL') is not None
        },
        'rolling_metrics': ROLLING_METRICS_CONFIG
    }
