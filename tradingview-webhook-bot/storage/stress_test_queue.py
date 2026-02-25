import time
import threading
import os
from datetime import datetime
from collections import Counter
from tradingview_webhook_bot.storage.jsonl_queue import AtomicJsonlQueue

def run_stress_test():
    test_queue_path = "storage/stress_test.jsonl"
    if os.path.exists(test_queue_path):
        os.remove(test_queue_path)

    queue = AtomicJsonlQueue(test_queue_path)
    
    def writer(thread_id, count):
        for i in range(count):
            record = {
                'thread': thread_id,
                'index': i,
                'timestamp': datetime.utcnow().isoformat()
            }
            queue.append(record)
            time.sleep(0.001)

    print("🧪 Starting Stress Test: 10 threads writing 100 records each...")
    threads = []
    for tid in range(10):
        t = threading.Thread(target=writer, args=(tid, 100))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    records = queue.read_all()
    print(f"✅ Total records written: {len(records)} (Expected: 1000)")
    
    counts = Counter(r['thread'] for r in records)
    print(f"📊 Distribution: {dict(counts)}")

if __name__ == "__main__":
    run_stress_test()
