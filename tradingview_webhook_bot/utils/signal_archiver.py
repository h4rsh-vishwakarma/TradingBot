"""
Signal Queue Archiver - Prevents unbounded queue growth

PROBLEM SOLVED:
- Signal queue grows indefinitely with processed signals
- Currently 1,337 old signals from Jan 24, 2026 still in queue
- Slows down processing and wastes disk space

SOLUTION:
- Archive processed signals older than retention period
- Compress archives (gzip) to save space
- Keep only active/recent signals in live queue
- Enable historical signal analysis when needed
"""
import json
import os
import gzip
from datetime import datetime, timedelta
from utils.logger import setup_logger

logger = setup_logger('signal_archiver')

class SignalArchiver:
    """Archives processed signals older than retention period"""
    
    def __init__(self, retention_days=7):
        """
        Initialize signal archiver.
        
        Args:
            retention_days: How many days to keep signals in live queue
                           Older processed signals are archived
                           Default: 7 days (keep 1 week of history live)
        """
        self.retention_days = retention_days
        self.archive_dir = 'storage/archive'
        os.makedirs(self.archive_dir, exist_ok=True)
        
        logger.info(f"📦 Signal Archiver initialized")
        logger.info(f"   Retention period: {retention_days} days")
        logger.info(f"   Archive directory: {self.archive_dir}")
    
    def archive_old_signals(self, queue_file):
        """
        Move old processed signals to compressed archive file.
        
        Process:
        1. Read all signals from queue
        2. Separate into: active (unprocessed or recent) vs archivable (old processed)
        3. Write archivable signals to dated gzip file
        4. Rewrite queue with only active signals
        5. Return statistics
        
        Args:
            queue_file: Path to signals queue JSONL file
        
        Returns:
            tuple: (active_count, archived_count)
        """
        if not os.path.exists(queue_file):
            logger.warning(f"⚠️ Queue file not found: {queue_file}")
            return 0, 0
        
        cutoff_time = datetime.utcnow() - timedelta(days=self.retention_days)
        logger.info(f"🕐 Archiving signals processed before {cutoff_time.isoformat()}")
        
        active_signals = []
        archive_signals = []
        parse_errors = 0
        
        # Read and categorize signals
        try:
            with open(queue_file, 'r') as f:
                for line_num, line in enumerate(f, 1):
                    try:
                        signal = json.loads(line.strip())
                        
                        # RULE 1: Keep all unprocessed signals (need to be executed)
                        if not signal.get('processed'):
                            active_signals.append(signal)
                            continue
                        
                        # RULE 2: Check when signal was processed
                        processed_at = signal.get('processed_at', '')
                        if processed_at:
                            # Parse timestamp (handle both ISO formats)
                            processed_at_clean = processed_at.replace('Z', '+00:00').replace('+00:00', '')
                            try:
                                processed_time = datetime.fromisoformat(processed_at_clean)
                            except ValueError:
                                # Fallback: Try with Z stripped
                                processed_time = datetime.fromisoformat(processed_at.rstrip('Z'))
                            
                            # RULE 3: Archive if older than cutoff, keep if recent
                            if processed_time < cutoff_time:
                                archive_signals.append(signal)
                            else:
                                active_signals.append(signal)
                        else:
                            # No processed_at timestamp, keep it active to be safe
                            logger.warning(f"⚠️ Signal {signal.get('signal_id')} marked processed but no timestamp")
                            active_signals.append(signal)
                            
                    except json.JSONDecodeError as e:
                        parse_errors += 1
                        logger.warning(f"⚠️ Failed to parse line {line_num}: {e}")
                        continue
                    except Exception as e:
                        parse_errors += 1
                        logger.warning(f"⚠️ Error processing line {line_num}: {e}")
                        continue
        
        except Exception as e:
            logger.error(f"❌ Failed to read queue file: {e}")
            return 0, 0
        
        logger.info(f"📊 Categorization complete:")
        logger.info(f"   Active signals: {len(active_signals)}")
        logger.info(f"   Archivable signals: {len(archive_signals)}")
        logger.info(f"   Parse errors: {parse_errors}")
        
        # Create archive file if there are signals to archive
        if archive_signals:
            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            archive_filename = os.path.join(
                self.archive_dir,
                f"signals_archive_{timestamp}.jsonl.gz"
            )
            
            try:
                with gzip.open(archive_filename, 'wt', encoding='utf-8') as f:
                    for signal in archive_signals:
                        f.write(json.dumps(signal) + '\n')
                
                # Get file size for logging
                archive_size_bytes = os.path.getsize(archive_filename)
                archive_size_kb = archive_size_bytes / 1024
                
                logger.info(f"📦 Created archive: {archive_filename}")
                logger.info(f"   Signals archived: {len(archive_signals)}")
                logger.info(f"   Compressed size: {archive_size_kb:.2f} KB")
                
            except Exception as e:
                logger.error(f"❌ Failed to create archive file: {e}")
                # Don't proceed to rewrite queue if archiving failed
                return len(active_signals), 0
        else:
            logger.info(f"✓ No signals to archive (all signals are recent)")
        
        # Rewrite queue with active signals only
        try:
            # Write to temp file first (atomic operation)
            temp_file = queue_file + '.tmp'
            with open(temp_file, 'w') as f:
                for signal in active_signals:
                    f.write(json.dumps(signal) + '\n')
            
            # Atomic rename (replaces original file)
            os.replace(temp_file, queue_file)
            
            logger.info(f"✅ Queue file updated: {queue_file}")
            logger.info(f"   New size: {len(active_signals)} signals")
            
        except Exception as e:
            logger.error(f"❌ Failed to rewrite queue file: {e}")
            # Clean up temp file if it exists
            if os.path.exists(temp_file):
                os.remove(temp_file)
            return len(active_signals), len(archive_signals)
        
        return len(active_signals), len(archive_signals)
    
    def get_archive_stats(self):
        """
        Get statistics about archived signals.
        
        Returns:
            dict: Archive statistics
        """
        if not os.path.exists(self.archive_dir):
            return {
                'total_archives': 0,
                'total_size_mb': 0,
                'oldest_archive': None,
                'newest_archive': None
            }
        
        archives = [f for f in os.listdir(self.archive_dir) if f.endswith('.jsonl.gz')]
        
        if not archives:
            return {
                'total_archives': 0,
                'total_size_mb': 0,
                'oldest_archive': None,
                'newest_archive': None
            }
        
        total_size = sum(
            os.path.getsize(os.path.join(self.archive_dir, f)) 
            for f in archives
        )
        
        archives_sorted = sorted(archives)
        
        return {
            'total_archives': len(archives),
            'total_size_mb': total_size / (1024 * 1024),
            'oldest_archive': archives_sorted[0],
            'newest_archive': archives_sorted[-1],
            'archive_files': archives_sorted
        }
    
    def read_archive(self, archive_filename):
        """
        Read signals from an archive file.
        
        Args:
            archive_filename: Name of archive file (e.g., signals_archive_20260218_120000.jsonl.gz)
        
        Returns:
            list: List of signal dicts from archive
        """
        archive_path = os.path.join(self.archive_dir, archive_filename)
        
        if not os.path.exists(archive_path):
            logger.error(f"❌ Archive file not found: {archive_path}")
            return []
        
        signals = []
        try:
            with gzip.open(archive_path, 'rt', encoding='utf-8') as f:
                for line in f:
                    try:
                        signal = json.loads(line.strip())
                        signals.append(signal)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"❌ Failed to read archive: {e}")
            return []
        
        logger.info(f"📖 Read {len(signals)} signals from archive: {archive_filename}")
        return signals
    
    def cleanup_old_archives(self, max_age_days=30):
        """
        Delete archives older than max_age_days.
        
        Args:
            max_age_days: Maximum age of archives to keep (default: 30 days)
        
        Returns:
            int: Number of archives deleted
        """
        if not os.path.exists(self.archive_dir):
            return 0
        
        cutoff_time = datetime.utcnow() - timedelta(days=max_age_days)
        deleted_count = 0
        
        for filename in os.listdir(self.archive_dir):
            if not filename.endswith('.jsonl.gz'):
                continue
            
            filepath = os.path.join(self.archive_dir, filename)
            
            # Get file creation time
            file_time = datetime.fromtimestamp(os.path.getctime(filepath))
            
            if file_time < cutoff_time:
                try:
                    os.remove(filepath)
                    deleted_count += 1
                    logger.info(f"🗑️ Deleted old archive: {filename} (age: {(datetime.utcnow() - file_time).days} days)")
                except Exception as e:
                    logger.error(f"❌ Failed to delete archive {filename}: {e}")
        
        if deleted_count > 0:
            logger.info(f"✅ Cleaned up {deleted_count} old archive(s) older than {max_age_days} days")
        else:
            logger.info(f"✓ No archives older than {max_age_days} days to clean up")
        
        return deleted_count
