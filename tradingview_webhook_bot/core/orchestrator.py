import time, logging, os, json, sys
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

# --- 1. PATH RESOLUTION & ENV LOAD ---
CORE_DIR = Path(__file__).resolve().parent
BASE_DIR = CORE_DIR.parent # This is ~/tradingview_webhook_bot/tradingview_webhook_bot

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Production secrets path
ENV_VARS_PATH = "/etc/tradingbot/env_vars"
if os.path.exists(ENV_VARS_PATH):
    load_dotenv(dotenv_path=ENV_VARS_PATH)
else:
    load_dotenv(dotenv_path=BASE_DIR.parent / ".env")

# --- 2. LOGGING CONFIGURATION ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Direct Imports
try:
    from storage.idempotency_store import IdempotencyStore
    from core.schemas import SignalPayload
    from storage.sheets_logger import GoogleSheetsLogger
    from storage.jsonl_consumer import JsonlOffsetConsumer
    from ledger.positions import PositionLedger
    from alerts.router import AlertRouter
    from recon.reconciler import Reconciler
    from exchange.binance_client import BinanceClient
except ImportError as e:
    logger.error(f"❌ Import failed: {e}. Attempting fallback...")
    from tradingview_webhook_bot.storage.idempotency_store import IdempotencyStore
    from tradingview_webhook_bot.core.schemas import SignalPayload
    from tradingview_webhook_bot.storage.sheets_logger import GoogleSheetsLogger
    from tradingview_webhook_bot.storage.jsonl_consumer import JsonlOffsetConsumer
    from tradingview_webhook_bot.ledger.positions import PositionLedger
    from tradingview_webhook_bot.alerts.router import AlertRouter
    from tradingview_webhook_bot.recon.reconciler import Reconciler
    from tradingview_webhook_bot.exchange.binance_client import BinanceClient

class Orchestrator:
    def __init__(self):
        self.allow_real = os.getenv("ALLOW_REAL_TRADES", "false").lower() == "true"
        self.run_mode = os.getenv("RUN_MODE", "production")

        storage_dir = Path("/home/ubuntu/tradingview_webhook_bot/tradingview_webhook_bot/storage")
        storage_dir.mkdir(parents=True, exist_ok=True)

        self.dlq_path = str(storage_dir / "dead_letter.jsonl")
        self.idempotency_db = os.getenv("IDEMPOTENCY_DB_PATH") or str(storage_dir / "idempotency.db")
        self.ledger_path = os.getenv("LEDGER_PATH") or str(storage_dir / "ledger_state.json")
        self.alerts_log = os.getenv("ALERTS_LOG") or str(storage_dir / "alerts.jsonl")
        self.queue_path = os.getenv("QUEUE_PATH") or str(storage_dir / "signals.jsonl")
        self.offset_path = os.getenv("OFFSET_PATH") or str(storage_dir / "signals.offset")

        self.processed_count = 0
        self.last_heartbeat = time.time()
        self.dlq_threshold_count = int(os.getenv("DLQ_THRESHOLD", "5"))
        self.dlq_threshold_window = int(os.getenv("DLQ_WINDOW_SECONDS", "60"))
        self.recent_failures = []

        # Init Components
        self.ledger = PositionLedger(self.ledger_path)
        self.alerts = AlertRouter(self.alerts_log)
        self.reconciler = Reconciler(self.ledger)
        self.sheets_logger = GoogleSheetsLogger()
        self.consumer = JsonlOffsetConsumer(self.queue_path, self.offset_path)
        self.exchange = BinanceClient()
        self.idempotency = IdempotencyStore(self.idempotency_db)

    def get_dlq_size(self):
        try:
            if not os.path.exists(self.dlq_path): return 0
            with open(self.dlq_path, "r") as f:
                return sum(1 for line in f if line.strip())
        except: return 0

    def handle_signal(self, event: dict) -> bool:
        """Core signal handler with Adaptive Symbol Security and Schema Validation."""
        try:
            signal_id = event.get("signal_id")
            if self.idempotency.is_seen(signal_id):
                logger.info(f"⏭️ Skipping already processed signal: {signal_id}")
                return True

            payload_raw = event.get("payload", {})
            
            # 🛡️ 1. SCHEMA VALIDATION & CLEANING
            try:
                # Fallback for missing action/quantity in raw signals
                if not payload_raw.get("action"):
                    indicator = str(payload_raw.get("indicator", "")).upper()
                    payload_raw["action"] = "BUY" if "BULL" in indicator or "LONG" in indicator else "SELL"
                
                if not payload_raw.get("quantity"):
                    payload_raw["quantity"] = 0.003 # Safe default for $100 notional

                valid_payload = SignalPayload(**payload_raw)
                payload = valid_payload.model_dump()
            except Exception as schema_err:
                logger.error(f"❌ Schema Validation Failed: {schema_err}")
                self.move_to_dlq(event, f"Schema Error: {schema_err}")
                return True

            # 🛡️ 2. ADAPTIVE SYMBOL SECURITY (Forever Fix)
            # Binance Testnet/Mainnet uses USDT pairs for USDT balance
            raw_symbol = str(payload.get("symbol", "")).upper()
            
            if "USDT" not in raw_symbol:
                if "BTC" in raw_symbol:
                    symbol = "BTCUSDT"
                elif "ETH" in raw_symbol:
                    symbol = "ETHUSDT"
                elif "SOL" in raw_symbol:
                    symbol = "SOLUSDT"
                else:
                    # Strip common suffixes and force USDT
                    clean_name = raw_symbol.replace("USD", "").replace("H2026", "").replace(".P", "")
                    symbol = f"{clean_name}USDT"
            else:
                symbol = raw_symbol

            logger.info(f"🔄 Routing Signal: {raw_symbol} -> {symbol}")

            # 3. EXTRACTION
            original_action = payload.get("action", "").upper()
            side = "SELL" if original_action in ["SELL", "TP", "EXIT", "SHORT"] else "BUY"
            qty = float(payload.get("quantity", 0))
            price = float(payload.get("price", 0))
            strat_id = payload.get("strategy_id") or payload.get("strategy") or "Bot"

            # 4. EXECUTION
            execution_res = self.exchange.execute_futures_order(symbol, side, qty, price, signal_id=signal_id)
            
            if execution_res.get("status") == "SUCCESS":
                client_oid = execution_res.get("order_id", "manual")
                self.idempotency.mark_seen(signal_id, client_order_id=client_oid)
                
                self.processed_count += 1
                self.ledger.apply_fill(symbol, side, qty, price)
                self.sheets_logger.log_trade(symbol=symbol, action=side, qty=qty, price=price, strategy=strat_id)
                
                emoji = "🟢" if side == "BUY" else "🔴"
                self.alerts.send(f"{emoji} Trade Executed: {side} {symbol} @ {price}", channel="TRADES")
                return True
            else:
                reason = execution_res.get("reason", "unknown_api")
                logger.error(f"❌ Execution Failed: {symbol} - {reason}")
                self.move_to_dlq(event, f"Exchange Failure: {reason}")
                return True

        except Exception as e:
            logger.error(f"❌ Critical Failure: {e}")
            self.move_to_dlq(event, str(e))
            return True

    def move_to_dlq(self, event: dict, error_msg: str):
        try:
            now = datetime.now()
            dlq_entry = {"timestamp": now.isoformat(), "error": error_msg, "original_event": event}
            with open(self.dlq_path, "a") as f:
                f.write(json.dumps(dlq_entry) + "\n")
            logger.warning(f"⚠️ Signal moved to DLQ: {error_msg}")
        except Exception as dlq_err:
            logger.critical(f"🔥 DLQ WRITE FAILURE: {dlq_err}")

    def run(self):
        logger.info(f"🚀 Engine Live | Mode: {self.run_mode} | Real: {self.allow_real}")
        last_recon = time.time()
        while True:
            self.consumer.poll(handler=self.handle_signal, batch_size=5)
            current_time = time.time()
            if current_time - self.last_heartbeat > 900:
                logger.info(f"💓 Heartbeat | Processed: {self.processed_count} | DLQ: {self.get_dlq_size()}")
                self.last_heartbeat = current_time
            if current_time - last_recon > 1800:
                try:
                    exchange_data = self.exchange.get_audit_data()
                    self.reconciler.reconcile_with_exchange(exchange_data)
                except Exception as e: 
                    logger.error(f"Recon Error: {e}")
                last_recon = current_time
            time.sleep(1)

if __name__ == "__main__":
    orchestrator = Orchestrator()
    orchestrator.run()
