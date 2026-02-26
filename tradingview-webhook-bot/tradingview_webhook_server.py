import sys
import os
import uuid
import logging
from pathlib import Path
from flask import Flask, request, jsonify
from datetime import datetime, timezone
from pydantic import ValidationError

# --- PATH FIX START ---
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
# --- PATH FIX END ---

# Import validated storage and new schemas
from tradingview_webhook_bot.storage.jsonl_queue import append_jsonl
from schemas.models import TradingViewPayload, SignalEvent, SignalStatus

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_app(config=None):
    """
    Application Factory: Support for Production, Testing, and Pydantic Validation.
    """
    app = Flask(__name__)
    app.config.update(config or {})

    @app.route('/health', methods=['GET'])
    def health():
        """Basic health check for Nginx/Uptime monitoring."""
        return jsonify({
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": "1.1.0"
        }), 200

    @app.route('/webhook/tradingview', methods=['POST'])
    def webhook():
        """
        Receives signals, validates via Pydantic, and enqueues.
        """
        # Configuration
        webhook_secret = app.config.get("WEBHOOK_SECRET") or os.getenv("WEBHOOK_SECRET", "default_secret")
        queue_path = app.config.get("QUEUE_PATH") or os.getenv("QUEUE_PATH", "storage/signals.jsonl")

        # 1. Security Check
        auth_token = request.headers.get("X-Webhook-Secret")
        if not auth_token or auth_token != webhook_secret:
            logger.warning(f"Unauthorized access attempt from {request.remote_addr}")
            return jsonify({"error": "Unauthorized"}), 401

        # 2. Raw Data Acquisition
        raw_data = request.get_json()
        if not raw_data:
            return jsonify({"error": "No JSON payload received"}), 400

        try:
            # 3. Pydantic Validation (Canonical Schema)
            # This handles type checking, value constraints (qty > 0), and normalization
            validated_payload = TradingViewPayload(**raw_data)

            # 4. Signal ID & Event Generation
            ts = datetime.now(timezone.utc)
            signal_id = f"TV-{ts.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
            
            event = SignalEvent(
                signal_id=signal_id,
                timestamp=ts,
                payload=validated_payload,
                status=SignalStatus.RECEIVED
            )

            # 5. Atomic Enqueue
            # We use model_dump() to convert the Pydantic object to a serializable dict
            success = append_jsonl(queue_path, event.model_dump(mode='json'))

            if success:
                logger.info(f"✅ Signal Validated & Enqueued: {signal_id} | Symbol: {validated_payload.symbol}")
                return jsonify({
                    "status": "enqueued",
                    "signal_id": signal_id,
                    "timestamp": ts.isoformat()
                }), 202
            else:
                raise IOError(f"Could not write to {queue_path}")

        except ValidationError as e:
            # Returns 422 Unprocessable Entity for schema mismatches
            logger.warning(f"❌ Validation Failed for request from {request.remote_addr}: {e.json()}")
            return jsonify({
                "error": "Validation Failed",
                "details": e.errors()
            }), 422
            
        except Exception as e:
            logger.error(f"❌ System Error: {str(e)}")
            return jsonify({"error": "Internal Server Error"}), 500

    return app



