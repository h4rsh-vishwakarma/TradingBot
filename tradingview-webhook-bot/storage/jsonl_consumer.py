"""
Hardened Offset-Based JSONL Consumer
Fixed Path Resolution and Absolute Offsetting
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
        # 1. Resolve Path to Absolute to avoid .name or relative path confusion
        self.queue_path = Path(queue_path).resolve()
        
        # 2. Fix Offset & DLQ naming logic using .with_suffix
        # If queue is 'storage/signals.jsonl', offset becomes 'storage/signals.jsonl.offset'
        self.offset_path = Path(offset_path) if offset_path else self.queue_path.with_suffix(self.queue_path.suffix + ".offset")
        self.dlq_path = Path(dlq_path) if dlq_path else self.queue_path.with_suffix(self.queue_path.suffix + ".dlq")

        # Ensure directories exist for all paths
        self.offset_path.parent.mkdir(parents=True, exist_ok=True)
        self.dlq_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"📖 Consumer initialized")
        logger.info(f"📂 Queue: {self.queue_path}")
        logger.info(f"📍 Offset: {self.offset_path}")

    def _read_offset(self) -> int:
        """Read last processed byte offset safely."""
        if not self.offset_path.exists():
            return 0
        try:
            content = self.offset_path.read_text().strip()
            return int(content) if content else 0
        except (ValueError, OSError, Exception) as e:
            logger.error(f"⚠️ Error reading offset file: {e}")
            return 0

    def _write_offset(self, offset: int):
        """Atomically write byte offset using temp file + rename."""
        try:
            temp_path = self.offset_path.with_suffix(".tmp")
            temp_path.write_text(str(offset))
            os.replace(temp_path, self.offset_path)
        except Exception as e:
            logger.error(f"❌ Critical: Could not write offset: {e}")

    def _move_to_dlq(self, raw_line: str, error: str):
        """Log corrupt or failed lines to Dead Letter Queue."""
        record = {
            "timestamp": time.time(),
            "error": error,
            "raw": raw_line.strip()
        }
        try:
            with open(self.dlq_path, 'a') as f:
                f.write(json.dumps(record) + '\n')
        except Exception as e:
            logger.error(f"🔥 DLQ Write Failure: {e}")

    def poll(self, handler: Callable[[Dict[str, Any]], bool], batch_size: int = 50) -> Dict[str, int]:
        """
        Polls the queue. Jump to offset, process batch, advance offset.
        """
        stats = {'processed': 0, 'dlq': 0, 'failed': 0}

        if not self.queue_path.exists():
            return stats

        current_offset = self._read_offset()

        # Open in 'r' mode and seek to the saved byte position
        with open(self.queue_path, 'r') as f:
            # INSTANT JUMP (O(1))
            f.seek(0, os.SEEK_END)
            file_end = f.tell()
            
            # Agar file truncate hui hai (size chota ho gaya), toh 0 se shuru karein
            if current_offset > file_end:
                logger.warning("🔄 File truncated detected. Resetting offset to 0.")
                current_offset = 0

            f.seek(current_offset)

            for _ in range(batch_size):
                line_start = f.tell()
                line = f.readline()

                if not line: 
                    break # End of File reached

                clean_line = line.strip()
                if not clean_line:
                    # Empty line? Just skip it and advance offset
                    current_offset = f.tell()
                    self._write_offset(current_offset)
                    continue

                try:
                    data = json.loads(clean_line)
                    # Attempt processing via handler
                    if handler(data):
                        # ONLY advance offset on successful processing
                        current_offset = f.tell()
                        self._write_offset(current_offset)
                        stats['processed'] += 1
                    else:
                        # Logic failure: stop batch to prevent data loss/skip
                        logger.error(f"🛑 Handler returned False at offset {line_start}. Stopping batch.")
                        stats['failed'] += 1
                        break

                except json.JSONDecodeError as e:
                    logger.error(f"💥 Corrupt JSON at {line_start}. Moving to DLQ.")
                    self._move_to_dlq(line, str(e))
                    # Advance past the corrupt line
                    current_offset = f.tell()
                    self._write_offset(current_offset)
                    stats['dlq'] += 1
                except Exception as e:
                    logger.error(f"❌ Unexpected error at offset {line_start}: {e}")
                    stats['failed'] += 1
                    break

        return stats
