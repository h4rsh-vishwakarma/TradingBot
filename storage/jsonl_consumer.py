import os
import json
import time
from storage.jsonl_queue import append_jsonl
from storage.idempotency_store import is_seen, mark_as_seen, init_db

OFFSET_FILE = "storage/queue.offset"
QUEUE_FILE = "storage/tradingview_signals_queue.jsonl"
DLQ_FILE = "storage/dead_letter.jsonl"

def get_last_offset():
    if not os.path.exists(OFFSET_FILE): return 0
    with open(OFFSET_FILE, 'r') as f:
        return int(f.read().strip() or 0)

def save_offset(offset):
    # Atomic offset save: Write to temp then rename
    temp_path = OFFSET_FILE + ".tmp"
    with open(temp_path, 'w') as f:
        f.write(str(offset))
    os.replace(temp_path, OFFSET_FILE)

def consume_queue(process_callback):
    """
    Reads new signals from the queue and processes them.
    process_callback: The function that handles the trade logic.
    """
    init_db()
    current_offset = get_last_offset()
    
    if not os.path.exists(QUEUE_FILE): return

    with open(QUEUE_FILE, 'r') as f:
        f.seek(current_offset)
        
        while True:
            line = f.readline()
            if not line:
                break # Wait for more data later
            
            new_offset = f.tell()
            
            try:
                signal = json.loads(line)
                sig_id = signal.get("signal_id")
                
                # Check Idempotency (Deduplication)
                if sig_id and is_seen(sig_id):
                    print(f"Skipping duplicate signal: {sig_id}")
                else:
                    # Process the trade!
                    process_callback(signal)
                    if sig_id: mark_as_seen(sig_id)
                
                # Update progress
                save_offset(new_offset)
                
            except Exception as e:
                # Move bad signals to DLQ
                print(f"Error processing signal, moving to DLQ: {e}")
                append_jsonl(DLQ_FILE, {"raw": line, "error": str(e)})
                save_offset(new_offset)