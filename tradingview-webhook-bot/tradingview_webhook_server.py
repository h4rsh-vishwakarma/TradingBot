import sys
import os
import uuid
import logging
import sqlite3
from pathlib import Path
from flask import Flask, request, jsonify
from datetime import datetime, timezone
from pydantic import ValidationError
from dotenv import load_dotenv

# --- 1. ENVIRONMENT LOAD ---
load_dotenv()

# --- 2. PATH RESOLUTION ---
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Database Path
DB_PATH = os.path.join(ROOT_DIR, 'storage/trading_system.db')

# Internal imports
from tradingview_webhook_bot.storage.jsonl_queue import append_jsonl
from tradingview_webhook_bot.schemas import TradingViewPayload, SignalEvent, SignalStatus

# Logging Config
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- NEW: DATABASE LOGGER FUNCTION ---
def log_event_to_db(signal_id, payload_dict):
    """Logs the received signal into the analytics database for Day 1 QBA."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        strategy_id = payload_dict.get("strategy_id", "Default_Strategy")
        symbol = payload_dict.get("symbol", "Unknown")
        side = payload_dict.get("action", "Unknown").upper()
        qty = float(payload_dict.get("quantity", 0))
        price = float(payload_dict.get("price", 0))

        # Ensure strategy and run entry exists
        cursor.execute("INSERT OR IGNORE INTO strategies (id, name) VALUES (?, ?)", (strategy_id, strategy_id))
        cursor.execute("INSERT OR IGNORE INTO runs (id, strategy_id, symbol, mode) VALUES (?, ?, ?, 'FORWARD')", 
                       ("LIVE_SESSION", strategy_id, symbol))

        # Record the 'intent' in trades table (marked as a signal received)
        cursor.execute('''INSERT INTO trades (run_id, timestamp, side, qty, price) 
                          VALUES (?, ?, ?, ?, ?)''', 
                       ("LIVE_SESSION", datetime.now(timezone.utc).isoformat(), side, qty, price))
        
        conn.commit()
        conn.close()
        logger.info(f"💾 Signal {signal_id} logged to database.")
    except Exception as e:
        logger.error(f"⚠️ DB Logging Error: {e}")

def create_app(config=None):
    app = Flask(__name__)
    app.config.update(config or {})

    @app.route('/health', methods=['GET'])
    def health():
        return jsonify({
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": "1.1.4" # Incremented version
        }), 200

    @app.route('/webhook/tradingview', methods=['POST'])
    def webhook():
        webhook_secret = os.getenv("WEBHOOK_SECRET", "default_secret")
        queue_path = os.getenv("QUEUE_PATH", "storage/signals.jsonl")

        raw_data = request.get_json()
        if not raw_data:
            return jsonify({"error": "No JSON payload received"}), 400

        auth_header = request.headers.get("X-Webhook-Secret")
        auth_payload = raw_data.get("secret")

        if not (auth_header == webhook_secret or auth_payload == webhook_secret):
            logger.warning(f"Unauthorized access attempt from {request.remote_addr}")
            return jsonify({"error": "Unauthorized"}), 401

        try:
            # 1. Schema Validation
            validated_payload = TradingViewPayload(**raw_data)

            # 2. Unique Signal ID and Timestamp
            ts = datetime.now(timezone.utc)
            signal_id = f"TV-{ts.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"

            event = SignalEvent(
                signal_id=signal_id,
                timestamp=ts,
                payload=validated_payload,
                status=SignalStatus.RECEIVED 
            )

            # 3. Persistence to JSONL Queue (Current logic)
            success = append_jsonl(queue_path, event.model_dump(mode='json'))

            if success:
                # 4. NEW: LOG TO DATABASE FOR ANALYTICS
                log_event_to_db(signal_id, raw_data)
                
                logger.info(f"✅ Signal Recorded: {signal_id} | Symbol: {validated_payload.symbol}")
                return jsonify({
                    "status": "success",
                    "signal_id": signal_id,
                    "timestamp": ts.isoformat()
                }), 202
            else:
                raise IOError(f"Failed to write to {queue_path}")

        except ValidationError as e:
            logger.warning(f"❌ Schema Mismatch: {e.json()}")
            return jsonify({"error": "Validation Failed", "details": e.errors()}), 422
        except Exception as e:
            logger.error(f"❌ Internal Failure: {str(e)}")
            return jsonify({"error": "Internal Server Error"}), 500

    return app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
