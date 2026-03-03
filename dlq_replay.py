import os
from pathlib import Path

DLQ_PATH = Path("storage/dead_letter.jsonl")
QUEUE_PATH = Path("storage/signals.jsonl")

def replay_dlq():
    if not DLQ_PATH.exists() or os.path.getsize(DLQ_PATH) == 0:
        print("ℹ️ Nothing to replay. DLQ is empty.")
        return

    # Read all failed signals
    with open(DLQ_PATH, 'r') as f:
        failed_entries = f.readlines()

    # Append to main queue
    with open(QUEUE_PATH, 'a') as f:
        for entry in failed_entries:
            f.write(entry)

    # Clear DLQ after replay
    open(DLQ_PATH, 'w').close()
    print(f"🚀 Replayed {len(failed_entries)} signals to main queue and cleared DLQ.")

if __name__ == "__main__":
    replay_dlq()

