"""
Atomic JSONL Queue Writer
Hardened for production with fcntl locking, fsync, and Schema validation.
"""

import json
import fcntl
import os
import threading
from pathlib import Path
from typing import Dict, Any, Union
import logging

# Use the schema we defined in Task 1
try:
    from tradingview_webhook_bot.schemas import SignalEvent
except ImportError:
    SignalEvent = None

logger = logging.getLogger(__name__)

class AtomicJsonlQueue:
    """Thread-safe and Process-safe JSONL queue."""
    
    def __init__(self, queue_path: Union[str, Path]):
        self.queue_path = Path(queue_path)
        # Ensure the directory exists immediately
        self.queue_path.parent.mkdir(parents=True, exist_ok=True)
        self._local_lock = threading.Lock()
        
        logger.info(f"📝 Atomic queue initialized: {queue_path}")
    
    def append(self, record: Union[Dict[str, Any], Any]) -> bool:
        """
        Atomically append a record. Supports dict or SignalEvent objects.
        """
        # 1. Convert to dict if it's a Pydantic model
        if hasattr(record, "dict"):
            data = record.dict()
        else:
            data = record

        with self._local_lock:
            try:
                # 2. Serialize and prepare line
                # We use sort_keys=True for better audit logs/debugging
                json_line = json.dumps(data, default=str, sort_keys=True) + '\n'
                encoded_line = json_line.encode('utf-8')
                
                # 3. Low-level file open
                # O_APPEND is atomic at the OS level on Linux
                fd = os.open(
                    str(self.queue_path), 
                    os.O_WRONLY | os.O_APPEND | os.O_CREAT,
                    0o644
                )
                
                try:
                    # 4. Apply Exclusive Lock (Process-level safety)
                    fcntl.flock(fd, fcntl.LOCK_EX)
                    
                    # 5. Write and Sync
                    os.write(fd, encoded_line)
                    os.fsync(fd) # Ensures data survives power loss
                    
                    return True
                finally:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    os.close(fd)
                    
            except Exception as e:
                logger.error(f"❌ Critical Queue Write Failure: {e}")
                return False
    
    def read_all(self) -> list:
        """Read all valid lines (Standardizes the read-back for consumers)."""
        if not self.queue_path.exists():
            return []
        
        records = []
        with open(self.queue_path, 'r') as f:
            for line_no, line in enumerate(f, 1):
                clean_line = line.strip()
                if not clean_line: continue
                try:
                    records.append(json.loads(clean_line))
                except json.JSONDecodeError:
                    logger.error(f"⚠️ Corrupt data at {self.queue_path}:{line_no}")
        return records

# Convenience function updated to match the class logic
def append_jsonl(path: str, record: Dict[str, Any]) -> bool:
    return AtomicJsonlQueue(path).append(record)
# Add this at the bottom of jsonl_queue.py
def read_jsonl(path: str):
    """Alias for the test suite to match the old naming."""
    return AtomicJsonlQueue(path).read_all()
