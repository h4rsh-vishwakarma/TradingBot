"""
Durable SQLite Signal Queue — replaces fragile JSONL+offset system.
Crash-safe, supports retries, atomic operations, no external dependencies.
"""
import sqlite3
import json
import time
import os
import logging
from typing import Callable, Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class DurableSignalQueue:
    """SQLite-backed signal queue with retry support and crash recovery."""

    def __init__(self, db_path: str, max_retries: int = 3):
        self.db_path = db_path
        self.max_retries = max_retries
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_id TEXT,
                    payload TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    retries INTEGER DEFAULT 0,
                    created_at REAL,
                    processed_at REAL,
                    error TEXT
                )
            """)
            conn.execute("PRAGMA journal_mode=WAL")  # Write-Ahead Logging: concurrent reads + crash safety
            conn.execute("PRAGMA synchronous=NORMAL")  # Faster writes, still crash-safe with WAL
            conn.execute("PRAGMA cache_size=-8000")  # 8MB cache for faster reads
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON signals(status)")
            # Reset any stuck 'processing' signals from a crash
            stuck = conn.execute(
                "UPDATE signals SET status='pending' WHERE status='processing'"
            ).rowcount
            if stuck:
                logger.info(f"🔄 Recovered {stuck} stuck signals from previous crash")
            conn.commit()

    def enqueue(self, data: dict) -> bool:
        """Add signal to queue. Returns True on success."""
        try:
            signal_id = data.get("signal_id", "")
            payload = json.dumps(data)
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO signals (signal_id, payload, status, created_at) VALUES (?, ?, 'pending', ?)",
                    (signal_id, payload, time.time())
                )
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"❌ Queue enqueue failed: {e}")
            return False

    def poll(self, handler: Callable[[Dict[str, Any]], bool], batch_size: int = 1) -> Dict[str, int]:
        """
        Process pending signals. Handler returns True=success, False=retry later.
        Compatible with existing orchestrator poll interface.
        """
        stats = {'processed': 0, 'failed': 0, 'dlq': 0}

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT id, signal_id, payload, retries FROM signals "
                    "WHERE status='pending' ORDER BY id LIMIT ?",
                    (batch_size,)
                ).fetchall()

                for row in rows:
                    row_id = row['id']
                    retries = row['retries']

                    # Mark as processing
                    conn.execute("UPDATE signals SET status='processing' WHERE id=?", (row_id,))
                    conn.commit()

                    try:
                        data = json.loads(row['payload'])
                        success = handler(data)

                        if success:
                            conn.execute(
                                "UPDATE signals SET status='completed', processed_at=? WHERE id=?",
                                (time.time(), row_id)
                            )
                            stats['processed'] += 1
                        else:
                            # Retry or move to DLQ
                            if retries + 1 >= self.max_retries:
                                conn.execute(
                                    "UPDATE signals SET status='dlq', error='Max retries exceeded', retries=? WHERE id=?",
                                    (retries + 1, row_id)
                                )
                                logger.warning(f"📛 Signal {row['signal_id']} moved to DLQ after {retries+1} retries")
                                stats['dlq'] += 1
                            else:
                                conn.execute(
                                    "UPDATE signals SET status='pending', retries=? WHERE id=?",
                                    (retries + 1, row_id)
                                )
                                logger.info(f"🔁 Signal {row['signal_id']} retry {retries+1}/{self.max_retries}")
                                stats['failed'] += 1
                                break  # Stop batch on failure

                        conn.commit()

                    except json.JSONDecodeError as e:
                        conn.execute(
                            "UPDATE signals SET status='dlq', error=? WHERE id=?",
                            (f"JSON decode error: {e}", row_id)
                        )
                        conn.commit()
                        stats['dlq'] += 1

                    except Exception as e:
                        conn.execute(
                            "UPDATE signals SET status='pending', retries=?, error=? WHERE id=?",
                            (retries + 1, str(e), row_id)
                        )
                        conn.commit()
                        stats['failed'] += 1
                        break

        except Exception as e:
            logger.error(f"❌ Queue poll error: {e}")

        return stats

    def get_stats(self) -> Dict[str, int]:
        """Get queue statistics."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                result = {}
                for status in ['pending', 'processing', 'completed', 'dlq']:
                    count = conn.execute(
                        "SELECT COUNT(*) FROM signals WHERE status=?", (status,)
                    ).fetchone()[0]
                    result[status] = count
                return result
        except Exception:
            return {}

    def cleanup(self, max_age_hours: int = 24):
        """Remove completed signals older than max_age_hours."""
        try:
            cutoff = time.time() - (max_age_hours * 3600)
            with sqlite3.connect(self.db_path) as conn:
                deleted = conn.execute(
                    "DELETE FROM signals WHERE status='completed' AND processed_at < ?",
                    (cutoff,)
                ).rowcount
                conn.commit()
                if deleted:
                    logger.info(f"🧹 Cleaned {deleted} old completed signals")
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
