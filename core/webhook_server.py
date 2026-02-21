from flask import Flask, request, jsonify
from storage.jsonl_queue import append_jsonl
import uuid
import datetime
import os
import json
import time

app = Flask(__name__)
QUEUE_PATH = "storage/tradingview_signals_queue.jsonl"
HEARTBEAT_PATH = "state/bot_heartbeat.json"

# Global variable to track the last signal received
last_received_timestamp = "N/A"

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    global last_received_timestamp
    data = request.get_json()
    
    if not data:
        return jsonify({"error": "No data received"}), 400

    incoming_signal_id = data.get("signal_id")
    final_signal_id = incoming_signal_id if incoming_signal_id else str(uuid.uuid4())

    last_received_timestamp = datetime.datetime.now(datetime.UTC).isoformat()

    signal = {
        "signal_id": final_signal_id,
        "timestamp": last_received_timestamp,
        "payload": data.get("payload", data)
    }
    
    try:
        append_jsonl(QUEUE_PATH, signal)
        return jsonify({"status": "success", "signal_id": signal["signal_id"]}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """
    Subtask 7.1: Enhanced health check.
    Checks queue size, last signal, and Signal Processor heartbeat.
    """
    # 1. Get Heartbeat Info
    processor_alive = False
    heartbeat_data = {}
    
    if os.path.exists(HEARTBEAT_PATH):
        try:
            with open(HEARTBEAT_PATH, "r") as f:
                heartbeat_data = json.load(f)
                # If heartbeat is less than 60s old, consider processor alive
                if time.time() - heartbeat_data.get("last_heartbeat", 0) < 60:
                    processor_alive = True
        except Exception:
            processor_alive = False

    # 2. Build Response
    stats = {
        "status": "ok" if processor_alive else "degraded",
        "service": "tradingview_webhook",
        "version": "1.0.0",
        "queue": {
            "path": QUEUE_PATH,
            "size_bytes": os.path.getsize(QUEUE_PATH) if os.path.exists(QUEUE_PATH) else 0,
        },
        "signals": {
            "last_signal_ts": last_received_timestamp,
        },
        "processor": {
            "is_alive": processor_alive,
            "last_heartbeat": heartbeat_data.get("last_heartbeat", "N/A"),
            "pid": heartbeat_data.get("pid", "N/A")
        }
    }
    
    # Return 200 if OK, 503 if Processor is down
    status_code = 200 if processor_alive else 503
    return jsonify(stats), status_code

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)