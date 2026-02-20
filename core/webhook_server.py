from flask import Flask, request, jsonify
from storage.jsonl_queue import append_jsonl
import uuid
import datetime

app = Flask(__name__)
QUEUE_PATH = "storage/tradingview_signals_queue.jsonl"

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    # 1. Get JSON payload from TradingView
    data = request.get_json()
    
    if not data:
        return jsonify({"error": "No data received"}), 400

    # 2. Logic to support Idempotency (Task 3 & 4)
    # Check if signal_id is already provided in the request
    # Otherwise, generate a new one
    incoming_signal_id = data.get("signal_id")
    final_signal_id = incoming_signal_id if incoming_signal_id else str(uuid.uuid4())

    # 3. Enrich the signal with metadata
    signal = {
        "signal_id": final_signal_id,
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
        "payload": data.get("payload", data) # Use nested payload if exists, else raw data
    }
    
    # 4. Write to the queue atomically
    try:
        append_jsonl(QUEUE_PATH, signal)
        return jsonify({"status": "success", "signal_id": signal["signal_id"]}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)