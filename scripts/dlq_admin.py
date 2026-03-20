import json
import os
import sys
from pathlib import Path

# Absolute Paths for Production Reliability
DLQ_PATH = "/home/ubuntu/tradingview_webhook_bot/tradingview_webhook_bot/storage/dead_letter.jsonl"
QUEUE_PATH = "/home/ubuntu/tradingview_webhook_bot/tradingview_webhook_bot/storage/signals.jsonl"

def run_admin():
    if not os.path.exists(DLQ_PATH) or os.path.getsize(DLQ_PATH) == 0:
        print("🟢 Dead Letter Queue is empty. No failures found.")
        return

    print("\n🔍 --- DLQ INSPECTOR ---")
    entries = []
    with open(DLQ_PATH, "r") as f:
        for i, line in enumerate(f):
            try:
                data = json.loads(line.strip())
                entries.append(data)
                print(f"[{i}] {data.get('timestamp', 'N/A')} | Error: {data.get('error', 'Unknown')[:60]}")
            except Exception as e:
                print(f"[{i}] Error parsing line: {e}")

    if not entries: 
        print("No valid entries found in DLQ.")
        return

    choice = input("\nEnter index to REPLAY, or 'c' to CLEAR DLQ, or 'q' to quit: ")
    
    if choice.isdigit():
        idx = int(choice)
        if 0 <= idx < len(entries):
            # Extract the original event to put back in the main queue
            signal = entries[idx].get('original_event')
            if signal:
                with open(QUEUE_PATH, "a") as q:
                    q.write(json.dumps(signal) + "\n")
                print(f"🚀 Signal {signal.get('signal_id', 'Unknown')} re-queued successfully!")
            else:
                print("❌ Could not find original event in DLQ entry.")
    
    elif choice.lower() == 'c':
        confirm = input("Are you sure you want to delete all DLQ entries? (y/n): ")
        if confirm.lower() == 'y':
            open(DLQ_PATH, 'w').close() # Truncate file
            print("🚮 DLQ cleared.")

if __name__ == "__main__":
    run_admin()
