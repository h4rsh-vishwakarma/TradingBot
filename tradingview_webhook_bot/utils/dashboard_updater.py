"""
Centralized Dashboard Updater

Uses clean_dashboard_7tabs family scripts and ensures only one process updates
the dashboard at a time across all strategy bots.
"""

import importlib
import os
import time
from pathlib import Path
from typing import Tuple


LOCK_FILE = Path("storage/locks/dashboard_update.lock")
STATE_FILE = Path("storage/locks/dashboard_last_update.txt")


def _load_clean_dashboard_main():
    """Load only clean_dashboard_tab7 module (single source of truth)."""
    module_name = "clean_dashboard_tab7"
    module = importlib.import_module(module_name)

    if hasattr(module, "main"):
        return module.main, module_name
    if hasattr(module, "update_sheet"):
        return module.update_sheet, module_name

    raise ImportError("clean_dashboard_tab7 has no main() or update_sheet()")


def _acquire_lock():
    """Acquire dashboard lock file handle (fcntl on Linux, best-effort on Windows)."""
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = open(LOCK_FILE, "a+")
    except Exception:
        return None, False

    try:
        import fcntl

        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd, True
    except ImportError:
        # Windows fallback in local dev: no cross-process lock
        return fd, True
    except Exception:
        fd.close()
        return None, False


def _release_lock(fd):
    """Release lock file handle."""
    if not fd:
        return

    try:
        import fcntl

        fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass

    try:
        fd.close()
    except Exception:
        pass


def _get_last_update_ts() -> float:
    if not STATE_FILE.exists():
        return 0.0

    try:
        return float(STATE_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return 0.0


def _set_last_update_ts(ts: float):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(str(ts), encoding="utf-8")


def trigger_dashboard_update(strategy_name: str, min_interval_seconds: int = 60) -> Tuple[bool, str]:
    """
    Trigger a single clean-dashboard update safely.

    Returns:
        (updated, message)
    """
    fd, locked = _acquire_lock()
    if not locked:
        return False, f"Dashboard update in progress by another bot (strategy={strategy_name})"

    try:
        now = time.time()
        last_ts = _get_last_update_ts()

        if now - last_ts < min_interval_seconds:
            return False, f"Dashboard throttled ({int(now - last_ts)}s since last update)"

        dashboard_main, module_name = _load_clean_dashboard_main()
        dashboard_main()
        _set_last_update_ts(now)

        return True, f"Dashboard updated via {module_name}"
    finally:
        _release_lock(fd)
