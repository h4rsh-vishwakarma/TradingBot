import sqlite3
import os
import logging

logger = logging.getLogger(__name__)

class IdempotencyStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initializes the database and ensures the correct table schema exists."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            # Verified Table Name: processed_signals
            conn.execute("""
                CREATE TABLE IF NOT EXISTS processed_signals (
                    signal_id TEXT PRIMARY KEY,
                    client_order_id TEXT,
                    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def get_order_mapping(self, signal_id: str):
        """Returns client_order_id if the signal was previously processed."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "SELECT client_order_id FROM processed_signals WHERE signal_id = ?", 
                    (signal_id,)
                )
                row = cursor.fetchone()
                return row[0] if row else None
        except sqlite3.Error as e:
            logger.error(f"❌ Database Read Error (get_mapping): {e}")
            return None

    def is_seen(self, signal_id: str) -> bool:
        """Quick check to see if a signal has already been touched."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "SELECT 1 FROM processed_signals WHERE signal_id = ?",
                    (signal_id,)
                )
                return cursor.fetchone() is not None
        except sqlite3.Error as e:
            logger.error(f"Database Read Error (is_seen): {e}")
            return False

    def mark_seen(self, signal_id: str, client_order_id: str = None):
        """
        Persists the mapping. Uses REPLACE to update existing signal_id 
        if client_order_id is provided later.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO processed_signals (signal_id, client_order_id) VALUES (?, ?)",
                    (signal_id, client_order_id)
                )
                conn.commit()
                logger.info(f"💾 Idempotency Saved: {signal_id} -> {client_order_id}")
        except sqlite3.Error as e:
            logger.error(f"❌ Database Write Error (mark_seen): {e}")

    def get_recent_signals(self, limit: int = 10):
        """Helper for debugging/admin tools to see recent activity."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT signal_id, client_order_id, processed_at FROM processed_signals ORDER BY processed_at DESC LIMIT ?",
                (limit,)
            )
            return cursor.fetchall()
