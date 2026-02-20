import json
import os
import portalocker  # Use portalocker instead of fcntl
import logging

logger = logging.getLogger(__name__)

def append_jsonl(path: str, record: dict):
    """
    Appends a single record to a JSONL file atomically using cross-platform locking.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    
    # portalocker.Lock handles the 'with' block and locking automatically
    with portalocker.Lock(path, mode='a', timeout=10) as f:
        try:
            line = json.dumps(record) + '\n'
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
        except Exception as e:
            logger.error(f"Failed to append to {path}: {e}")
            raise

def read_jsonl(path: str):
    """Reads JSONL file safely."""
    if not os.path.exists(path):
        return []
        
    records = []
    # Use 'r' mode with a shared lock
    with portalocker.Lock(path, mode='r', flags=portalocker.LOCK_SH, timeout=10) as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records