"""test_kill_switch.py
T6 audit fix: verify kill switch activate/deactivate cycle.
"""
import os, sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KILL_SWITCH_FILE = PROJECT_ROOT / "tradingview_webhook_bot" / "storage" / "KILL_SWITCH"

def _clear():
    if KILL_SWITCH_FILE.exists(): KILL_SWITCH_FILE.unlink()

def test_activate_creates_sentinel():
    """activate_kill_switch() must create the KILL_SWITCH sentinel file."""
    from scripts.kill_switch import activate_kill_switch, deactivate_kill_switch
    _clear()
    try:
        activate_kill_switch()
        assert KILL_SWITCH_FILE.exists(), "KILL_SWITCH sentinel not created"
        assert "ACTIVATED" in KILL_SWITCH_FILE.read_text(), "Missing ACTIVATED in sentinel"
    finally:
        deactivate_kill_switch()

def test_deactivate_removes_sentinel():
    """deactivate_kill_switch() must remove the KILL_SWITCH file."""
    from scripts.kill_switch import activate_kill_switch, deactivate_kill_switch
    activate_kill_switch()
    assert KILL_SWITCH_FILE.exists()
    deactivate_kill_switch()
    assert not KILL_SWITCH_FILE.exists(), "KILL_SWITCH still present after deactivate"

def test_deactivate_idempotent():
    """deactivate_kill_switch() must not raise when switch is already off."""
    from scripts.kill_switch import deactivate_kill_switch
    _clear()
    deactivate_kill_switch()  # should not raise
    assert not KILL_SWITCH_FILE.exists()

def test_sentinel_contains_timestamp():
    """KILL_SWITCH sentinel must contain a timestamp string."""
    from scripts.kill_switch import activate_kill_switch, deactivate_kill_switch
    _clear()
    try:
        activate_kill_switch()
        text = KILL_SWITCH_FILE.read_text()
        assert len(text) > 10, "KILL_SWITCH file too short, timestamp missing"
    finally:
        deactivate_kill_switch()
