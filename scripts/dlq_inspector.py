import json
import os
from pathlib import Path

# Path configuration using project root
DLQ_PATH = Path("storage/dead_letter.jsonl")

def inspect_dlq():
    """
    Analyzes failed signals in the Dead Letter Queue.
    Fixes the 'original_event' nesting issue for accurate analysis.
    """
    if not DLQ_PATH.exists() or os.path.getsize(DLQ_PATH) == 0:
        print("✅ Dead Letter Queue is empty. No failed signals found.")
        return

    print(f"🔍 Inspecting DLQ: {DLQ_PATH}")
    print("=" * 40)
    
    with open(DLQ_PATH, 'r') as f:
        for i, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                
                # Metadata extraction
                error = data.get('error', 'Unknown Error')
                timestamp = data.get('timestamp', 'N/A')
                
                # Data extraction from nested structure
                # Note: Orchestrator moves signals to DLQ under 'original_event' key
                event = data.get('original_event', {})
                signal_id = event.get('signal_id', 'N/A')
                payload = event.get('payload', {})
                
                print(f"📍 FAILURE #{i}")
                print(f"⏰ Timestamp : {timestamp}")
                print(f"❌ Error Log : {error}")
                print(f"🆔 Signal ID : {signal_id}")
                print(f"📦 Strategy  : {payload.get('strategy', 'N/A')}")
                print(f"📊 Action    : {payload.get('action', 'N/A')} {payload.get('quantity', 0)} {payload.get('symbol', 'N/A')}")
                print("-" * 40)
                
            except Exception as e:
                print(f"⚠️ Error parsing Line {i}: {e}")

if __name__ == "__main__":
    inspect_dlq()
