import json
import os
from pathlib import Path

DLQ_PATH = Path("storage/dead_letter.jsonl")

def inspect_dlq():
    if not DLQ_PATH.exists() or os.path.getsize(DLQ_PATH) == 0:
        print("✅ Dead Letter Queue is empty. No failed signals found.")
        return

    print(f"🔍 Inspecting DLQ: {DLQ_PATH}\n")
    with open(DLQ_PATH, 'r') as f:
        for i, line in enumerate(f, 1):
            try:
                data = json.loads(line)
                error = data.get('error', 'Unknown Error')
                signal = data.get('signal', {})
                timestamp = data.get('timestamp', 'N/A')
                
                print(f"--- [Failure #{i}] ---")
                print(f"⏰ Time: {timestamp}")
                print(f"❌ Error: {error}")
                print(f"📦 Signal ID: {signal.get('signal_id', 'N/A')}")
                print(f"📄 Full Signal: {json.dumps(signal, indent=2)}")
                print("-" * 25)
            except Exception as e:
                print(f"⚠️ Could not parse line {i}: {e}")

if __name__ == "__main__":
    inspect_dlq()
