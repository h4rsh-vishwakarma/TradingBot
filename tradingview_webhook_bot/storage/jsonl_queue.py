import json
import os
import fcntl
import logging

logger = logging.getLogger(__name__)

def append_jsonl(file_path: str, data: dict):
    """
    Hardened append using File Locking (fcntl) for multi-process safety.
    """
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        line = json.dumps(data) + "\n"
        
        with open(file_path, 'a') as f:
            # Exclusive lock: prevents other processes from writing/reading during append
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.write(line)
                f.flush()
                os.fsync(f.fileno()) # Guarantee write to disk
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        return True
    except Exception as e:
        logger.error(f"❌ JSONL Append Failure: {e}")
        return False

class AtomicJsonlQueue:
    def __init__(self, file_path):
        self.file_path = file_path

    def enqueue(self, data):
        return append_jsonl(self.file_path, data)
