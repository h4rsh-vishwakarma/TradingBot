import sys
import os
import uuid
import logging
import sqlite3
import pandas as pd
from pathlib import Path
from flask import Flask, request, jsonify
from datetime import datetime, timezone
from pydantic import ValidationError
from dotenv import load_dotenv

# --- 1. ENVIRONMENT LOAD ---
load_dotenv()

# --- 2. PATH RESOLUTION (Senior Standard) ---
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Database Path
DB_PATH = os.path.join(ROOT_DIR, 'storage/trading_system.db')

try:
    import tradingview_webhook_bot
except ImportError:
    import importlib.util
    folder_path = ROOT_DIR / "tradingview-webhook-bot"
    if folder_path.exists():
        spec = importlib.util.spec_from_file_location(
            "tradingview_webhook_bot",
            str(folder_path / "__init__.py")
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["tradingview_webhook_bot"] = module
        spec.loader.exec_module(module)

# Core internal imports
from tradingview_webhook_bot.storage.jsonl_queue import append_jsonl
from tradingview_webhook_bot.schemas import TradingViewPayload, SignalEvent, SignalStatus

# Production Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("WEBHOOK_SERVER")

# --- 3. DATABASE LOGGER HELPER ---
def log_event_to_db(signal_id, payload_dict):
    """Saves webhook signal data into SQLite for performance tracking."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        strat_id = payload_dict.get("strategy_id", "Default_Strategy")
        symbol = payload_dict.get("symbol", "Unknown")
        side = payload_dict.get("action", "Unknown").upper()
        qty = float(payload_dict.get("quantity", 0))
        price = float(payload_dict.get("price", 0))
        run_id = payload_dict.get("run_id", "LIVE_SESSION")

        cursor.execute("INSERT OR IGNORE INTO strategies (id, name) VALUES (?, ?)", (strat_id, strat_id))
        cursor.execute("INSERT OR IGNORE INTO runs (id, strategy_id, symbol, mode) VALUES (?, ?, ?, 'FORWARD')", 
                       (run_id, strat_id, symbol))

        cursor.execute('''INSERT INTO trades (run_id, timestamp, side, qty, price) 
                          VALUES (?, ?, ?, ?, ?)''', 
                       (run_id, datetime.now(timezone.utc).isoformat(), side, qty, price))
        
        conn.commit()
        conn.close()
        logger.info(f"💾 DB Log Success: {strat_id} | {side} {symbol}")
    except Exception as e:
        logger.error(f"⚠️ DB Logging Failed: {e}")

def create_app(config=None):
    app = Flask(__name__)
    app.config.update(config or {})

    @app.route('/health', methods=['GET'])
    def health():
        return jsonify({
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": "1.1.5",
            "db_found": os.path.exists(DB_PATH)
        }), 200

    # --- DAY 3: ANALYTICS ENDPOINTS ---
    @app.route('/analytics/summary', methods=['GET'])
    def get_summary():
        """Returns strategy performance summary from DB."""
        try:
            conn = sqlite3.connect(DB_PATH)
            query = """
            SELECT r.strategy_id, r.symbol, r.mode, 
                   COUNT(t.id) as total_signals, 
                   SUM(t.pnl) as realized_pnl
            FROM trades t
            JOIN runs r ON t.run_id = r.id
            GROUP BY r.strategy_id
            """
            df = pd.read_sql_query(query, conn)
            conn.close()
            return jsonify(df.to_dict(orient='records')), 200
        except Exception as e:
            logger.error(f"Analytics Error: {e}")
            return jsonify({"error": str(e)}), 500

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
            validated_payload = TradingViewPayload(**raw_data)
            ts = datetime.now(timezone.utc)
            signal_id = f"TV-{ts.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"

            event = SignalEvent(
                signal_id=signal_id,
                timestamp=ts,
                payload=validated_payload,
                status=SignalStatus.RECEIVED
            )

            success = append_jsonl(queue_path, event.model_dump(mode='json'))

            if success:
                # SQL Logging integration
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

# Gunicorn entry point
app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
