"""Enhanced JSONL rotating logger with gzip compression and event-type separation.

Features:
- Rotating file handlers per event type (decision, guard, order, fill, health, error)
- Automatic gzip compression of rotated files
- Configurable rotation (128-256MB or daily)
- 1:10 sampling for slim decision events
- Both file and console output
"""
import logging
import json
import os
import gzip
import shutil
import random
import threading
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from typing import Dict, Any, Optional

from .event_schemas import (
    DecisionEvent, GuardEvent, VetoEvent, OrderEvent, FillEvent,
    HealthEvent, ErrorEvent, slim_decision, SLIM_DECISION_FIELDS
)


class GzipRotator:
    """Rotator that compresses rotated log files with gzip."""
    def __call__(self, source, dest):
        if os.path.exists(source):
            with open(source, 'rb') as f_in:
                with gzip.open(f'{dest}.gz', 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            os.remove(source)


class JsonFormatter(logging.Formatter):
    """Format log records as JSON lines."""
    def format(self, record):
        base = {
            "ts": getattr(record, "ts", None) or datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Allow extra structured fields on the record
        try:
            if hasattr(record, 'extra_json') and isinstance(record.extra_json, dict):
                base.update(record.extra_json)
        except Exception:
            pass
        return json.dumps(base, default=str)


class EventJsonFormatter(logging.Formatter):
    """Format event records as JSON lines (for event-specific loggers)."""
    def format(self, record):
        if hasattr(record, 'event_data') and isinstance(record.event_data, dict):
            return json.dumps(record.event_data, default=str)
        return json.dumps({"message": record.getMessage()}, default=str)


class JSONLEventLogger:
    """Event logger that writes structured events to JSONL files with rotation and gzip.
    
    Supports:
    - Per-event-type file separation
    - Size-based rotation (default 128MB)
    - Gzip compression on rotation
    - Sampling for decision events (1:10 slim, 1:1 full on sample)
    """
    
    def __init__(
        self,
        log_dir: Optional[str] = None,
        max_bytes: int = 128 * 1024 * 1024,  # 128MB
        backup_count: int = 10,
        sample_rate: float = 0.1,  # 1:10 for full decision events
        console_output: bool = True
    ):
        self.log_dir = log_dir or os.path.join(os.getcwd(), 'logs', 'events')
        os.makedirs(self.log_dir, exist_ok=True)
        
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self.sample_rate = sample_rate
        self.console_output = console_output
        
        self._lock = threading.Lock()
        self._handlers: Dict[str, logging.Logger] = {}
        
        # Event types to track
        self.event_types = ['decision', 'guard', 'veto', 'order', 'fill', 'health', 'error', 'prediction']
        
        # Initialize loggers for each event type
        for event_type in self.event_types:
            self._create_event_logger(event_type)
    
    def _create_event_logger(self, event_type: str) -> logging.Logger:
        """Create a rotating logger for a specific event type."""
        logger = logging.getLogger(f'liqbot.events.{event_type}')
        logger.setLevel(logging.INFO)
        logger.propagate = False
        
        # Remove existing handlers
        for h in list(logger.handlers):
            logger.removeHandler(h)
        
        # File handler with rotation
        log_path = os.path.join(self.log_dir, f'{event_type}.jsonl')
        handler = RotatingFileHandler(
            log_path,
            maxBytes=self.max_bytes,
            backupCount=self.backup_count
        )
        handler.rotator = GzipRotator()
        handler.setFormatter(EventJsonFormatter())
        logger.addHandler(handler)
        
        # Console handler (optional)
        if self.console_output and event_type in ['error', 'health']:
            console = logging.StreamHandler()
            console.setFormatter(EventJsonFormatter())
            logger.addHandler(console)
        
        self._handlers[event_type] = logger
        return logger
    
    def _should_sample_full(self) -> bool:
        """Determine if this decision should be sampled as full."""
        return random.random() < self.sample_rate
    
    def emit_decision(self, event: DecisionEvent):
        """Emit a decision event with sampling."""
        with self._lock:
            logger = self._handlers.get('decision')
            if not logger:
                return
            
            # Determine if full or slim
            is_full = self._should_sample_full()
            event.is_full_sample = is_full
            
            if is_full:
                data = event.to_dict()
            else:
                data = slim_decision(event)
            
            record = logging.LogRecord(
                name='liqbot.events.decision',
                level=logging.INFO,
                pathname='',
                lineno=0,
                msg='',
                args=(),
                exc_info=None
            )
            record.event_data = data
            logger.handle(record)
    
    def emit_guard(self, event: GuardEvent):
        """Emit a guard event."""
        self._emit_event('guard', event)
    
    def emit_veto(self, event: VetoEvent):
        """Emit a veto event."""
        self._emit_event('veto', event)
    
    def emit_order(self, event: OrderEvent):
        """Emit an order event."""
        self._emit_event('order', event)
    
    def emit_fill(self, event: FillEvent):
        """Emit a fill event."""
        self._emit_event('fill', event)
    
    def emit_health(self, event: HealthEvent):
        """Emit a health event."""
        self._emit_event('health', event)
    
    def emit_prediction(self, event):
        """Emit a prediction event."""
        self._emit_event('prediction', event)
    
    def emit_error(self, event: ErrorEvent):
        """Emit an error event."""
        self._emit_event('error', event)
    
    def _emit_event(self, event_type: str, event):
        """Generic event emission."""
        with self._lock:
            logger = self._handlers.get(event_type)
            if not logger:
                return
            
            data = event.to_dict() if hasattr(event, 'to_dict') else event
            
            record = logging.LogRecord(
                name=f'liqbot.events.{event_type}',
                level=logging.INFO,
                pathname='',
                lineno=0,
                msg='',
                args=(),
                exc_info=None
            )
            record.event_data = data
            logger.handle(record)
    
    def emit_raw(self, event_type: str, data: Dict[str, Any]):
        """Emit raw dict data to an event logger."""
        with self._lock:
            logger = self._handlers.get(event_type)
            if not logger:
                return
            
            record = logging.LogRecord(
                name=f'liqbot.events.{event_type}',
                level=logging.INFO,
                pathname='',
                lineno=0,
                msg='',
                args=(),
                exc_info=None
            )
            record.event_data = data
            logger.handle(record)


# Global singleton
_event_logger: Optional[JSONLEventLogger] = None


def get_event_logger() -> JSONLEventLogger:
    """Get or create the global event logger singleton."""
    global _event_logger
    if _event_logger is None:
        _event_logger = JSONLEventLogger()
    return _event_logger


def setup_json_logger(log_path=None, level=logging.INFO, max_bytes=10 * 1024 * 1024, backup_count=5):
    """Set up a JSON RotatingFileHandler at `log_path` and return the logger.

    If `log_path` is omitted, defaults to `logs/logging.json` under repo root.
    This is the legacy setup for general application logging.
    """
    if not log_path:
        log_path = os.path.join(os.getcwd(), 'logs', 'logging.json')
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    logger = logging.getLogger()
    logger.setLevel(level)

    # Remove duplicate handlers if called multiple times
    for h in list(logger.handlers):
        if isinstance(h, RotatingFileHandler) and getattr(h, '_json_rotating', False):
            logger.removeHandler(h)

    handler = RotatingFileHandler(log_path, maxBytes=max_bytes, backupCount=backup_count)
    handler._json_rotating = True
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)

    # Also install a console handler that mirrors JSON output for stdout
    console = logging.StreamHandler()
    console.setFormatter(JsonFormatter())
    logger.addHandler(console)

    return logger

