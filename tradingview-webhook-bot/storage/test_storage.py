import pytest
import os
import json
from tradingview_webhook_bot.storage.jsonl_queue import append_jsonl, read_jsonl
from tradingview_webhook_bot.storage.jsonl_consumer import JsonlOffsetConsumer
from tradingview_webhook_bot.storage.idempotency_store import IdempotencyStore

# --- 1. QUEUE TESTS (Atomic Writes & Reads) ---
def test_queue_append_and_read(tmp_path):
    test_file = tmp_path / "test_queue.jsonl"
    data = {"signal_id": "test_1", "symbol": "BTCUSDT"}
    
    # Test Append
    append_jsonl(str(test_file), data)
    
    # Test Read
    results = read_jsonl(str(test_file))
    assert len(results) == 1
    assert results[0]["signal_id"] == "test_1"

def test_atomic_writes(tmp_path):
    test_file = tmp_path / "atomic.jsonl"
    for i in range(10):
        append_jsonl(str(test_file), {"id": i})
    
    results = read_jsonl(str(test_file))
    assert len(results) == 10


# --- 2. CONSUMER TESTS (Byte Offsets & DLQ) ---
def test_consumer_flow(tmp_path):    
    q = tmp_path / "queue.jsonl"
    o = tmp_path / "offset.txt"
    d = tmp_path / "dlq.jsonl"

    # Create mixed data: Valid, Corrupt, and another Valid
    with open(q, 'w') as f:
        f.write(json.dumps({"id": "valid_1"}) + "\n")
        f.write("INVALID_JSON_HERE\n")
        f.write(json.dumps({"id": "valid_2"}) + "\n")

    consumer = JsonlOffsetConsumer(str(q), str(o), str(d))

    results = []
    def handler(data):
        results.append(data)
        return True

    stats = consumer.poll(handler)

    # Verify results
    assert stats['processed'] == 2  # Do sahi signals process hue
    assert stats['dlq'] == 1        # Ek malformed signal DLQ mein gaya
    assert int(o.read_text()) > 0    # Bookmark (offset) file update hui
    assert len(results) == 2        # Handler ne sirf 2 signals receive kiye


# --- 3. IDEMPOTENCY TESTS (Duplicate Prevention) ---
def test_idempotency_store(tmp_path):
    db_file = tmp_path / "idempotency.db"
    store = IdempotencyStore(str(db_file))
    
    signal_id = "TV-SIG-999"
    
    # Pehli baar: Signal naya hona chahiye (False)
    assert store.seen(signal_id) is False
    
    # Dusri baar: Signal duplicate hona chahiye (True)
    assert store.seen(signal_id) is True
    
    # Naya signal: Phir se False hona chahiye
    assert store.seen("TV-SIG-1000") is False
