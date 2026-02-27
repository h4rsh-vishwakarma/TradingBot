import json
import os
import sys
from pathlib import Path

# Path Resolution
BASE_DIR = Path(__file__).resolve().parent.parent
QUEUE_PATH = BASE_DIR / "storage" / "signals.jsonl"
DLQ_PATH = BASE_DIR / "storage" / "dlq.jsonl"

def load_dlq():
    if not DLQ_PATH.exists():
        print("❌ DLQ file not found.")
        return []
    with open(DLQ_PATH, "r") as f:
        return [json.loads(line) for line in f if line.strip()]

def save_dlq(entries):
    with open(DLQ_PATH, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")

def replay_signal(entry):
    """Moves the original event back to the main signal queue"""
    original_event = entry.get("original_event")
    if not original_event:
        print("❌ Invalid entry: No original event found.")
        return False
    
    # Reset status for re-processing
    original_event["status"] = "received"
    original_event["replay_ts"] = entry.get("timestamp") # Audit trail
    
    with open(QUEUE_PATH, "a") as f:
        f.write(json.dumps(original_event) + "\n")
    return True

def main():
    print("🛠️ --- DLQ Replay Tool --- 🛠️")
    entries = load_dlq()
    
    if not entries:
        print("✅ DLQ is empty. Nothing to replay.")
        return

    print(f"Found {len(entries)} entries in DLQ.\n")
    
    remaining_entries = []
    replayed_count = 0

    for i, entry in enumerate(entries):
        print(f"[{i}] Time: {entry['timestamp']}")
        print(f"    Error: {entry['error']}")
        payload = entry['original_event'].get('payload', {})
        print(f"    Trade: {payload.get('action')} {payload.get('symbol')} @ {payload.get('price')}")
        
        choice = input(f"\nReplay this signal? (y/n/skip): ").lower()
        
        if choice == 'y':
            if replay_signal(entry):
                print(f"✅ Signal re-enqueued successfully!")
                replayed_count += 1
            else:
                remaining_entries.append(entry)
        elif choice == 'n' or choice == 'skip':
            print("⏭️ Entry skipped but remains in DLQ.")
            remaining_entries.append(entry)
        elif choice == 'd':
            print("🗑️ Entry deleted.")
        else:
            remaining_entries.append(entry)
        print("-" * 30)

    # Save remaining entries back to DLQ
    save_dlq(remaining_entries)
    print(f"\nDone! Replayed: {replayed_count} | Remaining in DLQ: {len(remaining_entries)}")

if __name__ == "__main__":
    main()
