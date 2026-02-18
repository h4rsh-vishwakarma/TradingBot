"""PostgreSQL emitter for durable analytics storage.

Stores events as JSONB in PostgreSQL tables:
- decisions: Full decision events for fine-tuning
- orders: Order events
- fills: Fill events with PnL
- health: Health snapshots
- errors: Error events

Environment variables:
- POSTGRES_HOST: Database host (default: localhost)
- POSTGRES_PORT: Database port (default: 5432)
- POSTGRES_DB: Database name (default: liqbot)
- POSTGRES_USER: Database user
- POSTGRES_PASSWORD: Database password
- POSTGRES_ENABLED: Set to '1' to enable (default: '0')

Falls back to CSV emitter if Postgres is unavailable.

Usage:
    emitter = PostgresEmitter()
    emitter.insert_decision(decision_event.to_dict())
"""
import os
import logging
import json
import time
import threading
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from queue import Queue, Empty

logger = logging.getLogger(__name__)

# Try to import psycopg2
try:
    import psycopg2
    import psycopg2.extras
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False
    logger.info("psycopg2 not installed - PostgreSQL emitter will use CSV fallback")

from .sheets_emitter import CSVEmitter, get_csv_emitter


# SQL for table creation
CREATE_TABLES_SQL = """
-- Decisions table
CREATE TABLE IF NOT EXISTS decisions (
    id SERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    run_id VARCHAR(32),
    session_id VARCHAR(32),
    decision_id VARCHAR(32) UNIQUE,
    venue VARCHAR(32),
    symbol VARCHAR(16),
    env VARCHAR(16),
    mode VARCHAR(16),
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_decisions_ts ON decisions(ts);
CREATE INDEX IF NOT EXISTS idx_decisions_run_id ON decisions(run_id);
CREATE INDEX IF NOT EXISTS idx_decisions_decision_id ON decisions(decision_id);
CREATE INDEX IF NOT EXISTS idx_decisions_data_gin ON decisions USING GIN (data);

-- Orders table
CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    run_id VARCHAR(32),
    session_id VARCHAR(32),
    order_id VARCHAR(64),
    decision_id VARCHAR(32),
    venue VARCHAR(32),
    symbol VARCHAR(16),
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_orders_ts ON orders(ts);
CREATE INDEX IF NOT EXISTS idx_orders_order_id ON orders(order_id);
CREATE INDEX IF NOT EXISTS idx_orders_decision_id ON orders(decision_id);

-- Fills table
CREATE TABLE IF NOT EXISTS fills (
    id SERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    run_id VARCHAR(32),
    session_id VARCHAR(32),
    fill_id VARCHAR(64),
    order_id VARCHAR(64),
    venue VARCHAR(32),
    symbol VARCHAR(16),
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fills_ts ON fills(ts);
CREATE INDEX IF NOT EXISTS idx_fills_order_id ON fills(order_id);

-- Health table
CREATE TABLE IF NOT EXISTS health (
    id SERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    run_id VARCHAR(32),
    session_id VARCHAR(32),
    venue VARCHAR(32),
    symbol VARCHAR(16),
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_health_ts ON health(ts);
CREATE INDEX IF NOT EXISTS idx_health_run_id ON health(run_id);

-- Errors table
CREATE TABLE IF NOT EXISTS errors (
    id SERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    run_id VARCHAR(32),
    session_id VARCHAR(32),
    severity VARCHAR(16),
    component VARCHAR(64),
    message TEXT,
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_errors_ts ON errors(ts);
CREATE INDEX IF NOT EXISTS idx_errors_severity ON errors(severity);
CREATE INDEX IF NOT EXISTS idx_errors_component ON errors(component);

-- Guards table
CREATE TABLE IF NOT EXISTS guards (
    id SERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    run_id VARCHAR(32),
    session_id VARCHAR(32),
    kind VARCHAR(32),
    venue VARCHAR(32),
    symbol VARCHAR(16),
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_guards_ts ON guards(ts);
CREATE INDEX IF NOT EXISTS idx_guards_kind ON guards(kind);

-- Vetoes table
CREATE TABLE IF NOT EXISTS vetoes (
    id SERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    run_id VARCHAR(32),
    session_id VARCHAR(32),
    reason VARCHAR(64),
    venue VARCHAR(32),
    symbol VARCHAR(16),
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_vetoes_ts ON vetoes(ts);
CREATE INDEX IF NOT EXISTS idx_vetoes_reason ON vetoes(reason);
"""


class PostgresEmitter:
    """PostgreSQL emitter for durable event storage.
    
    Features:
    - Async batch inserts via background thread
    - Connection pooling
    - Automatic reconnection
    - Falls back to CSV if unavailable
    """
    
    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        database: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        batch_size: int = 100,
        flush_interval: float = 5.0
    ):
        # Configuration from environment
        self.host = host or os.getenv('POSTGRES_HOST', 'localhost')
        self.port = port or int(os.getenv('POSTGRES_PORT', '5432'))
        self.database = database or os.getenv('POSTGRES_DB', 'liqbot')
        self.user = user or os.getenv('POSTGRES_USER', 'liqbot')
        self.password = password or os.getenv('POSTGRES_PASSWORD', '')
        
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        
        # Check if explicitly enabled
        self.enabled = (
            PSYCOPG2_AVAILABLE and 
            os.getenv('POSTGRES_ENABLED', '0') == '1'
        )
        
        # Connection
        self._conn: Optional[Any] = None
        self._lock = threading.Lock()
        
        # Queues for async inserts
        self._queues: Dict[str, Queue] = {
            'decisions': Queue(),
            'orders': Queue(),
            'fills': Queue(),
            'health': Queue(),
            'errors': Queue(),
            'guards': Queue(),
            'vetoes': Queue(),
        }
        
        # Fallback CSV emitter
        self._csv = get_csv_emitter()
        
        # Background flush thread
        self._running = False
        self._flush_thread: Optional[threading.Thread] = None
        
        if self.enabled:
            try:
                self._connect()
                self._create_tables()
                self._start_flush_thread()
                logger.info(f"PostgreSQL emitter connected to {self.host}:{self.port}/{self.database}")
            except Exception as e:
                logger.error(f"Failed to connect to PostgreSQL: {e} - falling back to CSV")
                self.enabled = False
        else:
            logger.info("PostgreSQL emitter disabled - using CSV fallback")
    
    def _connect(self):
        """Establish database connection."""
        if not PSYCOPG2_AVAILABLE:
            raise RuntimeError("psycopg2 not available")
        
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except:
                    pass
            
            self._conn = psycopg2.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password
            )
            self._conn.autocommit = True
    
    def _create_tables(self):
        """Create database tables if they don't exist."""
        if not self._conn:
            return
        
        with self._lock:
            try:
                with self._conn.cursor() as cur:
                    cur.execute(CREATE_TABLES_SQL)
                logger.info("PostgreSQL tables created/verified")
            except Exception as e:
                logger.error(f"Failed to create tables: {e}")
    
    def _start_flush_thread(self):
        """Start background flush thread."""
        if self._running:
            return
        
        self._running = True
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()
    
    def _flush_loop(self):
        """Background loop to flush queues."""
        while self._running:
            try:
                time.sleep(self.flush_interval)
                self._flush_all()
            except Exception as e:
                logger.exception(f"Error in flush loop: {e}")
    
    def _flush_all(self):
        """Flush all queues to database."""
        for table_name, queue in self._queues.items():
            items = []
            while len(items) < self.batch_size:
                try:
                    item = queue.get_nowait()
                    items.append(item)
                except Empty:
                    break
            
            if items:
                self._batch_insert(table_name, items)
    
    def _batch_insert(self, table: str, items: List[Dict]):
        """Batch insert items into table."""
        if not self._conn or not items:
            return
        
        try:
            with self._lock:
                with self._conn.cursor() as cur:
                    # Build insert SQL based on table
                    if table == 'decisions':
                        sql = """
                            INSERT INTO decisions (ts, run_id, session_id, decision_id, venue, symbol, env, mode, data)
                            VALUES (%(ts)s, %(run_id)s, %(session_id)s, %(decision_id)s, %(venue)s, %(symbol)s, %(env)s, %(mode)s, %(data)s)
                            ON CONFLICT (decision_id) DO UPDATE SET data = EXCLUDED.data
                        """
                    elif table == 'orders':
                        sql = """
                            INSERT INTO orders (ts, run_id, session_id, order_id, decision_id, venue, symbol, data)
                            VALUES (%(ts)s, %(run_id)s, %(session_id)s, %(order_id)s, %(decision_id)s, %(venue)s, %(symbol)s, %(data)s)
                        """
                    elif table == 'fills':
                        sql = """
                            INSERT INTO fills (ts, run_id, session_id, fill_id, order_id, venue, symbol, data)
                            VALUES (%(ts)s, %(run_id)s, %(session_id)s, %(fill_id)s, %(order_id)s, %(venue)s, %(symbol)s, %(data)s)
                        """
                    elif table == 'health':
                        sql = """
                            INSERT INTO health (ts, run_id, session_id, venue, symbol, data)
                            VALUES (%(ts)s, %(run_id)s, %(session_id)s, %(venue)s, %(symbol)s, %(data)s)
                        """
                    elif table == 'errors':
                        sql = """
                            INSERT INTO errors (ts, run_id, session_id, severity, component, message, data)
                            VALUES (%(ts)s, %(run_id)s, %(session_id)s, %(severity)s, %(component)s, %(message)s, %(data)s)
                        """
                    elif table == 'guards':
                        sql = """
                            INSERT INTO guards (ts, run_id, session_id, kind, venue, symbol, data)
                            VALUES (%(ts)s, %(run_id)s, %(session_id)s, %(kind)s, %(venue)s, %(symbol)s, %(data)s)
                        """
                    elif table == 'vetoes':
                        sql = """
                            INSERT INTO vetoes (ts, run_id, session_id, reason, venue, symbol, data)
                            VALUES (%(ts)s, %(run_id)s, %(session_id)s, %(reason)s, %(venue)s, %(symbol)s, %(data)s)
                        """
                    else:
                        return
                    
                    # Execute batch
                    psycopg2.extras.execute_batch(cur, sql, items)
                    
        except Exception as e:
            logger.exception(f"Batch insert failed for {table}: {e}")
            # Attempt reconnection
            try:
                self._connect()
            except:
                pass
    
    def _prepare_record(self, payload: Dict, table: str) -> Dict:
        """Prepare a record for insertion."""
        ts = payload.get('ts', datetime.now(timezone.utc).isoformat())
        
        record = {
            'ts': ts,
            'run_id': payload.get('run_id', ''),
            'session_id': payload.get('session_id', ''),
            'venue': payload.get('venue', 'binanceusdm'),
            'symbol': payload.get('symbol', 'BTCUSDT'),
            'data': json.dumps(payload)
        }
        
        # Add table-specific fields
        if table == 'decisions':
            record['decision_id'] = payload.get('decision_id', '')
            record['env'] = payload.get('env', '')
            record['mode'] = payload.get('mode', '')
        elif table == 'orders':
            record['order_id'] = payload.get('order_id', '')
            record['decision_id'] = payload.get('decision_id', '')
        elif table == 'fills':
            record['fill_id'] = payload.get('fill_id', '')
            record['order_id'] = payload.get('order_id', '')
        elif table == 'errors':
            record['severity'] = payload.get('severity', 'ERROR')
            record['component'] = payload.get('component', '')
            record['message'] = payload.get('message', '')
        elif table == 'guards':
            record['kind'] = payload.get('kind', 'other')
        elif table == 'vetoes':
            record['reason'] = payload.get('reason', '')
        
        return record
    
    def insert_decision(self, payload: Dict):
        """Insert a decision event."""
        if self.enabled:
            record = self._prepare_record(payload, 'decisions')
            self._queues['decisions'].put(record)
        
        # Always write to CSV as backup
        try:
            self._csv.insert_decision(payload)
        except Exception:
            logger.exception('CSV decision insert failed')
    
    def insert_order(self, payload: Dict):
        """Insert an order event."""
        if self.enabled:
            record = self._prepare_record(payload, 'orders')
            self._queues['orders'].put(record)
        
        try:
            self._csv.insert_order(payload)
        except Exception:
            logger.exception('CSV order insert failed')
    
    def insert_fill(self, payload: Dict):
        """Insert a fill event."""
        if self.enabled:
            record = self._prepare_record(payload, 'fills')
            self._queues['fills'].put(record)
        
        try:
            self._csv.insert_fill(payload)
        except Exception:
            logger.exception('CSV fill insert failed')
    
    def insert_health(self, payload: Dict):
        """Insert a health snapshot."""
        if self.enabled:
            record = self._prepare_record(payload, 'health')
            self._queues['health'].put(record)
        
        try:
            self._csv.insert_health(payload)
        except Exception:
            logger.exception('CSV health insert failed')
    
    def insert_error(self, payload: Dict):
        """Insert an error event."""
        if self.enabled:
            record = self._prepare_record(payload, 'errors')
            self._queues['errors'].put(record)
        
        try:
            self._csv.insert_error(payload)
        except Exception:
            logger.exception('CSV error insert failed')
    
    def insert_guard(self, payload: Dict):
        """Insert a guard event."""
        if self.enabled:
            record = self._prepare_record(payload, 'guards')
            self._queues['guards'].put(record)
        
        try:
            self._csv.insert_guard(payload)
        except Exception:
            logger.exception('CSV guard insert failed')
    
    def insert_veto(self, payload: Dict):
        """Insert a veto event."""
        if self.enabled:
            record = self._prepare_record(payload, 'vetoes')
            self._queues['vetoes'].put(record)
        
        try:
            self._csv.insert_veto(payload)
        except Exception:
            logger.exception('CSV veto insert failed')
    
    def flush(self):
        """Force flush all queues."""
        self._flush_all()
    
    def close(self):
        """Close the emitter and flush remaining events."""
        self._running = False
        self._flush_all()
        
        if self._conn:
            try:
                self._conn.close()
            except:
                pass


# Global singleton
_postgres_emitter: Optional[PostgresEmitter] = None


def get_postgres_emitter() -> PostgresEmitter:
    """Get or create the global PostgreSQL emitter singleton."""
    global _postgres_emitter
    if _postgres_emitter is None:
        _postgres_emitter = PostgresEmitter()
    return _postgres_emitter

