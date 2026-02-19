"""
Atomic JSONL Queue Writer
Provides thread-safe, crash-safe appends to JSONL files with file locking and fsync.
"""

import json
import fcntl
import os
import threading
from pathlib import Path
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)


class AtomicJsonlQueue:
    """Thread-safe JSONL queue with atomic writes."""
    
    def __init__(self, queue_path: str):
        """
        Initialize atomic queue.
        
        Args:
            queue_path: Path to JSONL queue file
        """
        self.queue_path = Path(queue_path)
        self.queue_path.parent.mkdir(parents=True, exist_ok=True)
        self._local_lock = threading.Lock()
        
        logger.info(f"📝 Atomic queue initialized: {queue_path}")
    
    def append(self, record: Dict[str, Any]) -> bool:
        """
        Atomically append a record to the queue.
        
        Uses file-level locking (fcntl) to prevent concurrent write corruption.
        Calls fsync() to ensure data is written to disk before releasing lock.
        
        Args:
            record: Dictionary to append as JSON line
            
        Returns:
            True if successful, False otherwise
        """
        with self._local_lock:  # Thread-level lock first
            try:
                # Serialize to JSON first (fail fast if not serializable)
                json_line = json.dumps(record) + '\n'
                
                # Open file for append, create if doesn't exist
                fd = os.open(
                    str(self.queue_path), 
                    os.O_WRONLY | os.O_APPEND | os.O_CREAT,
                    0o644
                )
                
                try:
                    # Acquire exclusive lock (blocks if another process holds it)
                    fcntl.flock(fd, fcntl.LOCK_EX)
                    
                    try:
                        # Write the JSON line
                        os.write(fd, json_line.encode('utf-8'))
                        
                        # Force write to disk (durability guarantee)
                        os.fsync(fd)
                        
                        return True
                        
                    finally:
                        # Always release the lock
                        fcntl.flock(fd, fcntl.LOCK_UN)
                        
                finally:
                    # Always close the file descriptor
                    os.close(fd)
                    
            except Exception as e:
                logger.error(f"❌ Failed to append to queue: {e}")
                return False
    
    def read_all(self) -> list:
        """
        Read all lines from queue (for migration/debugging).
        
        Returns:
            List of dictionaries
        """
        if not self.queue_path.exists():
            return []
        
        records = []
        try:
            with open(self.queue_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError as e:
                            logger.warning(f"Malformed line: {line[:50]}... | Error: {e}")
                            continue
        except Exception as e:
            logger.error(f"Failed to read queue: {e}")
        
        return records
    
    def count_lines(self) -> int:
        """Count total lines in queue."""
        if not self.queue_path.exists():
            return 0
        
        try:
            with open(self.queue_path, 'r') as f:
                return sum(1 for line in f if line.strip())
        except:
            return 0
    
    def size_bytes(self) -> int:
        """Get queue file size in bytes."""
        if not self.queue_path.exists():
            return 0
        return self.queue_path.stat().st_size


# Convenience function
def append_jsonl(path: str, record: Dict[str, Any]) -> bool:
    """
    Convenience function for one-off atomic appends.
    
    For repeated appends, instantiate AtomicJsonlQueue to avoid overhead.
    """
    queue = AtomicJsonlQueue(path)
    return queue.append(record)


if __name__ == "__main__":
    # Test: Concurrent write safety
    import time
    import threading
    from datetime import datetime
    
    test_queue = "storage/test_queue.jsonl"
    
    # Clean slate
    if os.path.exists(test_queue):
        os.remove(test_queue)
    
    queue = AtomicJsonlQueue(test_queue)
    
    def writer(thread_id, count):
        """Write multiple records from a thread."""
        for i in range(count):
            record = {
                'thread': thread_id,
                'index': i,
                'timestamp': datetime.utcnow().isoformat()
            }
            success = queue.append(record)
            if not success:
                print(f"❌ Thread {thread_id} failed to write record {i}")
            time.sleep(0.001)  # Tiny delay to encourage interleaving
    
    print("🧪 Testing concurrent writes...")
    threads = []
    for tid in range(5):
        t = threading.Thread(target=writer, args=(tid, 20))
        threads.append(t)
        t.start()
    
    for t in threads:
        t.join()
    
    # Verify results
    records = queue.read_all()
    print(f"✅ Wrote {len(records)} records (expected 100)")
    print(f"📊 File size: {queue.size_bytes()} bytes")
    
    # Check all lines are valid JSON
    all_valid = all('thread' in r and 'index' in r for r in records)
    print(f"{'✅' if all_valid else '❌'} All lines are valid JSON")
    
    # Count per thread
    from collections import Counter
    thread_counts = Counter(r['thread'] for r in records)
    print(f"📊 Per-thread counts: {dict(thread_counts)}")
    
    print("\n✅ Atomic queue test complete!")
