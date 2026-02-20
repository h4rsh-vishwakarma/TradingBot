import sqlite3
import os

DB_PATH = "storage/idempotency.db"

def init_db():
    """Initializes the SQLite database for tracking processed signals."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    # Create a table to store processed signal IDs
    conn.execute("CREATE TABLE IF NOT EXISTS processed_signals (signal_id TEXT PRIMARY KEY)")
    conn.commit()
    conn.close()

def is_seen(signal_id):
    """Returns True if the signal_id has already been processed."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM processed_signals WHERE signal_id = ?", (signal_id,))
    result = cur.fetchone()
    conn.close()
    return result is not None

def mark_as_seen(signal_id):
    """Saves the signal_id to the database."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO processed_signals (signal_id) VALUES (?)", (signal_id,))
    conn.commit()
    conn.close()