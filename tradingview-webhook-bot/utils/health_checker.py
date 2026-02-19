"""
Health Check & Metrics System for Trading Bot

Provides:
- Health check endpoint with component status
- Prometheus-compatible metrics
- System resource monitoring
- Trading metrics (signals, orders, P&L)
"""

import time
import psutil
import threading
from datetime import datetime, timezone
from typing import Dict, Optional, Any
from dataclasses import dataclass, asdict


@dataclass
class ComponentHealth:
    """Health status of a bot component"""
    component: str
    status: str  # 'healthy', 'degraded', 'unhealthy'
    last_check: datetime
    message: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


@dataclass
class TradingMetrics:
    """Trading performance metrics"""
    signals_received: int = 0
    signals_processed: int = 0
    signals_failed: int = 0
    orders_placed: int = 0
    orders_filled: int = 0
    orders_rejected: int = 0
    positions_opened: int = 0
    positions_closed: int = 0
    total_pnl: float = 0.0
    win_rate: float = 0.0
    uptime_seconds: int = 0


class HealthChecker:
    """
    Health check and metrics collection system.
    
    Tracks:
    - Component health (webhook, signal processor, order manager)
    - System resources (CPU, memory, disk)
    - Trading metrics (signals, orders, P&L)
    - Uptime and performance
    """
    
    def __init__(self, strategy_name: str):
        """
        Initialize health checker.
        
        Args:
            strategy_name: Strategy identifier
        """
        self.strategy_name = strategy_name
        self.start_time = time.time()
        
        # Component health status
        self.component_health: Dict[str, ComponentHealth] = {}
        
        # Trading metrics
        self.metrics = TradingMetrics()
        
        # Metrics lock
        self.lock = threading.Lock()
        
        # Last activity timestamps
        self.last_signal_time: Optional[float] = None
        self.last_order_time: Optional[float] = None
        
    def update_component_health(self, component: str, status: str, 
                                message: Optional[str] = None,
                                details: Optional[Dict] = None):
        """
        Update health status of a component.
        
        Args:
            component: Component name (e.g., 'webhook_server', 'signal_processor')
            status: 'healthy', 'degraded', or 'unhealthy'
            message: Optional status message
            details: Optional additional details
        """
        with self.lock:
            self.component_health[component] = ComponentHealth(
                component=component,
                status=status,
                last_check=datetime.now(timezone.utc),
                message=message,
                details=details
            )
    
    def increment_signals_received(self):
        """Increment signals received counter"""
        with self.lock:
            self.metrics.signals_received += 1
            self.last_signal_time = time.time()
    
    def increment_signals_processed(self):
        """Increment signals processed counter"""
        with self.lock:
            self.metrics.signals_processed += 1
    
    def increment_signals_failed(self):
        """Increment signals failed counter"""
        with self.lock:
            self.metrics.signals_failed += 1
    
    def increment_orders_placed(self):
        """Increment orders placed counter"""
        with self.lock:
            self.metrics.orders_placed += 1
            self.last_order_time = time.time()
    
    def increment_orders_filled(self):
        """Increment orders filled counter"""
        with self.lock:
            self.metrics.orders_filled += 1
    
    def increment_orders_rejected(self):
        """Increment orders rejected counter"""
        with self.lock:
            self.metrics.orders_rejected += 1
    
    def increment_positions_opened(self):
        """Increment positions opened counter"""
        with self.lock:
            self.metrics.positions_opened += 1
    
    def increment_positions_closed(self, pnl: float):
        """
        Increment positions closed and update P&L.
        
        Args:
            pnl: Profit/loss from closed position
        """
        with self.lock:
            self.metrics.positions_closed += 1
            self.metrics.total_pnl += pnl
            
            # Update win rate
            if self.metrics.positions_closed > 0:
                # Assume winning if pnl > 0
                wins = sum(1 for _ in range(self.metrics.positions_closed) if pnl > 0)
                self.metrics.win_rate = wins / self.metrics.positions_closed
    
    def get_health_status(self) -> Dict[str, Any]:
        """
        Get comprehensive health status.
        
        Returns:
            Health status dict with all components and metrics
        """
        with self.lock:
            # Calculate uptime
            uptime = int(time.time() - self.start_time)
            
            # Overall health
            unhealthy_components = [
                c for c in self.component_health.values() 
                if c.status == 'unhealthy'
            ]
            degraded_components = [
                c for c in self.component_health.values() 
                if c.status == 'degraded'
            ]
            
            if unhealthy_components:
                overall_status = 'unhealthy'
            elif degraded_components:
                overall_status = 'degraded'
            else:
                overall_status = 'healthy'
            
            # System resources
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            return {
                'status': overall_status,
                'strategy': self.strategy_name,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'uptime_seconds': uptime,
                'components': {
                    comp.component: {
                        'status': comp.status,
                        'message': comp.message,
                        'last_check': comp.last_check.isoformat(),
                        'details': comp.details
                    }
                    for comp in self.component_health.values()
                },
                'system': {
                    'cpu_percent': cpu_percent,
                    'memory_percent': memory.percent,
                    'memory_available_mb': memory.available / (1024 * 1024),
                    'disk_percent': disk.percent,
                    'disk_free_gb': disk.free / (1024 ** 3)
                },
                'trading': {
                    'signals_received': self.metrics.signals_received,
                    'signals_processed': self.metrics.signals_processed,
                    'signals_failed': self.metrics.signals_failed,
                    'orders_placed': self.metrics.orders_placed,
                    'orders_filled': self.metrics.orders_filled,
                    'orders_rejected': self.metrics.orders_rejected,
                    'positions_opened': self.metrics.positions_opened,
                    'positions_closed': self.metrics.positions_closed,
                    'total_pnl': self.metrics.total_pnl,
                    'win_rate': self.metrics.win_rate
                },
                'activity': {
                    'last_signal_seconds_ago': int(time.time() - self.last_signal_time) if self.last_signal_time else None,
                    'last_order_seconds_ago': int(time.time() - self.last_order_time) if self.last_order_time else None
                }
            }
    
    def get_prometheus_metrics(self) -> str:
        """
        Get metrics in Prometheus format.
        
        Returns:
            Prometheus-formatted metrics string
        """
        with self.lock:
            uptime = int(time.time() - self.start_time)
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            
            metrics = []
            
            # Uptime
            metrics.append(f'# HELP bot_uptime_seconds Bot uptime in seconds')
            metrics.append(f'# TYPE bot_uptime_seconds counter')
            metrics.append(f'bot_uptime_seconds{{strategy="{self.strategy_name}"}} {uptime}')
            
            # Signals
            metrics.append(f'# HELP bot_signals_received_total Total signals received')
            metrics.append(f'# TYPE bot_signals_received_total counter')
            metrics.append(f'bot_signals_received_total{{strategy="{self.strategy_name}"}} {self.metrics.signals_received}')
            
            metrics.append(f'# HELP bot_signals_processed_total Total signals processed')
            metrics.append(f'# TYPE bot_signals_processed_total counter')
            metrics.append(f'bot_signals_processed_total{{strategy="{self.strategy_name}"}} {self.metrics.signals_processed}')
            
            metrics.append(f'# HELP bot_signals_failed_total Total signals failed')
            metrics.append(f'# TYPE bot_signals_failed_total counter')
            metrics.append(f'bot_signals_failed_total{{strategy="{self.strategy_name}"}} {self.metrics.signals_failed}')
            
            # Orders
            metrics.append(f'# HELP bot_orders_placed_total Total orders placed')
            metrics.append(f'# TYPE bot_orders_placed_total counter')
            metrics.append(f'bot_orders_placed_total{{strategy="{self.strategy_name}"}} {self.metrics.orders_placed}')
            
            metrics.append(f'# HELP bot_orders_filled_total Total orders filled')
            metrics.append(f'# TYPE bot_orders_filled_total counter')
            metrics.append(f'bot_orders_filled_total{{strategy="{self.strategy_name}"}} {self.metrics.orders_filled}')
            
            # Positions
            metrics.append(f'# HELP bot_positions_opened_total Total positions opened')
            metrics.append(f'# TYPE bot_positions_opened_total counter')
            metrics.append(f'bot_positions_opened_total{{strategy="{self.strategy_name}"}} {self.metrics.positions_opened}')
            
            metrics.append(f'# HELP bot_positions_closed_total Total positions closed')
            metrics.append(f'# TYPE bot_positions_closed_total counter')
            metrics.append(f'bot_positions_closed_total{{strategy="{self.strategy_name}"}} {self.metrics.positions_closed}')
            
            # P&L
            metrics.append(f'# HELP bot_total_pnl Total profit/loss')
            metrics.append(f'# TYPE bot_total_pnl gauge')
            metrics.append(f'bot_total_pnl{{strategy="{self.strategy_name}"}} {self.metrics.total_pnl}')
            
            metrics.append(f'# HELP bot_win_rate Win rate (0-1)')
            metrics.append(f'# TYPE bot_win_rate gauge')
            metrics.append(f'bot_win_rate{{strategy="{self.strategy_name}"}} {self.metrics.win_rate}')
            
            # System resources
            metrics.append(f'# HELP bot_cpu_percent CPU usage percentage')
            metrics.append(f'# TYPE bot_cpu_percent gauge')
            metrics.append(f'bot_cpu_percent{{strategy="{self.strategy_name}"}} {cpu_percent}')
            
            metrics.append(f'# HELP bot_memory_percent Memory usage percentage')
            metrics.append(f'# TYPE bot_memory_percent gauge')
            metrics.append(f'bot_memory_percent{{strategy="{self.strategy_name}"}} {memory.percent}')
            
            return '\n'.join(metrics) + '\n'


# Global instance
_health_checker: Optional[HealthChecker] = None


def get_health_checker(strategy_name: Optional[str] = None) -> HealthChecker:
    """
    Get or create global health checker instance.
    
    Args:
        strategy_name: Strategy name (required for first call)
        
    Returns:
        HealthChecker instance
    """
    global _health_checker
    
    if _health_checker is None:
        if strategy_name is None:
            raise ValueError("strategy_name required for first call")
        _health_checker = HealthChecker(strategy_name)
    
    return _health_checker
