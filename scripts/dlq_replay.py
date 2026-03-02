
import json
import os
import sys
import time
from pathlib import Path

# --- 1. PATH RESOLUTION ---
# Kyunki ye script 'scripts/' folder mein hai, humein ek level up jana hoga 
# taaki 'storage/' folder mil sake.
BASE_DIR = Path(__file__).resolve().parent.parent
QUEUE_PATH = BASE_DIR / "storage" / "signals.jsonl"
DLQ_PATH = BASE_DIR / "storage" / "dlq.jsonl"

def load_dlq():
    """Reads all failed signals from the Dead Letter Queue"""
    if not DLQ_PATH.exists():
        print(f"❌ DLQ file not found at: {DLQ_PATH}")
        return []
    try:
        with open(DLQ_PATH, "r") as f:
            return [json.loads(line) for line in f if line.strip()]
    except Exception as e:
        print(f"❌ Error reading DLQ: {e}")
        return []

def save_dlq(entries):
    """Saves only the non-replayed/skipped entries back to DLQ"""
    try:
        with open(DLQ_PATH, "w") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")
    except Exception as e:
        print(f"❌ Error saving DLQ: {e}")

def replay_signal(entry):
    """Moves the original event back to the main signal queue for the Orchestrator to process"""
    original_event = entry.get("original_event")
    if not original_event:
        print("❌ Invalid entry: No original event found.")
        return False

    # Reset status for re-processing so Orchestrator sees it as 'new'
    original_event["status"] = "received"
    original_event["replay_attempt_ts"] = time.strftime('%Y-%m-%dT%H:%M:%S') # Audit trail

    try:
        # Check if queue path exists, if not create parent dir
        QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        with open(QUEUE_PATH, "a") as f:
            f.write(json.dumps(original_event) + "\n")
        return True
    except Exception as e:
        print(f"❌ Failed to write to main queue: {e}")
        return False

def main():
    print("\n" + "="*40)
    print("🛠️  --- ENTERPRISE DLQ REPLAY TOOL ---  🛠️")
    print("="*40)
    
    entries = load_dlq()

    if not entries:
        print("✅ DLQ is empty. No failed signals to recover.")
        return

    print(f"📋 Found {len(entries)} entries in DLQ.\n")

    remaining_entries = []
    replayed_count = 0
    deleted_count = 0

    for i, entry in enumerate(entries):
        print(f"\n[ENTRY #{i+1}]")
        print(f"⏰ Failed At: {entry.get('timestamp')}")
        print(f"⚠️  Error:     {entry.get('error')}")
        
        payload = entry.get('original_event', {}).get('payload', {})
        symbol = payload.get('symbol', 'UNKNOWN')
        side = payload.get('action', 'UNKNOWN')
        price = payload.get('price', '0')
        
        print(f"📊 Trade:     {side} {symbol} @ {price}")
        print("-" * 20)

        # Prompt for Action
        choice = input(f"Action? [y] Replay, [n] Keep in DLQ, [d] Delete permanently: ").lower().strip()

        if choice == 'y':
            if replay_signal(entry):
                print(f"🚀 SUCCESS: Signal re-enqueued for Orchestrator.")
                replayed_count += 1
            else:
                remaining_entries.append(entry)
        elif choice == 'd':
            print("🗑️  DELETED: Signal removed from system.")
            deleted_count += 1
        else:
            print("⏭️  SKIPPED: Entry remains in DLQ for later review.")
            remaining_entries.append(entry)

    # Final cleanup: Write only what wasn't replayed or deleted
    save_dlq(remaining_entries)
    
    print("\n" + "="*40)
    print(f"✨ SUMMARY:")
    print(f"✅ Replayed:  {replayed_count}")
    print(f"🗑️  Deleted:   {deleted_count}")
    print(f"📦 Remaining: {len(remaining_entries)}")
    print("="*40 + "\n")

if __name__ == "__main__":
    main()
