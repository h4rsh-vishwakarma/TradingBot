"""
Offset-Based JSONL Consumer
Provides restart-safe consumption of JSONL queues with dead-letter handling.
"""

import json
import os
import time
from pathlib import Path
from typing import Callable, Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class JsonlOffsetConsumer:
    """
    Offset-based consumer for JSONL queues.
    
    Features:
    - Restart-safe: Tracks last processed offset in separate file
    - Dead-letter queue: Moves malformed lines to DLQ
    - Atomic offset updates: Uses temp file + rename for crash safety
    """
    
    def __init__(self, queue_path: str, offset_path: Optional[str] = None, dlq_path: Optional[str] = None):
        """
        Initialize consumer.
        
        Args:
            queue_path: Path to JSONL queue file
            offset_path: Path to offset file (default: {queue_path}.offset)
            dlq_path: Path to dead-letter queue (default: {queue_path}.dlq)
        """
        self.queue_path = Path(queue_path)
        self.offset_path = Path(offset_path or f"{queue_path}.offset")
        self.dlq_path = Path(dlq_path or f"{queue_path}.dlq")
        
        # Ensure directories exist
        self.queue_path.parent.mkdir(parents=True, exist_ok=True)
        self.offset_path.parent.mkdir(parents=True, exist_ok=True)
        self.dlq_path.parent.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"📖 Consumer initialized: {queue_path}")
        logger.info(f"   Offset: {self.offset_path}")
        logger.info(f"   DLQ: {self.dlq_path}")
    
    def read_offset(self) -> int:
        """
        Read last processed offset.
        
        Returns:
            Line number (0-based) of last successfully processed line, or 0 if no offset file
        """
        if not self.offset_path.exists():
            return 0
        
        try:
            with open(self.offset_path, 'r') as f:
                offset = int(f.read().strip())
                return offset
        except Exception as e:
            logger.warning(f"Failed to read offset, starting from 0: {e}")
            return 0
    
    def write_offset(self, offset: int) -> bool:
        """
        Atomically write offset using temp file + rename.
        
        Args:
            offset: Line number of last successfully processed line
            
        Returns:
            True if successful
        """
        try:
            # Write to temp file first
            temp_path = Path(str(self.offset_path) + '.tmp')
            with open(temp_path, 'w') as f:
                f.write(str(offset))
                f.flush()
                os.fsync(f.fileno())
            
            # Atomic rename (overwrites target on most systems)
            os.replace(temp_path, self.offset_path)
            return True
            
        except Exception as e:
            logger.error(f"Failed to write offset: {e}")
            return False
    
    def append_to_dlq(self, raw_line: str, error: str, line_number: int):
        """
        Append malformed line to dead-letter queue.
        
        Args:
            raw_line: The malformed line
            error: Error message
            line_number: Line number in original queue
        """
        try:
            dlq_record = {
                'raw_line': raw_line.strip(),
                'error': str(error),
                'line_number': line_number,
                'timestamp': time.time()
            }
            
            # Simple append (DLQ doesn't need atomic writes)
            with open(self.dlq_path, 'a') as f:
                f.write(json.dumps(dlq_record) + '\n')
            
            logger.warning(f"📮 Moved malformed line {line_number} to DLQ: {error}")
            
        except Exception as e:
            logger.error(f"Failed to write to DLQ: {e}")
    
    def poll(self, handler: Callable[[Dict[str, Any]], bool], batch_size: int = 10, max_retries: int = 3) -> Dict[str, int]:
        """
        Poll queue and process new records.
        
        Args:
            handler: Function that processes record, returns True on success
            batch_size: Maximum number of records to process per call
            max_retries: Number of times to retry failed records
            
        Returns:
            Statistics dict with processed/failed/dlq counts
        """
        stats = {
            'processed': 0,
            'failed': 0,
            'dlq': 0,
            'skipped': 0
        }
        
        if not self.queue_path.exists():
            return stats
        
        # Read current offset
        start_offset = self.read_offset()
        current_offset = start_offset
        
        try:
            with open(self.queue_path, 'r') as f:
                # Skip to start offset
                for _ in range(start_offset):
                    f.readline()
                
                # Process batch
                for _ in range(batch_size):
                    line = f.readline()
                    if not line:
                        break  # End of file
                    
                    line = line.strip()
                    if not line:
                        current_offset += 1
                        stats['skipped'] += 1
                        continue
                    
                    # Try to parse JSON
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError as e:
                        # Malformed JSON -> DLQ
                        self.append_to_dlq(line, str(e), current_offset)
                        current_offset += 1
                        stats['dlq'] += 1
                        
                        # Update offset even for DLQ (don't retry forever)
                        self.write_offset(current_offset)
                        continue
                    
                    # Process record
                    retry_count = 0
                    success = False
                    
                    while retry_count < max_retries and not success:
                        try:
                            success = handler(record)
                            
                            if success:
                                stats['processed'] += 1
                                current_offset += 1
                                
                                # Update offset after each successful process
                                self.write_offset(current_offset)
                            else:
                                retry_count += 1
                                if retry_count < max_retries:
                                    time.sleep(0.5 * retry_count)  # Exponential backoff
                                    
                        except Exception as e:
                            logger.error(f"Handler error at line {current_offset}: {e}")
                            retry_count += 1
                            if retry_count < max_retries:
                                time.sleep(0.5 * retry_count)
                    
                    if not success:
                        # Failed after retries -> DLQ
                        self.append_to_dlq(
                            line, 
                            f"Handler failed after {max_retries} retries", 
                            current_offset
                        )
                        current_offset += 1
                        stats['failed'] += 1
                        
                        # Update offset to skip this record
                        self.write_offset(current_offset)
        
        except Exception as e:
            logger.error(f"Consumer error: {e}")
        
        return stats
    
    def reset_offset(self):
        """Reset offset to 0 (reprocess all signals)."""
        self.write_offset(0)
        logger.info("🔄 Offset reset to 0")
    
    def get_pending_count(self) -> int:
        """Get number of pending (unprocessed) records."""
        if not self.queue_path.exists():
            return 0
        
        try:
            total_lines = sum(1 for _ in open(self.queue_path))
            offset = self.read_offset()
            return max(0, total_lines - offset)
        except:
            return 0


if __name__ == "__main__":
    # Test: Offset-based consumption with restart
    import tempfile
    import shutil
    
    test_dir = Path("storage/test_consumer")
    shutil.rmtree(test_dir, ignore_errors=True)
    test_dir.mkdir(parents=True, exist_ok=True)
    
    queue_file = test_dir / "signals.jsonl"
    
    # Create test queue
    with open(queue_file, 'w') as f:
        for i in range(10):
            f.write(json.dumps({'id': i, 'msg': f'signal_{i}'}) + '\n')
        
        # Add malformed line
        f.write('{"id": 10, "msg": "missing_quote}\n')
        
        # Add more valid lines
        for i in range(11, 15):
            f.write(json.dumps({'id': i, 'msg': f'signal_{i}'}) + '\n')
    
    print(f"📝 Created test queue with 15 lines (1 malformed)")
    
    consumer = JsonlOffsetConsumer(str(queue_file))
    
    processed_ids = []
    
    def test_handler(record):
        """Test handler that collects IDs."""
        processed_ids.append(record['id'])
        print(f"  ✅ Processed: {record}")
        return True
    
    # Process first 5
    print("\n🔄 Processing first batch (5)...")
    stats1 = consumer.poll(test_handler, batch_size=5)
    print(f"Stats: {stats1}")
    print(f"Offset: {consumer.read_offset()}")
    
    # Simulate restart: Process next 5
    print("\n🔄 Simulating restart, processing next batch (5)...")
    stats2 = consumer.poll(test_handler, batch_size=5)
    print(f"Stats: {stats2}")
    print(f"Offset: {consumer.read_offset()}")
    
    # Process remaining (should include DLQ)
    print("\n🔄 Processing remaining...")
    stats3 = consumer.poll(test_handler, batch_size=10)
    print(f"Stats: {stats3}")
    print(f"Offset: {consumer.read_offset()}")
    
    print(f"\n📊 Total processed IDs: {sorted(processed_ids)}")
    print(f"📊 Pending: {consumer.get_pending_count()}")
    
    # Check DLQ
    if consumer.dlq_path.exists():
        with open(consumer.dlq_path, 'r') as f:
            dlq_entries = [json.loads(line) for line in f if line.strip()]
        print(f"\n📮 DLQ entries: {len(dlq_entries)}")
        for entry in dlq_entries:
            print(f"   Line {entry['line_number']}: {entry['error']}")
    
    print("\n✅ Consumer test complete!")
