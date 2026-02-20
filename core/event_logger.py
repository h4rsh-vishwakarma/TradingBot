import time
from storage.jsonl_queue import append_jsonl

EVENT_LOG_PATH = "storage/event_logs.jsonl"

def log_event(event_name, signal_id, extra_data=None):
    """
    Subtask 5.1: Logs key events to a JSONL file for auditing.
    """
    event = {
        "timestamp": time.time(),
        "event": event_name,
        "signal_id": signal_id,
        "data": extra_data or {}
    }
    append_jsonl(EVENT_LOG_PATH, event)