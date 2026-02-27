import sys
import os
import uuid
import logging
from pathlib import Path
from flask import Flask, request, jsonify
from datetime import datetime, timezone
from pydantic import ValidationError
from dotenv import load_dotenv

# --- 1. ENVIRONMENT LOAD ---
load_dotenv()

# --- 2. PATH RESOLUTION (Senior Standard) ---
# Handles hyphenated folder names and project root mapping
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

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

# Day 4: Production Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def create_app(config=None):
    app = Flask(__name__)
    app.config.update(config or {})

    @app.route('/health', methods=['GET'])
    def health():
        return jsonify({
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": "1.1.3"
        }), 200

    @app.route('/webhook/tradingview', methods=['POST'])
    def webhook():
        # Day 4: Config Load
        webhook_secret = os.getenv("WEBHOOK_SECRET", "default_secret")
        queue_path = os.getenv("QUEUE_PATH", "storage/signals.jsonl")

        raw_data = request.get_json()
        if not raw_data:
            return jsonify({"error": "No JSON payload received"}), 400

        # Day 4: Security Verification (Header + Payload)
        auth_header = request.headers.get("X-Webhook-Secret")
        auth_payload = raw_data.get("secret")

        if not (auth_header == webhook_secret or auth_payload == webhook_secret):
            logger.warning(f"Unauthorized access attempt from {request.remote_addr}")
            return jsonify({"error": "Unauthorized"}), 401

        try:
            # 1. Schema Validation (Matches your Pydantic model)
            validated_payload = TradingViewPayload(**raw_data)

            # 2. Unique Signal ID and Timestamp Generation
            ts = datetime.now(timezone.utc)
            signal_id = f"TV-{ts.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"

            # --- SCHEMA COMPLIANCE FIX ---
            # Using 'received' to match your Pydantic Enum constraints
            event = SignalEvent(
                signal_id=signal_id,
                timestamp=ts,
                payload=validated_payload,
                status=SignalStatus.RECEIVED  # Fixed: Match strictly with schemas.py
            )

            # 3. Persistence to JSONL Queue
            success = append_jsonl(queue_path, event.model_dump(mode='json'))

            if success:
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
