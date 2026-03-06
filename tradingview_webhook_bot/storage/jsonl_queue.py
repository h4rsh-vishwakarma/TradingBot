import json
import os
import threading

def append_jsonl(file_path, data):
    """Utility function expected by the webhook server"""
    lock = threading.Lock()
    with lock:
        with open(file_path, 'a') as f:
            f.write(json.dumps(data) + '\n')

class AtomicJsonlQueue:
    def __init__(self, file_path):
        self.file_path = file_path
        self.lock = threading.Lock()

    def enqueue(self, data):
        append_jsonl(self.file_path, data)

    def dequeue_all(self):
        with self.lock:
            if not os.path.exists(self.file_path):
                return []
            with open(self.file_path, 'r') as f:
                lines = f.readlines()
            open(self.file_path, 'w').close()
            return [json.loads(line) for line in lines if line.strip()]
