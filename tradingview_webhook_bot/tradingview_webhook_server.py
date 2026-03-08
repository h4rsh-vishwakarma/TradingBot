import os, json, logging, time
from flask import Flask, request, jsonify
from datetime import datetime

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WEBHOOK_SERVER")

app = Flask(__name__)

# Secret key for validation
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "squeeze_tradingview_cluster_2026_secure")
# Database path
DB_PATH = os.path.join(os.getcwd(), 'storage/trading_system.db')

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy", "db_found": os.exists(os.path.dirname(DB_PATH)) if os.path.dirname(DB_PATH) else True}), 200

@app.route('/webhook/tradingview', methods=['POST'])
def webhook():
    data = request.get_json()
    if not data or data.get("secret") != WEBHOOK_SECRET:
        return jsonify({"status": "unauthorized"}), 401

    signal_id = f"TV-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{os.urandom(4).hex()}"
    
    # Save to signals.jsonl (The Queue for Orchestrator)
    queue_data = {
        "signal_id": signal_id,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "status": "received",
        "payload": data
    }
    
    try:
        with open('storage/signals.jsonl', 'a') as f:
            f.write(json.dumps(queue_data) + '\n')
        logger.info(f"✅ Signal Queued: {signal_id}")
        return jsonify({"status": "success", "signal_id": signal_id}), 202
    except Exception as e:
        logger.error(f"❌ Failed to queue signal: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
