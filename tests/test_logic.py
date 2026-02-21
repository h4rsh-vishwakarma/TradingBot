import os
import pytest
from storage.idempotency_store import init_db, is_seen, mark_as_seen
from bot.orders import generate_deterministic_id

def test_idempotency_logic():
    """Verify that we can detect duplicate signals."""
    init_db()
    test_id = "test_123"
    
    # First time seeing the ID
    assert is_seen(test_id) is False
    mark_as_seen(test_id)
    
    # Second time seeing the ID
    assert is_seen(test_id) is True

def test_deterministic_id_format():
    """Verify the format required in Subtask 4.1."""
    sig_id = "signal_abc"
    generated = generate_deterministic_id(sig_id, venue="binance", leg="main", attempt=1)
    
    # Check if format is {signal_id}_{venue}_{leg}_{attempt}
    assert generated == "signal_abc_binance_main_1"

def test_queue_file_exists():
    """Verify the queue path is correctly set."""
    from core.webhook_server import QUEUE_PATH
    assert "tradingview_signals_queue.jsonl" in QUEUE_PATH