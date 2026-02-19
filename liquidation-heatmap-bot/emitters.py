"""
Fixed Emitters module with proper event routing and JSONL logging.

This module provides unified observability for the trading bot:
- JSONL event logging with rotation and gzip compression
- Per-event-type file separation (decision, guard, veto, order, fill, health, error)
- Prometheus metrics export
- CSV file export
- LLM-friendly summary generation

DEPLOYMENT: Copy this file to /home/ubuntu/trading_bot/emitters.py on the server
"""
import os
import json
import gzip
import shutil
import time
import threading
import logging
import traceback
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict

# Prometheus (optional)
try:
    from prometheus_client import Counter, Gauge, Histogram, start_http_server
    PROM_AVAILABLE = True
except ImportError:
    PROM_AVAILABLE = False

# OpenTelemetry (optional)
try:
    from opentelemetry import trace
    OTEL_AVAILABLE = True
    tracer = trace.get_tracer(__name__)
except ImportError:
    OTEL_AVAILABLE = False

logger = logging.getLogger(__name__)


# ============================================================================
# EVENT SCHEMAS
# ============================================================================

@dataclass
class BaseEvent:
    """Base event with common fields."""
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    run_id: str = field(default_factory=lambda: os.getenv('RUN_ID', f'r_{uuid.uuid4().hex[:8]}'))
    session_id: str = field(default_factory=lambda: os.getenv('SESSION_ID', f's_{uuid.uuid4().hex[:8]}'))
    venue: str = "binanceusdm"
    symbol: str = "BTCUSDT"
    env: str = field(default_factory=lambda: os.getenv('ENV', 'dev'))
    mode: str = field(default_factory=lambda: os.getenv('TRADING_MODE', 'PAPER'))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


# ============================================================================
# ROTATING JSONL WRITER
# ============================================================================

class RotatingJSONLWriter:
    """Size-based rotating JSONL writer with gzip compression of rotated files.
    
    Handles external log rotation by detecting when file has been moved/renamed
    and automatically reopening the current file.
    """
    
    def __init__(self, path: str, max_bytes: int = 50 * 1024 * 1024):
        """
        Args:
            path: File path for the JSONL file
            max_bytes: Maximum file size before rotation (default: 50MB)
        """
        self.path = path
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        self._last_inode = None
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        
        # Open file in append mode
        self._fh = open(self.path, 'a', encoding='utf-8')
        self._update_inode()
        logger.info(f"RotatingJSONLWriter initialized: {path}")

    def _update_inode(self):
        """Update the cached inode number."""
        try:
            if os.path.exists(self.path):
                self._last_inode = os.stat(self.path).st_ino
        except Exception:
            self._last_inode = None

    def _check_external_rotation(self):
        """Check if file was rotated externally and reopen if needed."""
        try:
            # If file doesn't exist or inode changed, it was rotated externally
            if not os.path.exists(self.path):
                logger.info(f"Log file {self.path} rotated externally, reopening...")
                self._fh.close()
                self._fh = open(self.path, 'a', encoding='utf-8')
                self._update_inode()
                return True
            
            current_inode = os.stat(self.path).st_ino
            if current_inode != self._last_inode:
                logger.info(f"Log file {self.path} inode changed (external rotation), reopening...")
                self._fh.close()
                self._fh = open(self.path, 'a', encoding='utf-8')
                self._update_inode()
                return True
                
        except Exception as e:
            logger.error(f"Error checking external rotation: {e}")
            try:
                self._fh.close()
                self._fh = open(self.path, 'a', encoding='utf-8')
                self._update_inode()
            except Exception as ex:
                logger.error(f"Failed to reopen file: {ex}")
        
        return False

    def _rotate_if_needed(self):
        """Rotate file if size exceeds threshold."""
        try:
            self._fh.flush()
            if os.path.exists(self.path):
                size = os.path.getsize(self.path)
                if size >= self.max_bytes:
                    self._fh.close()
                    
                    # Create timestamped rotated filename
                    ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
                    rotated = f"{self.path}.{ts}"
                    os.rename(self.path, rotated)
                    
                    # Gzip the rotated file
                    with open(rotated, 'rb') as f_in:
                        with gzip.open(f"{rotated}.gz", 'wb') as f_out:
                            shutil.copyfileobj(f_in, f_out)
                    os.remove(rotated)
                    
                    # Reopen main file
                    self._fh = open(self.path, 'a', encoding='utf-8')
                    self._update_inode()
                    logger.info(f"Rotated log file: {self.path}")
        except FileNotFoundError:
            self._fh = open(self.path, 'a', encoding='utf-8')
            self._update_inode()
        except Exception as e:
            logger.error(f"Rotation error: {e}")

    def write(self, obj: Dict[str, Any]):
        """Write a dictionary as a JSON line."""
        with self._lock:
            try:
                # Check for external rotation before writing
                self._check_external_rotation()
                
                line = json.dumps(obj, default=str, ensure_ascii=False)
                self._fh.write(line + "\n")
                self._fh.flush()
                self._rotate_if_needed()
            except Exception as e:
                logger.error(f"Write error: {e}")
                # Try to recover by reopening the file
                try:
                    self._fh.close()
                    self._fh = open(self.path, 'a', encoding='utf-8')
                    self._update_inode()
                except Exception as ex:
                    logger.error(f"Failed to recover from write error: {ex}")

    def close(self):
        """Close the file handle."""
        with self._lock:
            if self._fh:
                self._fh.close()


# ============================================================================
# CSV EMITTER
# ============================================================================

class CSVEmitter:
    """CSV emitter with proper headers and date-stamped files."""
    
    def __init__(self, out_dir: str = None):
        self.out_dir = out_dir or os.path.join(os.getcwd(), 'logs', 'csv')
        os.makedirs(self.out_dir, exist_ok=True)
        self.files: Dict[str, Any] = {}
        self.locks: Dict[str, threading.Lock] = {}
        self._date_suffix = datetime.now(timezone.utc).strftime('%Y%m%d')
        logger.info(f"CSVEmitter initialized: {self.out_dir}")

    def _get_file_path(self, name: str) -> str:
        """Get date-stamped file path."""
        return os.path.join(self.out_dir, f"{name}_{self._date_suffix}.csv")

    def _ensure_file(self, name: str, headers: List[str]):
        """Ensure CSV file exists with headers."""
        if name not in self.files:
            self.locks[name] = threading.Lock()
            path = self._get_file_path(name)
            first = not os.path.exists(path)
            fh = open(path, 'a', newline='', encoding='utf-8')
            if first:
                fh.write(','.join(headers) + '\n')
                fh.flush()
            self.files[name] = (fh, headers)

    def _write_row(self, name: str, row: Dict[str, Any], headers: List[str]):
        """Write a row to the CSV file."""
        self._ensure_file(name, headers)
        fh, _ = self.files[name]
        lock = self.locks[name]
        
        with lock:
            values = [str(row.get(h, '')) for h in headers]
            fh.write(','.join(values) + '\n')
            fh.flush()

    def insert_decision(self, payload: Dict[str, Any]):
        """Insert a decision row."""
        headers = [
            'ts', 'run_id', 'session_id', 'decision_id', 'signal_dir', 'signal_strength',
            'S_long', 'S_short', 'votes_m1', 'votes_m2', 'votes_m3', 'tie_break_used',
            'cluster_timeframe', 'cluster_target_level', 'cluster_intensity_z', 'cluster_distance_bps',
            'oi_delta_30m_bps', 'funding_pct', 'lsr', 'post_shock_flag', 'funding_window_block',
            'spread_bps', 'est_slip_bps', 'edge_bps', 'edge_ok',
            'entry_px', 'stop_px', 'tp_px', 'qty',
            'action', 'no_trade_reason', 'latency_ms', 'market_regime'
        ]
        
        cluster = payload.get('cluster') or {}
        context = payload.get('context') or {}
        costs = payload.get('costs') or {}
        votes = payload.get('votes') or {}
        
        row = {
            'ts': payload.get('ts'),
            'run_id': payload.get('run_id'),
            'session_id': payload.get('session_id'),
            'decision_id': payload.get('decision_id'),
            'signal_dir': payload.get('signal_dir'),
            'signal_strength': payload.get('signal_strength'),
            'S_long': payload.get('S_long'),
            'S_short': payload.get('S_short'),
            'votes_m1': votes.get('m1'),
            'votes_m2': votes.get('m2'),
            'votes_m3': votes.get('m3'),
            'tie_break_used': payload.get('tie_break_used'),
            'cluster_timeframe': cluster.get('timeframe'),
            'cluster_target_level': cluster.get('target_level'),
            'cluster_intensity_z': cluster.get('intensity_z'),
            'cluster_distance_bps': cluster.get('distance_bps'),
            'oi_delta_30m_bps': context.get('oi_delta_30m_bps'),
            'funding_pct': context.get('funding_pct'),
            'lsr': context.get('lsr'),
            'post_shock_flag': context.get('post_shock_flag'),
            'funding_window_block': context.get('funding_window_block'),
            'spread_bps': costs.get('spread_bps'),
            'est_slip_bps': costs.get('est_slip_bps'),
            'edge_bps': costs.get('edge_bps'),
            'edge_ok': costs.get('edge_ok'),
            'entry_px': payload.get('entry_px'),
            'stop_px': payload.get('stop_px'),
            'tp_px': payload.get('tp_px'),
            'qty': payload.get('qty'),
            'action': payload.get('action'),
            'no_trade_reason': payload.get('no_trade_reason'),
            'latency_ms': payload.get('latency_ms'),
            'market_regime': payload.get('market_regime')
        }
        self._write_row('decisions', row, headers)

    def insert_order(self, payload: Dict[str, Any]):
        """Insert an order row."""
        headers = ['ts', 'run_id', 'session_id', 'order_id', 'decision_id', 'side', 'type', 
                   'px', 'qty', 'status', 'latency_ms', 'reduce_only', 'time_in_force']
        self._write_row('orders', payload, headers)

    def insert_fill(self, payload: Dict[str, Any]):
        """Insert a fill row."""
        headers = ['ts', 'run_id', 'session_id', 'fill_id', 'order_id', 'px', 'qty', 
                   'fee', 'pnl_close', 'r_multiple', 'exit_type', 'hold_duration_s']
        self._write_row('fills', payload, headers)

    def insert_guard(self, payload: Dict[str, Any]):
        """Insert a guard row."""
        headers = ['ts', 'run_id', 'session_id', 'kind', 'details']
        row = {
            'ts': payload.get('ts'),
            'run_id': payload.get('run_id'),
            'session_id': payload.get('session_id'),
            'kind': payload.get('kind'),
            'details': json.dumps(payload.get('details', {}))
        }
        self._write_row('guards', row, headers)

    def insert_veto(self, payload: Dict[str, Any]):
        """Insert a veto row."""
        headers = ['ts', 'run_id', 'session_id', 'reason', 'fields']
        row = {
            'ts': payload.get('ts'),
            'run_id': payload.get('run_id'),
            'session_id': payload.get('session_id'),
            'reason': payload.get('reason'),
            'fields': json.dumps(payload.get('fields', {}))
        }
        self._write_row('vetoes', row, headers)

    def insert_health(self, payload: Dict[str, Any]):
        """Insert a health row."""
        headers = ['ts', 'run_id', 'session_id', 'price_age_s', 'heatmap_age_s', 
                   'oi_age_s', 'funding_age_s', 'lsr_age_s',
                   'ws_connected', 'ws_reconnect_count', 'coinglass_ok',
                   'positions_open', 'risk_used_pct', 'daily_cap_hit',
                   'equity_usd', 'pnl_realized_usd', 'kill_switch_active', 'kill_switch_reason']
        self._write_row('health', payload, headers)

    def insert_error(self, payload: Dict[str, Any]):
        """Insert an error row."""
        headers = ['ts', 'run_id', 'session_id', 'severity', 'component', 'message', 
                   'exc_type', 'exc_msg', 'decision_id', 'order_id']
        self._write_row('errors', payload, headers)

    def close(self):
        """Close all file handles."""
        for name, (fh, _) in self.files.items():
            try:
                fh.close()
            except Exception:
                pass


# ============================================================================
# UNIFIED EMITTERS CLASS
# ============================================================================

class Emitters:
    """
    Unified observability hub for the trading bot.
    
    Provides:
    - JSONL event logging per event type with rotation
    - Prometheus metrics
    - CSV export
    - Structured logging
    
    Usage:
        emitters = Emitters(run_id='r_abc123', session_id='s_def456')
        emitters.emit_decision(decision_event_dict)
        emitters.emit_order(order_event_dict)
        emitters.emit_health(price_age_s=0.5, ...)
    """
    
    def __init__(
        self,
        run_id: str,
        session_id: str,
        venue: str = 'binanceusdm',
        symbol: str = 'BTCUSDT',
        env: str = 'dev',
        mode: str = 'PAPER',
        out_dir: str = None,
        csv_dir: str = None,
        sample_rate: int = 10,
        rotate_bytes: int = 50 * 1024 * 1024,
        prometheus_port: int = 8000
    ):
        self.run_id = run_id
        self.session_id = session_id
        self.venue = venue
        self.symbol = symbol
        self.env = env
        self.mode = mode
        self.sample_rate = max(1, int(sample_rate))
        self._sample_counter = 0
        
        # Set environment variables for child components
        os.environ['RUN_ID'] = self.run_id
        os.environ['SESSION_ID'] = self.session_id
        os.environ['ENV'] = self.env
        os.environ['TRADING_MODE'] = self.mode
        
        # JSONL writers per event type
        self.out_dir = out_dir or os.path.join(os.getcwd(), 'logs', 'events')
        os.makedirs(self.out_dir, exist_ok=True)
        
        self.rotate_bytes = rotate_bytes
        self.writers: Dict[str, RotatingJSONLWriter] = {}
        
        # Pre-create writers for all event types
        event_types = ['decision', 'guard', 'veto', 'order', 'fill', 'health', 'error', 'session']
        for et in event_types:
            self._get_writer(et)
        
        # CSV emitter
        csv_out = csv_dir or os.path.join(os.getcwd(), 'logs', 'csv')
        self.csv = CSVEmitter(out_dir=csv_out)
        
        # Dashboard removed due to initialization issues
        self.live_dashboard = None
        
        # Prometheus metrics
        self.prom: Optional[Dict[str, Any]] = None
        if PROM_AVAILABLE:
            try:
                self._setup_prometheus(prometheus_port)
            except Exception as e:
                logger.warning(f"Prometheus setup failed: {e}")
        
        # Session tracking for summary
        self._session_stats = {
            'decisions': 0,
            'trades': 0,
            'wins': 0,
            'losses': 0,
            'total_pnl': 0.0,
            'total_fees': 0.0,
            'session_start': datetime.now(timezone.utc).isoformat()
        }
        
        logger.info(f"Emitters initialized: run_id={run_id}, session_id={session_id}, out_dir={self.out_dir}")

    def _get_writer(self, event_type: str) -> RotatingJSONLWriter:
        """Get or create a writer for an event type."""
        if event_type not in self.writers:
            path = os.path.join(self.out_dir, f"{event_type}.jsonl")
            self.writers[event_type] = RotatingJSONLWriter(path, max_bytes=self.rotate_bytes)
        return self.writers[event_type]

    def _base_event(self) -> Dict[str, Any]:
        """Return base event fields."""
        return {
            'ts': datetime.now(timezone.utc).isoformat(),
            'run_id': self.run_id,
            'session_id': self.session_id,
            'venue': self.venue,
            'symbol': self.symbol,
            'env': self.env,
            'mode': self.mode
        }

    def _setup_prometheus(self, port: int = 8000):
        """Set up Prometheus metrics."""
        self.prom = {}
        
        # Counters
        self.prom['decision_total'] = Counter('liqbot_decision_total', 'Total decisions', ['action'])
        self.prom['decision_no_trade_total'] = Counter('liqbot_decision_no_trade_total', 'No-trade decisions', ['reason'])
        self.prom['guard_total'] = Counter('liqbot_guard_total', 'Guard triggers', ['kind'])
        self.prom['veto_total'] = Counter('liqbot_veto_total', 'Context vetoes', ['reason'])
        self.prom['order_placed_total'] = Counter('liqbot_order_placed_total', 'Orders placed')
        self.prom['order_failed_total'] = Counter('liqbot_order_failed_total', 'Order failures')
        self.prom['fill_total'] = Counter('liqbot_fill_total', 'Fills')
        self.prom['risk_daily_cap_hits_total'] = Counter('liqbot_risk_daily_cap_hits_total', 'Daily cap hits')
        self.prom['ws_reconnects_total'] = Counter('liqbot_ws_reconnects_total', 'WS reconnects')
        self.prom['error_total'] = Counter('liqbot_error_total', 'Errors', ['severity', 'component'])
        
        # Gauges
        self.prom['feed_price_age_seconds'] = Gauge('liqbot_feed_price_age_seconds', 'Price feed age')
        self.prom['feed_heatmap_age_seconds'] = Gauge('liqbot_feed_heatmap_age_seconds', 'Heatmap age')
        self.prom['feed_oi_age_seconds'] = Gauge('liqbot_feed_oi_age_seconds', 'OI data age')
        self.prom['feed_funding_age_seconds'] = Gauge('liqbot_feed_funding_age_seconds', 'Funding rate age')
        self.prom['feed_lsr_age_seconds'] = Gauge('liqbot_feed_lsr_age_seconds', 'LSR data age')
        self.prom['positions_open'] = Gauge('liqbot_positions_open', 'Open positions')
        self.prom['risk_used_pct'] = Gauge('liqbot_risk_used_pct', 'Risk used percent')
        self.prom['equity_usd'] = Gauge('liqbot_equity_usd', 'Equity USD')
        self.prom['pnl_realized_usd'] = Gauge('liqbot_pnl_realized_usd', 'Realized PnL USD')
        self.prom['kill_switch_active'] = Gauge('liqbot_kill_switch_active', 'Kill switch status')
        
        # Histograms
        self.prom['decision_latency_ms'] = Histogram('liqbot_decision_latency_ms', 'Decision latency',
                                                      buckets=[1, 5, 10, 25, 50, 100, 250, 500, 1000])
        self.prom['order_place_latency_ms'] = Histogram('liqbot_order_place_latency_ms', 'Order latency',
                                                         buckets=[10, 25, 50, 100, 250, 500, 1000, 2500])
        
        # Start HTTP server
        try:
            threading.Thread(target=start_http_server, args=(port,), daemon=True).start()
            logger.info(f"Prometheus metrics server started on port {port}")
        except Exception as e:
            logger.warning(f"Failed to start Prometheus server: {e}")

    # =========================================================================
    # EVENT EMISSION METHODS
    # =========================================================================
    
    def emit_decision(
        self,
        decision_id: Optional[str] = None,
        signal_dir: str = 'NONE',
        signal_strength: str = 'NONE',
        S_long: float = 0.0,
        S_short: float = 0.0,
        votes: Optional[Dict] = None,
        tie_break_used: bool = False,
        cluster: Optional[Dict] = None,
        context: Optional[Dict] = None,
        costs: Optional[Dict] = None,
        market_regime: str = 'unknown',
        entry_px: Optional[float] = None,
        stop_px: Optional[float] = None,
        tp_px: Optional[float] = None,
        qty: Optional[float] = None,
        action: str = 'NO_TRADE',
        no_trade_reason: Optional[str] = None,
        latency_ms: float = 0.0,
        **kwargs
    ):
        """Emit a decision event."""
        decision_id = decision_id or f"dec_{uuid.uuid4().hex[:8]}"
        
        event = self._base_event()
        event.update({
            'event': 'decision',
            'decision_id': decision_id,
            'signal_dir': signal_dir,
            'signal_strength': signal_strength,
            'S_long': S_long,
            'S_short': S_short,
            'votes': votes or {'m1': 'NONE', 'm2': 'NONE', 'm3': 'NONE'},
            'tie_break_used': tie_break_used,
            'cluster': cluster or {},
            'context': context or {},
            'costs': costs or {},
            'market_regime': market_regime,
            'entry_px': entry_px,
            'stop_px': stop_px,
            'tp_px': tp_px,
            'qty': qty,
            'action': action,
            'no_trade_reason': no_trade_reason,
            'latency_ms': latency_ms
        })
        event.update(kwargs)  # Allow extra fields

        # If a bias is provided in context, ensure we surface it and align signal_dir
        ctx = event.get('context', {}) or {}
        if 'bias' in ctx and ctx.get('bias'):
            event['bias'] = ctx.get('bias')
            # If signal_dir is NONE, use bias to indicate directional bias in this decision
            if event.get('signal_dir') in (None, 'NONE'):
                event['signal_dir'] = ctx.get('bias')
        
        # Write to JSONL
        self._get_writer('decision').write(event)
        
        # Write to CSV
        try:
            self.csv.insert_decision(event)
        except Exception as e:
            logger.error(f"CSV decision write failed: {e}")
        
        # Update metrics
        if self.prom:
            try:
                self.prom['decision_total'].labels(action=action).inc()
                if action == 'NO_TRADE' and no_trade_reason:
                    self.prom['decision_no_trade_total'].labels(reason=no_trade_reason).inc()
                if latency_ms > 0:
                    self.prom['decision_latency_ms'].observe(latency_ms)
            except Exception:
                pass
        
        # Update session stats
        self._session_stats['decisions'] += 1
        
        return decision_id

    def emit_guard(self, kind: str, details: Optional[Dict] = None):
        """Emit a guard event."""
        event = self._base_event()
        event.update({
            'event': 'guard',
            'kind': kind,
            'details': details or {}
        })
        
        self._get_writer('guard').write(event)
        
        try:
            self.csv.insert_guard(event)
        except Exception as e:
            logger.error(f"CSV guard write failed: {e}")
        
        if self.prom:
            try:
                self.prom['guard_total'].labels(kind=kind).inc()
            except Exception:
                pass

    def emit_veto(self, reason: str, fields: Optional[Dict] = None):
        """Emit a veto event."""
        event = self._base_event()
        event.update({
            'event': 'veto.context',
            'reason': reason,
            'fields': fields or {}
        })
        
        self._get_writer('veto').write(event)
        
        try:
            self.csv.insert_veto(event)
        except Exception as e:
            logger.error(f"CSV veto write failed: {e}")
        
        if self.prom:
            try:
                self.prom['veto_total'].labels(reason=reason).inc()
            except Exception:
                pass

    def emit_order(
        self,
        order_id: str,
        decision_id: str,
        side: str,
        order_type: str = 'MARKET',
        px: float = 0.0,
        qty: float = 0.0,
        status: str = 'NEW',
        latency_ms: float = 0.0,
        reduce_only: bool = False,
        time_in_force: str = 'GTC'
    ):
        """Emit an order event."""
        event = self._base_event()
        event.update({
            'event': 'order',
            'order_id': order_id,
            'decision_id': decision_id,
            'side': side,
            'type': order_type,
            'px': px,
            'qty': qty,
            'status': status,
            'latency_ms': latency_ms,
            'reduce_only': reduce_only,
            'time_in_force': time_in_force
        })
        
        self._get_writer('order').write(event)
        
        try:
            self.csv.insert_order(event)
        except Exception as e:
            logger.error(f"CSV order write failed: {e}")
        
        if self.prom:
            try:
                if status == 'NEW':
                    self.prom['order_placed_total'].inc()
                    if latency_ms > 0:
                        self.prom['order_place_latency_ms'].observe(latency_ms)
                elif status == 'REJECTED':
                    self.prom['order_failed_total'].inc()
            except Exception:
                pass

    def emit_fill(
        self,
        fill_id: Optional[str] = None,
        order_id: str = '',
        side: Optional[str] = None,
        px: float = 0.0,
        qty: float = 0.0,
        fee: float = 0.0,
        pnl_open: float = 0.0,
        pnl_close: float = 0.0,
        decision_id: Optional[str] = None,
        expected_px: Optional[float] = None,
        slippage_bps: Optional[float] = None,
        exit_type: Optional[str] = None,
        r_multiple: Optional[float] = None,
        hold_duration_s: Optional[float] = None
    ):
        """Emit a fill event."""
        fill_id = fill_id or f"fill_{uuid.uuid4().hex[:8]}"
        
        # Calculate slippage if not provided but expected_px is available
        if slippage_bps is None and expected_px is not None and expected_px > 0:
            slippage_bps = ((px - expected_px) / expected_px) * 10000
        
        event = self._base_event()
        event.update({
            'event': 'fill',
            'fill_id': fill_id,
            'order_id': order_id,
            'decision_id': decision_id,
            'side': side,
            'px': px,
            'qty': qty,
            'fee': fee,
            'pnl_open': pnl_open,
            'pnl_close': pnl_close,
            'expected_px': expected_px,
            'slippage_bps': slippage_bps,
            'exit_type': exit_type,
            'r_multiple': r_multiple,
            'hold_duration_s': hold_duration_s
        })
        
        self._get_writer('fill').write(event)
        
        try:
            self.csv.insert_fill(event)
        except Exception as e:
            logger.error(f"CSV fill write failed: {e}")
        
        if self.prom:
            try:
                self.prom['fill_total'].inc()
            except Exception:
                pass
        
        # Update session stats
        if pnl_close != 0:
            self._session_stats['trades'] += 1
            self._session_stats['total_pnl'] += pnl_close
            self._session_stats['total_fees'] += fee
            if pnl_close > 0:
                self._session_stats['wins'] += 1
            else:
                self._session_stats['losses'] += 1

    def emit_health(
        self,
        price_age_s: Optional[float] = None,
        heatmap_age_s: Optional[float] = None,
        oi_age_s: Optional[float] = None,
        funding_age_s: Optional[float] = None,
        lsr_age_s: Optional[float] = None,
        ws_connected: bool = False,
        ws_reconnect_count: int = 0,
        coinglass_ok: bool = True,
        positions_open: int = 0,
        risk_used_pct: float = 0.0,
        daily_cap_hit: bool = False,
        equity_usd: float = 0.0,
        pnl_realized_usd: float = 0.0,
        kill_switch_active: bool = False,
        kill_switch_reason: Optional[str] = None,
        **kwargs
    ):
        """Emit a health heartbeat event."""
        event = self._base_event()
        event.update({
            'event': 'health.heartbeat',
            'price_age_s': price_age_s,
            'heatmap_age_s': heatmap_age_s,
            'oi_age_s': oi_age_s,
            'funding_age_s': funding_age_s,
            'lsr_age_s': lsr_age_s,
            'ws_connected': ws_connected,
            'ws_reconnect_count': ws_reconnect_count,
            'coinglass_ok': coinglass_ok,
            'positions_open': positions_open,
            'risk_used_pct': risk_used_pct,
            'daily_cap_hit': daily_cap_hit,
            'equity_usd': equity_usd,
            'pnl_realized_usd': pnl_realized_usd,
            'kill_switch_active': kill_switch_active,
            'kill_switch_reason': kill_switch_reason
        })
        event.update(kwargs)
        
        self._get_writer('health').write(event)
        
        try:
            self.csv.insert_health(event)
        except Exception as e:
            logger.error(f"CSV health write failed: {e}")
        
        # Update Prometheus gauges
        if self.prom:
            try:
                if price_age_s is not None:
                    self.prom['feed_price_age_seconds'].set(price_age_s)
                if heatmap_age_s is not None:
                    self.prom['feed_heatmap_age_seconds'].set(heatmap_age_s)
                if oi_age_s is not None:
                    self.prom['feed_oi_age_seconds'].set(oi_age_s)
                if funding_age_s is not None:
                    self.prom['feed_funding_age_seconds'].set(funding_age_s)
                if lsr_age_s is not None:
                    self.prom['feed_lsr_age_seconds'].set(lsr_age_s)
                self.prom['positions_open'].set(positions_open)
                self.prom['risk_used_pct'].set(risk_used_pct)
                self.prom['equity_usd'].set(equity_usd)
                self.prom['pnl_realized_usd'].set(pnl_realized_usd)
                self.prom['kill_switch_active'].set(1 if kill_switch_active else 0)
                if daily_cap_hit:
                    self.prom['risk_daily_cap_hits_total'].inc()
            except Exception:
                pass

    def emit_error(
        self,
        component: str,
        message: str,
        severity: str = 'ERROR',
        exc: Optional[Exception] = None,
        decision_id: Optional[str] = None,
        order_id: Optional[str] = None
    ):
        """Emit an error event."""
        exc_type = None
        exc_msg = None
        stack = None
        
        if exc:
            exc_type = type(exc).__name__
            exc_msg = str(exc)
            stack = traceback.format_exc()
        
        event = self._base_event()
        event.update({
            'event': 'error',
            'severity': severity,
            'component': component,
            'message': message,
            'exc_type': exc_type,
            'exc_msg': exc_msg,
            'stack': stack,
            'decision_id': decision_id,
            'order_id': order_id
        })
        
        self._get_writer('error').write(event)
        
        try:
            self.csv.insert_order(event)
        except Exception as e:
            logger.error(f"CSV order write failed: {e}")
        
        if self.prom:
            try:
                self.prom['order_total'].labels(side=side, status=status).inc()
            except Exception:
                pass

    def emit_session_summary(self):
        """Emit end-of-session summary."""
        stats = self._session_stats
        trades = stats['trades']
        
        win_rate = stats['wins'] / trades if trades > 0 else 0.0
        net_pnl = stats['total_pnl'] - stats['total_fees']
        
        event = self._base_event()
        event.update({
            'event': 'session.summary',
            'total_decisions': stats['decisions'],
            'total_trades': trades,
            'wins': stats['wins'],
            'losses': stats['losses'],
            'win_rate': win_rate,
            'total_pnl_usd': stats['total_pnl'],
            'total_fees_usd': stats['total_fees'],
            'net_pnl_usd': net_pnl,
            'session_start_ts': stats['session_start'],
            'session_end_ts': datetime.now(timezone.utc).isoformat()
        })
        
        self._get_writer('session').write(event)
        logger.info(f"Session summary emitted: {trades} trades, {win_rate:.1%} win rate, ${net_pnl:.2f} net PnL")

    # =========================================================================
    # LEGACY COMPATIBILITY
    # =========================================================================
    
    def emit_event(self, event_type: str, payload: Dict, full: bool = False):
        """Legacy event emission for backward compatibility."""
        event = self._base_event()
        event.update(payload)
        self._get_writer(event_type).write(event)

    def emit(self, event_type: str, payload: Dict):
        """Alias for emit_event."""
        self.emit_event(event_type, payload)

    def incr(self, metric: str, amount: int = 1):
        """Increment a Prometheus counter."""
        if self.prom and metric in self.prom:
            try:
                self.prom[metric].inc(amount)
            except Exception:
                pass

    def set_gauge(self, metric: str, value: float):
        """Set a Prometheus gauge."""
        if self.prom and metric in self.prom:
            try:
                self.prom[metric].set(value)
            except Exception:
                pass

    def observe(self, metric: str, value: float):
        """Observe a Prometheus histogram value."""
        if self.prom and metric in self.prom:
            try:
                self.prom[metric].observe(value)
            except Exception:
                pass

    # =========================================================================
    # TRACING
    # =========================================================================
    
    @contextmanager
    def start_span(self, name: str, attrs: Optional[Dict] = None):
        """Start an OpenTelemetry span."""
        if OTEL_AVAILABLE:
            with tracer.start_as_current_span(name, attributes=attrs or {}) as span:
                yield span
        else:
            yield None

    # =========================================================================
    # LIFECYCLE
    # =========================================================================
    
    def flush(self):
        """Flush all writers."""
        for writer in self.writers.values():
            try:
                writer._fh.flush()
            except Exception:
                pass

    def close(self):
        """Close all resources and emit session summary."""
        try:
            self.emit_session_summary()
        except Exception as e:
            logger.error(f"Failed to emit session summary: {e}")
        
        for writer in self.writers.values():
            try:
                writer.close()
            except Exception:
                pass
        
        try:
            self.csv.close()
        except Exception:
            pass
        
        logger.info("Emitters closed")


# ============================================================================
# FACTORY FUNCTION
# ============================================================================

_emitters_instance: Optional[Emitters] = None

def get_emitters(**kwargs) -> Emitters:
    """Get or create the global Emitters singleton."""
    global _emitters_instance
    if _emitters_instance is None:
        run_id = kwargs.get('run_id', os.getenv('RUN_ID', f'r_{uuid.uuid4().hex[:8]}'))
        session_id = kwargs.get('session_id', os.getenv('SESSION_ID', f's_{uuid.uuid4().hex[:8]}'))
        _emitters_instance = Emitters(run_id=run_id, session_id=session_id, **kwargs)
    return _emitters_instance
