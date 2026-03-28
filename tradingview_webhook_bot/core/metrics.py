"""
Lightweight Prometheus-compatible metrics — no external dependencies.
Exposes /metrics endpoint with trading bot operational metrics.
"""
import time
import threading
import logging

logger = logging.getLogger(__name__)


class Metrics:
    """Thread-safe metrics collector for trading bot."""

    def __init__(self):
        self._lock = threading.Lock()
        self._counters = {}
        self._gauges = {}
        self._histograms = {}
        self._start_time = time.time()

    def inc(self, name: str, value: float = 1.0, labels: dict = None):
        """Increment a counter."""
        key = self._make_key(name, labels)
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + value

    def set_gauge(self, name: str, value: float, labels: dict = None):
        """Set a gauge value."""
        key = self._make_key(name, labels)
        with self._lock:
            self._gauges[key] = value

    def observe(self, name: str, value: float, labels: dict = None):
        """Record a histogram observation."""
        key = self._make_key(name, labels)
        with self._lock:
            if key not in self._histograms:
                self._histograms[key] = {"count": 0, "sum": 0, "min": float("inf"), "max": 0}
            h = self._histograms[key]
            h["count"] += 1
            h["sum"] += value
            h["min"] = min(h["min"], value)
            h["max"] = max(h["max"], value)

    def _make_key(self, name: str, labels: dict = None) -> str:
        if not labels:
            return name
        label_str = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    def render_prometheus(self) -> str:
        """Render all metrics in Prometheus text exposition format."""
        lines = []
        uptime = time.time() - self._start_time

        # Built-in metrics
        lines.append(f"# HELP bot_uptime_seconds Time since bot started")
        lines.append(f"# TYPE bot_uptime_seconds gauge")
        lines.append(f"bot_uptime_seconds {uptime:.2f}")

        with self._lock:
            # Counters
            seen_names = set()
            for key, val in sorted(self._counters.items()):
                name = key.split("{")[0]
                if name not in seen_names:
                    lines.append(f"# TYPE {name} counter")
                    seen_names.add(name)
                lines.append(f"{key} {val}")

            # Gauges
            seen_names = set()
            for key, val in sorted(self._gauges.items()):
                name = key.split("{")[0]
                if name not in seen_names:
                    lines.append(f"# TYPE {name} gauge")
                    seen_names.add(name)
                lines.append(f"{key} {val}")

            # Histograms (simplified)
            for key, h in sorted(self._histograms.items()):
                name = key.split("{")[0]
                lines.append(f"# TYPE {name} summary")
                lines.append(f"{key}_count {h['count']}")
                lines.append(f"{key}_sum {h['sum']:.4f}")
                if h["count"] > 0:
                    lines.append(f"{key}_avg {h['sum']/h['count']:.4f}")

        return "\n".join(lines) + "\n"


# Global singleton
metrics = Metrics()
