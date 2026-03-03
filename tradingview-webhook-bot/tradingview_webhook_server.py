import sys
import os
import uuid
import logging
import sqlite3
import pandas as pd
import requests
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

from tradingview_webhook_bot.storage.jsonl_queue import append_jsonl
from tradingview_webhook_bot.schemas import TradingViewPayload, SignalEvent, SignalStatus

# Production Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("WEBHOOK_SERVER")

# --- 3. TELEGRAM ALERT HELPER ---
def send_telegram_notification(strat_id, symbol, side, qty, price, signal_id, indicator="N/A"):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return

    side_upper = side.upper()
    if "BUY" in side_upper: emoji = "🟢"
    elif "TP" in side_upper or "EXIT" in side_upper: emoji = "🎯"
    else: emoji = "🔴"

    message = (
        f"{emoji} **Bot Alert ({strat_id})**\n\n"
        f"✅ **Executed:** {side_upper} {symbol}\n"
        f"💰 **Price:** {price}\n"
        f"📊 **Indicator:** {indicator}\n"
        f"📦 **Qty:** {qty}\n"
        f"🆔 **ID:** `{signal_id}`"
    )

    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        logger.error(f"❌ Telegram Send Failed: {e}")

# --- 4. DATABASE LOGGER HELPER (Fix: Using Validated Object) ---
def log_event_to_db(signal_id, payload: TradingViewPayload):
    """Saves validated signal data into SQLite."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Extracting from Pydantic Object
        strat_id = payload.strategy_id or payload.strategy
        symbol = payload.symbol
        side = payload.action.upper()
        qty = payload.quantity
        price = payload.price
        indicator = payload.indicator
        
        # We can pass run_id in raw_data if needed, otherwise default
        run_id = "LIVE_SESSION"

        cursor.execute("INSERT OR IGNORE INTO strategies (id, name) VALUES (?, ?)", (strat_id, strat_id))
        cursor.execute("INSERT OR IGNORE INTO runs (id, strategy_id, symbol, mode) VALUES (?, ?, ?, 'FORWARD')",
                       (run_id, strat_id, symbol))

        cursor.execute('''INSERT INTO trades (run_id, timestamp, side, qty, price)
                          VALUES (?, ?, ?, ?, ?)''',
                       (run_id, datetime.now(timezone.utc).isoformat(), side, qty, price))

        conn.commit()
        conn.close()

        # Trigger Telegram
        send_telegram_notification(strat_id, symbol, side, qty, price, signal_id, indicator)
        logger.info(f"💾 DB & Telegram Success: {strat_id} | {side} {symbol}")
    except Exception as e:
        logger.error(f"⚠️ Logging Failed: {e}")

def create_app(config=None):
    app = Flask(__name__)

    @app.route('/health', methods=['GET'])
    def health():
        return jsonify({"status": "healthy", "version": "1.2.1", "db_found": os.path.exists(DB_PATH)}), 200

    @app.route('/webhook/tradingview', methods=['POST'])
    def webhook():
        webhook_secret = os.getenv("WEBHOOK_SECRET", "default_secret")
        queue_path = os.getenv("QUEUE_PATH", "storage/signals.jsonl")

        raw_data = request.get_json()
        if not raw_data: return jsonify({"error": "No JSON"}), 400

        auth_payload = raw_data.get("secret")
        if auth_payload != webhook_secret:
            return jsonify({"error": "Unauthorized"}), 401

        try:
            # 1. Validation
            validated_payload = TradingViewPayload(**raw_data)
            
            ts = datetime.now(timezone.utc)
            signal_id = f"TV-{ts.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"

            # 2. Schema compliance
            event = SignalEvent(
                signal_id=signal_id,
                timestamp=ts,
                payload=validated_payload,
                status=SignalStatus.RECEIVED
            )

            # 3. Enqueue
            if append_jsonl(queue_path, event.model_dump(mode='json')):
                # Fix: Passing the validated object instead of raw dict
                log_event_to_db(signal_id, validated_payload)
                return jsonify({"status": "success", "signal_id": signal_id}), 202
            else:
                raise IOError("Queue write failed")

        except ValidationError as e:
            return jsonify({"error": "Validation Failed", "details": e.errors()}), 422
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
