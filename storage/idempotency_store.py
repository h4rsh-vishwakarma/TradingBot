"""
SQLite-based idempotency store to prevent duplicate signal processing.
Ensures that even after bot restart, previously processed signals are not re-executed.
"""

import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class IdempotencyStore:
    """Thread-safe SQLite-based idempotency checker."""
    
    def __init__(self, db_path: str):
        """
        Initialize idempotency store.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()
    
    def _init_db(self):
        """Create database table if it doesn't exist."""
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
        
        Args:
            signal_id: Unique signal identifier
            strategy: Strategy name (optional, for logging)
            side: Signal side (optional, for logging)
            symbol: Trading symbol (optional, for logging)
            details: Additional details (optional, for logging)
        
        Returns:
            True if signal was already seen (duplicate)
            False if this is the first time (and it's now recorded)
        """
        with self._lock:
            try:
                with sqlite3.connect(str(self.db_path)) as conn:
                    # Check if exists
                    cursor = conn.execute(
                        "SELECT signal_id, processed_at FROM processed_signals WHERE signal_id = ?",
                        (signal_id,)
                    )
                    row = cursor.fetchone()
                    if row:
                        # TTL-aware duplicate handling: if old enough, allow re-processing
                        if ttl is not None:
                            processed_at = float(row[1]) if len(row) > 1 else 0.0
                            age = time.time() - processed_at
                            if age > ttl:
                                conn.execute(
                                    "DELETE FROM processed_signals WHERE signal_id = ?",
                                    (signal_id,)
                                )
                                conn.commit()
                            else:
                                logger.warning(f"🔄 Duplicate signal detected: {signal_id}")
                                return True
                        else:
                            logger.warning(f"🔄 Duplicate signal detected: {signal_id}")
                            return True
                    
                    # Record it
                    conn.execute("""
                        INSERT INTO processed_signals 
                        (signal_id, processed_at, strategy, side, symbol, details)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (signal_id, time.time(), strategy, side, symbol, details))
                    conn.commit()
                    
                    logger.debug(f"✅ Signal recorded: {signal_id}")
                    return False
                    
            except Exception as e:
                logger.error(f"❌ Idempotency check failed for {signal_id}: {e}")
                # Fail safe: assume not seen to avoid blocking legitimate signals
                return False
    
    def get_processed_count(self, since_timestamp: Optional[float] = None) -> int:
        """
        Get count of processed signals.
        
        Args:
            since_timestamp: Only count signals processed after this timestamp
        
        Returns:
            Number of processed signals
        """
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
        """
        Remove old processed signal records to prevent database bloat.
        
        Args:
            older_than_days: Remove records older than this many days
        """
        cutoff_time = time.time() - (older_than_days * 24 * 3600)
        
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.execute(
                    "DELETE FROM processed_signals WHERE processed_at < ?",
                    (cutoff_time,)
                )
                deleted = cursor.rowcount
                conn.commit()
                
                if deleted > 0:
                    logger.info(f"🧹 Cleaned up {deleted} old idempotency records")
                    
        except Exception as e:
            logger.error(f"Failed to cleanup old records: {e}")
    
    def get_recent_signals(self, limit: int = 100) -> list:
        """
        Get recent processed signals for debugging.
        
        Args:
            limit: Maximum number of signals to return
        
        Returns:
            List of dicts with signal info
        """
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT signal_id, processed_at, strategy, side, symbol
                    FROM processed_signals
                    ORDER BY processed_at DESC
                    LIMIT ?
                """, (limit,))
                
                return [dict(row) for row in cursor.fetchall()]
                
        except Exception as e:
            logger.error(f"Failed to get recent signals: {e}")
            return []


# Convenience function for testing
def test_idempotency_store():
    """Test the idempotency store."""
    import tempfile
    import os
    
    # Create temp db
    with tempfile.NamedTemporaryFile(delete=False, suffix='.db') as f:
        db_path = f.name
    
    try:
        store = IdempotencyStore(db_path)
        
        # Test 1: First signal should not be seen
        assert not store.seen("TEST-001", "smc_luxalgo", "BUY", "BTCUSDT"), "First signal should be new"
        
        # Test 2: Same signal should be seen
        assert store.seen("TEST-001"), "Duplicate signal should be detected"
        
        # Test 3: Different signal should not be seen
        assert not store.seen("TEST-002", "smc_luxalgo", "SELL", "BTCUSDT"), "Different signal should be new"
        
        # Test 4: Count should be 2
        assert store.get_processed_count() == 2, "Should have 2 processed signals"
        
        # Test 5: Recent signals
        recent = store.get_recent_signals(limit=10)
        assert len(recent) == 2, "Should have 2 recent signals"
        
        print("✅ All idempotency store tests passed!")
        
    finally:
        # Cleanup
        if os.path.exists(db_path):
            os.unlink(db_path)


if __name__ == "__main__":
    # Run tests
    logging.basicConfig(level=logging.DEBUG)
    test_idempotency_store()
