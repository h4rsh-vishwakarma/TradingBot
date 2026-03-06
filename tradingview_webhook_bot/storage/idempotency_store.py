"""
SQLite-based Idempotency Store
Ensures that duplicate signals are not processed, even across bot restarts.
Features: TTL support, automatic cleanup, and thread-safety.
"""

import sqlite3
import threading
import time
import logging
from pathlib import Path
from typing import Optional, Union, List, Dict, Any

logger = logging.getLogger(__name__)

class IdempotencyStore:
    """Thread-safe SQLite-based idempotency checker."""
    
    def __init__(self, db_path: Union[str, Path]):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()
    
    def _init_db(self):
        """Create database table and index if they don't exist."""
        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS processed_signals (
                        signal_id TEXT PRIMARY KEY,
                        processed_at REAL NOT NULL,
                        strategy TEXT,
                        side TEXT,
                        symbol TEXT,
                        details TEXT
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_processed_at 
                    ON processed_signals(processed_at)
                """)
                conn.commit()
    
    def seen(self, signal_id: str, strategy: Optional[str] = None, side: Optional[str] = None,
             symbol: Optional[str] = None, details: Optional[str] = None,
             ttl: Optional[int] = None) -> bool:
        """
        Check if signal was already processed. If not, record it atomically.
        
        Returns:
            True if signal was already seen (duplicate).
            False if this is a new signal (now recorded).
        """
        with self._lock:
            try:
                with sqlite3.connect(str(self.db_path)) as conn:
                    # 1. Check existing record
                    cursor = conn.execute(
                        "SELECT processed_at FROM processed_signals WHERE signal_id = ?",
                        (signal_id,)
                    )
                    row = cursor.fetchone()
                    
                    if row:
                        # Handle TTL: If record is older than TTL, delete and allow re-processing
                        if ttl is not None:
                            age = time.time() - float(row[0])
                            if age > ttl:
                                conn.execute("DELETE FROM processed_signals WHERE signal_id = ?", (signal_id,))
                            else:
                                logger.warning(f"🔄 Duplicate signal detected: {signal_id} (Age: {age:.1f}s)")
                                return True
                        else:
                            logger.warning(f"🔄 Duplicate signal detected: {signal_id}")
                            return True
                    
                    # 2. Record the new signal
                    conn.execute("""
                        INSERT INTO processed_signals 
                        (signal_id, processed_at, strategy, side, symbol, details)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (signal_id, time.time(), strategy, side, symbol, details))
                    conn.commit()
                    return False
                    
            except Exception as e:
                logger.error(f"❌ Idempotency check failed for {signal_id}: {e}")
                # Safety first: if DB fails, assume seen to prevent accidental double-trading
                return True

    def get_processed_count(self, since_timestamp: Optional[float] = None) -> int:
        """Returns count of processed signals for auditing."""
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                if since_timestamp:
                    cursor = conn.execute(
                        "SELECT COUNT(*) FROM processed_signals WHERE processed_at >= ?",
                        (since_timestamp,)
                    )
                else:
                    cursor = conn.execute("SELECT COUNT(*) FROM processed_signals")
                return cursor.fetchone()[0]
        except Exception as e:
            logger.error(f"Failed to get processed count: {e}")
            return 0

    def cleanup_old_records(self, older_than_days: int = 30):
        """Remove old records to prevent DB bloat."""
        cutoff_time = time.time() - (older_than_days * 24 * 3600)
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.execute("DELETE FROM processed_signals WHERE processed_at < ?", (cutoff_time,))
                deleted = cursor.rowcount
                conn.commit()
                if deleted > 0:
                    logger.info(f"🧹 Cleaned up {deleted} old idempotency records")
        except Exception as e:
            logger.error(f"Failed to cleanup records: {e}")

    def get_recent_signals(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent history for debugging/UI."""
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT * FROM processed_signals ORDER BY processed_at DESC LIMIT ?
                """, (limit,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get recent signals: {e}")
            return []
