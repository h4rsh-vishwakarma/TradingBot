import threading
import os
import json
from storage.jsonl_queue import append_jsonl, read_jsonl

# Configuration
TEST_QUEUE = "storage/test_stress_queue.jsonl"
THREAD_COUNT = 100

def worker(thread_id):
    """Worker function to simulate a webhook signal write."""
    record = {
        "thread_id": thread_id,
        "signal": "STRESS_TEST",
        "data": "A" * 100  # Small payload to test stability
    }
    append_jsonl(TEST_QUEUE, record)

def run_stress_test():
    # 1. Clean up old test file if it exists
    if os.path.exists(TEST_QUEUE):
        os.remove(TEST_QUEUE)

    print(f"🚀 Starting stress test with {THREAD_COUNT} concurrent threads...")
    
    threads = []
    for i in range(THREAD_COUNT):
        t = threading.Thread(target=worker, args=(i,))
        threads.append(t)

    # 2. Start all threads simultaneously
    for t in threads:
        t.start()

    # 3. Wait for all threads to finish
    for t in threads:
        t.join()

    # 4. Verification
    results = read_jsonl(TEST_QUEUE)
    print(f"\n--- Verification ---")
    print(f"Expected Lines: {THREAD_COUNT}")
    print(f"Actual Lines:   {len(results)}")

    if len(results) == THREAD_COUNT:
        print("✅ PASS: All concurrent writes were successful and atomic!")
    else:
        print("❌ FAIL: Data corruption or loss detected.")

if __name__ == "__main__":
    run_stress_test()