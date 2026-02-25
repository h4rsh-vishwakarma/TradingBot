"""
Hardened Offset-Based JSONL Consumer
Uses Byte Offsets for O(1) jump performance and DLQ for crash-safe processing.
"""

import json
import os
import time
import logging
from pathlib import Path
from typing import Callable, Optional, Dict, Any

logger = logging.getLogger(__name__)

class JsonlOffsetConsumer:
    def __init__(self, queue_path: str, offset_path: Optional[str] = None, dlq_path: Optional[str] = None):
        self.queue_path = Path(queue_path)
        # Default naming convention if paths not provided
        self.offset_path = Path(offset_path or f"{queue_path}.offset")
        self.dlq_path = Path(dlq_path or f"{queue_path}.dlq")
        
        # Ensure directories exist
        self.offset_path.parent.mkdir(parents=True, exist_ok=True)
        self.dlq_path.parent.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"📖 Consumer initialized for: {self.queue_path.name}")

    def _read_offset(self) -> int:
        """Read last processed byte offset."""
        if not self.offset_path.exists():
            return 0
        try:
            return int(self.offset_path.read_text().strip())
        except (ValueError, OSError):
            return 0

    def _write_offset(self, offset: int):
        """Atomically write byte offset using temp file + rename."""
        temp_path = self.offset_path.with_suffix(".tmp")
        temp_path.write_text(str(offset))
        os.replace(temp_path, self.offset_path)

    def _move_to_dlq(self, raw_line: str, error: str):
        """Log corrupt or failed lines to Dead Letter Queue."""
        record = {
            "timestamp": time.time(),
            "error": error,
            "raw": raw_line.strip()
        }
        with open(self.dlq_path, 'a') as f:
            f.write(json.dumps(record) + '\n')

    def poll(self, handler: Callable[[Dict[str, Any]], bool], batch_size: int = 50) -> Dict[str, int]:
        """
        Polls the queue. Jump to offset, process batch, advance offset.
        """
        stats = {'processed': 0, 'dlq': 0, 'failed': 0}
        
        if not self.queue_path.exists():
            return stats

        current_offset = self._read_offset()
        
        with open(self.queue_path, 'r') as f:
            # INSTANT JUMP to the last known position (O(1) complexity)
            f.seek(current_offset)
            
            for _ in range(batch_size):
                line_start = f.tell() # Remember where this line started
                line = f.readline()
                
                if not line: break # EOF
                
                clean_line = line.strip()
                if not clean_line:
                    current_offset = f.tell()
                    continue

                try:
                    data = json.loads(clean_line)
                    # Attempt processing
                    if handler(data):
                        # ONLY advance offset on success
                        current_offset = f.tell()
                        self._write_offset(current_offset)
                        stats['processed'] += 1
                    else:
                        # Logic failure: stop batch to prevent message loss
                        logger.error(f"Handler failed at offset {line_start}. Stopping batch.")
                        stats['failed'] += 1
                        break

                except json.JSONDecodeError as e:
                    logger.error(f"Corrupt JSON at {line_start}. Moving to DLQ.")
                    self._move_to_dlq(line, str(e))
                    # Advance past the corrupt line so we don't get stuck
                    current_offset = f.tell()
                    self._write_offset(current_offset)
                    stats['dlq'] += 1

        return stats
