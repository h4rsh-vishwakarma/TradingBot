"""
Alert Rules Configuration for Trading Bot Monitoring
P3: Defines thresholds and conditions for operational alerts
"""

from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum


class AlertSeverity(Enum):
    """Alert severity levels."""
    CRITICAL = "critical"  # Requires immediate action
    WARNING = "warning"    # Requires attention
    INFO = "info"          # Informational only


class AlertChannel(Enum):
    """Where to send alerts."""
    SLACK = "slack"
    PROMETHEUS = "prometheus"
    LOG = "log"
    EMAIL = "email"


@dataclass
class AlertRule:
    """Configuration for a single alert rule."""
    name: str
    description: str
    severity: AlertSeverity
    channels: List[AlertChannel]
    condition: str  # Prometheus query or condition expression
    threshold: float
    duration_seconds: int = 0  # Alert only if condition persists for this duration
    labels: Optional[Dict[str, str]] = None
    annotations: Optional[Dict[str, str]] = None


# P3: ALERT RULES CONFIGURATION
ALERT_RULES = {
    # === Data Staleness Alerts ===
    "price_stale_critical": AlertRule(
        name="PriceDataStaleCritical",
        description="Price data is critically stale (>10s)",
        severity=AlertSeverity.CRITICAL,
        channels=[AlertChannel.SLACK, AlertChannel.PROMETHEUS],
        condition="trading_bot_price_age_seconds > 10",
        threshold=10.0,
        duration_seconds=30,
        labels={"alert_type": "data_staleness", "feed": "price"},
        annotations={
            "summary": "Price data critically stale",
            "action": "Check WebSocket connection and Binance API status"
        }
    ),
    
    "heatmap_stale_warning": AlertRule(
        name="HeatmapDataStaleWarning",
        description="Liquidation heatmap data is stale (>120s)",
        severity=AlertSeverity.WARNING,
        channels=[AlertChannel.SLACK, AlertChannel.LOG],
        condition="trading_bot_heatmap_age_seconds > 120",
        threshold=120.0,
        duration_seconds=300,
        labels={"alert_type": "data_staleness", "feed": "heatmap"},
        annotations={
            "summary": "Liquidation heatmap data stale",
            "action": "Check CoinGlass scraper and Google Sheets sync"
        }
    ),
    
    "oi_stale_warning": AlertRule(
        name="OIDataStaleWarning",
        description="Open Interest data is stale (>300s)",
        severity=AlertSeverity.WARNING,
        channels=[AlertChannel.LOG],
        condition="trading_bot_oi_age_seconds > 300",
        threshold=300.0,
        duration_seconds=600,
        labels={"alert_type": "data_staleness", "feed": "open_interest"}
    ),
    
    # === Risk & Trading Alerts ===
    "daily_cap_hit": AlertRule(
        name="DailyLossCapHit",
        description="Daily loss cap has been hit",
        severity=AlertSeverity.CRITICAL,
        channels=[AlertChannel.SLACK, AlertChannel.PROMETHEUS],
        condition="trading_bot_daily_cap_hit == 1",
        threshold=1.0,
        duration_seconds=0,  # Immediate alert
        labels={"alert_type": "risk_limit"},
        annotations={
            "summary": "Daily loss cap hit - trading stopped",
            "action": "Review today's trades and adjust strategy if needed"
        }
    ),
    
    "kill_switch_active": AlertRule(
        name="KillSwitchActive",
        description="Kill switch has been triggered",
        severity=AlertSeverity.CRITICAL,
        channels=[AlertChannel.SLACK, AlertChannel.PROMETHEUS],
        condition="trading_bot_kill_switch_active == 1",
        threshold=1.0,
        duration_seconds=0,
        labels={"alert_type": "risk_limit"},
        annotations={
            "summary": "Kill switch triggered - all trading stopped",
            "action": "Investigate kill switch reason and resolve before resuming"
        }
    ),
    
    "risk_usage_high": AlertRule(
        name="RiskUsageHigh",
        description="Risk usage exceeds 80%",
        severity=AlertSeverity.WARNING,
        channels=[AlertChannel.LOG],
        condition="trading_bot_risk_used_pct > 80",
        threshold=80.0,
        duration_seconds=600,
        labels={"alert_type": "risk_limit"}
    ),
    
    # === Performance Alerts ===
    "drawdown_warning": AlertRule(
        name="DrawdownWarning",
        description="Drawdown exceeds 5% of equity",
        severity=AlertSeverity.WARNING,
        channels=[AlertChannel.SLACK, AlertChannel.LOG],
        condition="(trading_bot_equity_usd - trading_bot_equity_high_watermark) / trading_bot_equity_high_watermark < -0.05",
        threshold=-0.05,
        duration_seconds=1800,  # 30 minutes
        labels={"alert_type": "performance"}
    ),
    
    "consecutive_losses": AlertRule(
        name="ConsecutiveLossesHigh",
        description="5 or more consecutive losing trades",
        severity=AlertSeverity.WARNING,
        channels=[AlertChannel.SLACK],
        condition="trading_bot_consecutive_losses >= 5",
        threshold=5.0,
        duration_seconds=0,
        labels={"alert_type": "performance"},
        annotations={
            "summary": "Multiple consecutive losses detected",
            "action": "Review recent trade quality and market conditions"
        }
    ),
    
    # === System Health Alerts ===
    "websocket_reconnects_high": AlertRule(
        name="WebSocketReconnectsHigh",
        description="Excessive WebSocket reconnections (>5/hour)",
        severity=AlertSeverity.WARNING,
        channels=[AlertChannel.LOG],
        condition="rate(trading_bot_ws_reconnect_count[1h]) > 5",
        threshold=5.0,
        duration_seconds=3600,
        labels={"alert_type": "connectivity"}
    ),
    
    "decision_latency_high": AlertRule(
        name="DecisionLatencyHigh",
        description="Decision latency exceeds 500ms",
        severity=AlertSeverity.WARNING,
        channels=[AlertChannel.LOG],
        condition="trading_bot_decision_latency_ms > 500",
        threshold=500.0,
        duration_seconds=600,
        labels={"alert_type": "performance"}
    ),
    
    # === Veto Rate Alerts ===
    "veto_rate_spike": AlertRule(
        name="VetoRateSpike",
        description="Veto rate exceeds 50% (indicating systematic issues)",
        severity=AlertSeverity.WARNING,
        channels=[AlertChannel.SLACK, AlertChannel.LOG],
        condition="rate(trading_bot_veto_total[5m]) / rate(trading_bot_decision_total[5m]) > 0.5",
        threshold=0.5,
        duration_seconds=300,
        labels={"alert_type": "strategy"},
        annotations={
            "summary": "High veto rate detected",
            "action": "Check veto reasons in logs - likely data staleness or regime filters"
        }
    ),
    
    "no_trades_extended": AlertRule(
        name="NoTradesExtended",
        description="No trades executed in 24 hours",
        severity=AlertSeverity.WARNING,
        channels=[AlertChannel.SLACK],
        condition="time() - trading_bot_last_trade_timestamp > 86400",
        threshold=86400.0,
        duration_seconds=0,
        labels={"alert_type": "strategy"},
        annotations={
            "summary": "No trades in 24 hours",
            "action": "Review NO_TRADE reasons and check if filters are too conservative"
        }
    ),
}


# Prometheus AlertManager configuration template
PROMETHEUS_ALERT_CONFIG = """
groups:
  - name: trading_bot_alerts
    interval: 30s
    rules:
"""

def generate_prometheus_rules() -> str:
    """
    Generate Prometheus alerting rules YAML configuration.
    
    Returns:
        YAML string with all alert rules
    """
    yaml_rules = PROMETHEUS_ALERT_CONFIG
    
    for rule_id, rule in ALERT_RULES.items():
        if AlertChannel.PROMETHEUS in rule.channels:
            yaml_rules += f"""
      - alert: {rule.name}
        expr: {rule.condition}
        for: {rule.duration_seconds}s
        labels:
          severity: {rule.severity.value}
"""
            if rule.labels:
                for k, v in rule.labels.items():
                    yaml_rules += f"          {k}: {v}\n"
            
            yaml_rules += "        annotations:\n"
            yaml_rules += f"          description: {rule.description}\n"
            
            if rule.annotations:
                for k, v in rule.annotations.items():
                    yaml_rules += f"          {k}: {v}\n"
    
    return yaml_rules


# Slack notification thresholds
SLACK_THRESHOLDS = {
    "min_pnl_notify": 10.0,  # Notify on trades with |PnL| > $10
    "min_drawdown_notify_pct": 3.0,  # Notify on drawdown > 3%
    "critical_price_age_s": 10.0,
    "critical_heatmap_age_s": 300.0,
}


def should_alert_slack(alert_rule: AlertRule, metric_value: float) -> bool:
    """
    Determine if a Slack alert should be sent.
    
    Args:
        alert_rule: The alert rule configuration
        metric_value: Current value of the metric
        
    Returns:
        True if alert should be sent to Slack
    """
    if AlertChannel.SLACK not in alert_rule.channels:
        return False
    
    if alert_rule.severity == AlertSeverity.CRITICAL:
        return True  # Always alert on critical
    
    # For warnings, check threshold
    if alert_rule.severity == AlertSeverity.WARNING:
        if alert_rule.condition.find('>') >= 0:
            return metric_value > alert_rule.threshold
        elif alert_rule.condition.find('<') >= 0:
            return metric_value < alert_rule.threshold
    
    return False


if __name__ == "__main__":
    # Generate and print Prometheus rules
    print("=" * 80)
    print("PROMETHEUS ALERTING RULES")
    print("=" * 80)
    print(generate_prometheus_rules())
    
    print("\n" + "=" * 80)
    print("CONFIGURED ALERTS")
    print("=" * 80)
    for rule_id, rule in ALERT_RULES.items():
        print(f"\n{rule.name} ({rule.severity.value}):")
        print(f"  Condition: {rule.condition}")
        print(f"  Channels: {', '.join([c.value for c in rule.channels])}")
        print(f"  Description: {rule.description}")
