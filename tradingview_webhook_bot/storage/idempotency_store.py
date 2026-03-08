import sqlite3
import os

class IdempotencyStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS processed_signals (
                    signal_id TEXT PRIMARY KEY, 
                    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def is_seen(self, signal_id: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT 1 FROM processed_signals WHERE signal_id = ?", (signal_id,))
            return cursor.fetchone() is not None

    def mark_seen(self, signal_id: str):
        with sqlite3.connect(self.db_path) as conn:
            try:
                conn.execute("INSERT OR IGNORE INTO processed_signals (signal_id) VALUES (?)", (signal_id,))
                conn.commit()
            except Exception as e:
                print(f"Error marking signal as seen: {e}")
