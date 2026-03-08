import sqlite3
import os

class IdempotencyStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            # signal_id: TradingView unique ID
            # client_order_id: Unique ID sent to Binance API
            conn.execute("""
                CREATE TABLE IF NOT EXISTS processed_signals (
                    signal_id TEXT PRIMARY KEY, 
                    client_order_id TEXT,
                    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def get_order_mapping(self, signal_id: str):
        """Returns client_order_id if the signal was previously processed."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT client_order_id FROM processed_signals WHERE signal_id = ?", (signal_id,))
            row = cursor.fetchone()
            return row[0] if row else None

    def is_seen(self, signal_id: str) -> bool:
        """Helper to quickly check if signal_id exists."""
        return self.get_order_mapping(signal_id) is not None

    def mark_seen(self, signal_id: str, client_order_id: str = None):
        """Persists the mapping after a successful or attempted trade."""
        with sqlite3.connect(self.db_path) as conn:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO processed_signals (signal_id, client_order_id) VALUES (?, ?)",
                    (signal_id, client_order_id)
                )
                conn.commit()
            except Exception as e:
                print(f"Error marking signal as seen: {e}")
