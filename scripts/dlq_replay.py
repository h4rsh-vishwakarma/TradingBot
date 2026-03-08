import json
import os
import shutil
from datetime import datetime
from pathlib import Path

# Using Absolute Paths for production reliability
BASE_STORAGE = Path("/home/ubuntu/tradingview_webhook_bot/tradingview_webhook_bot/storage")
DLQ_PATH = BASE_STORAGE / "dead_letter.jsonl"
QUEUE_PATH = BASE_STORAGE / "signals.jsonl"

def replay_dlq():
    if not DLQ_PATH.exists() or os.path.getsize(DLQ_PATH) == 0:
        print("ℹ️ Nothing to replay. DLQ is empty.")
        return

    print(f"🔄 Replaying signals from {DLQ_PATH}...")
    
    replayed_count = 0
    with open(DLQ_PATH, 'r') as f_in, open(QUEUE_PATH, 'a') as f_out:
        for line in f_in:
            try:
                entry = json.loads(line)
                # Extract the original signal event from the DLQ wrapper
                original_signal = entry.get("original_event")
                if original_signal:
                    f_out.write(json.dumps(original_signal) + '\n')
                    replayed_count += 1
            except Exception as e:
                print(f"❌ Error parsing DLQ line: {e}")

    # Archive the current DLQ before clearing
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_path = BASE_STORAGE / f"dlq_archive_{timestamp}.jsonl"
    shutil.copy(DLQ_PATH, archive_path)
    
    # Clear DLQ
    open(DLQ_PATH, 'w').close()
    print(f"🚀 Replayed {replayed_count} signals. DLQ archived to {archive_path.name}")

if __name__ == "__main__":
    replay_dlq()
