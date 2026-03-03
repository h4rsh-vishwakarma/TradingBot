"""
Instance Lock Manager for Trading Bot

Prevents multiple bot instances for the same strategy from running concurrently.
Uses file-based locking with PID tracking and stale lock detection.
"""

import os
import sys
import time
import fcntl
import signal
import psutil
from pathlib import Path
from typing import Optional
from utils.logger import setup_logger

logger = setup_logger('instance_lock')


class InstanceLockError(Exception):
    """Raised when unable to acquire instance lock"""
    pass


class InstanceLock:
    """
    File-based instance lock to prevent concurrent bot instances.
    
    Features:
    - PID-based locking
    - Stale lock detection and cleanup
    - Automatic release on exit
    - Signal handler for cleanup
    """
    
    def __init__(self, strategy_name: str, lock_dir: str = "storage/locks"):
        """
        Initialize instance lock.
        
        Args:
            strategy_name: Strategy identifier
            lock_dir: Directory for lock files
        """
        self.strategy_name = strategy_name
        self.lock_dir = Path(lock_dir)
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        
        self.lock_file = self.lock_dir / f"{strategy_name}.lock"
        self.lock_fd: Optional[int] = None
        self.acquired = False
        
        # Register cleanup on exit
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle termination signals"""
        logger.info(f"🛑 Received signal {signum}, releasing lock...")
        self.release()
        sys.exit(0)
    
    def _is_process_running(self, pid: int) -> bool:
        """
        Check if a process with given PID is running.
        
        Args:
            pid: Process ID to check
            
        Returns:
            True if process exists and is running
        """
        try:
            process = psutil.Process(pid)
            return process.is_running()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False
    
    def _read_lock_file(self) -> Optional[int]:
        """
        Read PID from lock file.
        
        Returns:
            PID if lock file exists and is valid, None otherwise
        """
        if not self.lock_file.exists():
            return None
        
        try:
            with open(self.lock_file, 'r') as f:
                content = f.read().strip()
                if content:
                    return int(content)
        except (ValueError, IOError) as e:
            logger.warning(f"⚠️ Invalid lock file: {e}")
            return None
        
        return None
    
    def _write_lock_file(self):
        """Write current PID to lock file"""
        try:
            with open(self.lock_file, 'w') as f:
                f.write(str(os.getpid()))
                f.flush()
        except IOError as e:
            raise InstanceLockError(f"Failed to write lock file: {e}")
    
    def _remove_stale_lock(self):
        """Remove stale lock file if process is not running"""
        existing_pid = self._read_lock_file()
        
        if existing_pid is not None:
            if not self._is_process_running(existing_pid):
                logger.warning(f"⚠️ Removing stale lock (PID {existing_pid} not running)")
                try:
                    self.lock_file.unlink()
                    return True
                except IOError as e:
                    logger.error(f"❌ Failed to remove stale lock: {e}")
                    return False
        
        return False
    
    def acquire(self, wait: bool = False, timeout: int = 30) -> bool:
        """
        Acquire instance lock.
        
        Args:
            wait: Wait for lock to become available
            timeout: Maximum wait time in seconds
            
        Returns:
            True if lock acquired successfully
            
        Raises:
            InstanceLockError: If lock cannot be acquired
        """
        if self.acquired:
            logger.warning("⚠️ Lock already acquired by this instance")
            return True
        
        start_time = time.time()
        
        while True:
            # Check for stale lock
            self._remove_stale_lock()
            
            # Try to acquire lock
            existing_pid = self._read_lock_file()
            
            if existing_pid is None:
                # No lock file, we can proceed
                try:
                    self._write_lock_file()
                    
                    # Open file for fcntl locking
                    self.lock_fd = os.open(str(self.lock_file), os.O_RDWR)
                    
                    # Try to acquire exclusive lock (non-blocking)
                    try:
                        fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        self.acquired = True
                        logger.info(f"🔒 Instance lock acquired for strategy '{self.strategy_name}' (PID {os.getpid()})")
                        return True
                    except IOError:
                        # Lock already held by another process
                        os.close(self.lock_fd)
                        self.lock_fd = None
                        existing_pid = self._read_lock_file()
                
                except IOError as e:
                    raise InstanceLockError(f"Failed to acquire lock: {e}")
            
            # Lock exists and is held by another process
            if existing_pid and self._is_process_running(existing_pid):
                if not wait:
                    raise InstanceLockError(
                        f"Another instance is already running (PID {existing_pid}). "
                        f"Strategy: {self.strategy_name}"
                    )
                
                # Check timeout
                if time.time() - start_time >= timeout:
                    raise InstanceLockError(
                        f"Timeout waiting for lock (held by PID {existing_pid})"
                    )
                
                logger.info(f"⏳ Waiting for lock (held by PID {existing_pid})...")
                time.sleep(1)
            else:
                # Process not running, remove stale lock and retry
                self._remove_stale_lock()
    
    def release(self):
        """Release instance lock"""
        if not self.acquired:
            return
        
        try:
            # Release fcntl lock
            if self.lock_fd is not None:
                fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
                os.close(self.lock_fd)
                self.lock_fd = None
            
            # Remove lock file
            if self.lock_file.exists():
                self.lock_file.unlink()
            
            self.acquired = False
            logger.info(f"🔓 Instance lock released for strategy '{self.strategy_name}'")
        
        except Exception as e:
            logger.error(f"❌ Error releasing lock: {e}")
    
    def __enter__(self):
        """Context manager entry"""
        self.acquire()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.release()
    
    def __del__(self):
        """Destructor - ensure lock is released"""
        self.release()


def acquire_strategy_lock(strategy_name: str) -> InstanceLock:
    """
    Acquire instance lock for a strategy.
    
    Args:
        strategy_name: Strategy identifier
        
    Returns:
        InstanceLock object
        
    Raises:
        InstanceLockError: If lock cannot be acquired
    """
    lock = InstanceLock(strategy_name)
    lock.acquire()
    return lock
