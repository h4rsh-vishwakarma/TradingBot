import time, logging, os, json, sys, smtplib
from datetime import datetime, timedelta
from pathlib import Path
from email.mime.text import MIMEText
from dotenv import load_dotenv

# --- 1. PATH RESOLUTION & ENV LOAD ---
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_PATH = BASE_DIR.parent / ".env"
load_dotenv(dotenv_path=ENV_PATH)

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# New Imports
from tradingview_webhook_bot.storage.idempotency_store import IdempotencyStore
from tradingview_webhook_bot.core.schemas import SignalPayload

# Existing Imports
from tradingview_webhook_bot.storage.sheets_logger import GoogleSheetsLogger
from tradingview_webhook_bot.storage.jsonl_consumer import JsonlOffsetConsumer
from tradingview_webhook_bot.ledger.positions import PositionLedger
from tradingview_webhook_bot.alerts.router import AlertRouter
from tradingview_webhook_bot.recon.reconciler import Reconciler
from tradingview_webhook_bot.exchange.binance_client import BinanceClient

# --- 2. LOGGING CONFIGURATION ---
class SensitiveFilter(logging.Filter):
    def filter(self, record):
        msg = str(record.msg)
        secrets = [os.getenv("WEBHOOK_SECRET"), os.getenv("BINANCE_API_KEY"), os.getenv("BINANCE_API_SECRET")]
        for s in secrets:
            if s and len(s) > 5 and s in msg:
                record.msg = msg.replace(s, "********")
        return True

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
logger.addFilter(SensitiveFilter())

class Orchestrator:
    def __init__(self):
        # --- 3. CONFIGURATION LOAD ---
        self.allow_real = os.getenv("ALLOW_REAL_TRADES", "false").lower() == "true"
        self.run_mode = os.getenv("RUN_MODE", "production")
        self.dlq_path = "storage/dead_letter.jsonl"
        self.idempotency_db = os.getenv("IDEMPOTENCY_DB_PATH", "storage/idempotency.db")

        self.processed_count = 0
        self.last_heartbeat = time.time()
        self.manual_overrides = {}

        self.dlq_threshold_count = int(os.getenv("DLQ_THRESHOLD", "5"))
        self.dlq_threshold_window = int(os.getenv("DLQ_WINDOW_SECONDS", "60"))
        self.recent_failures = []

        self.ledger_path = os.getenv("LEDGER_PATH", "storage/ledger_state.json")
        self.alerts_log = os.getenv("ALERTS_LOG", "storage/alerts.jsonl")
        self.queue_path = os.getenv("QUEUE_PATH", "storage/signals.jsonl")
        self.offset_path = os.getenv("OFFSET_PATH", "storage/signals.offset")

        # --- INITIALIZATION ---
        self.ledger = PositionLedger(self.ledger_path)
        self.alerts = AlertRouter(self.alerts_log)
        self.reconciler = Reconciler(self.ledger)
        self.sheets_logger = GoogleSheetsLogger(json_key="service_account.json")
        self.consumer = JsonlOffsetConsumer(self.queue_path, self.offset_path)
        self.exchange = BinanceClient()
        
        # 🔑 Initialize Idempotency Store
        self.idempotency = IdempotencyStore(self.idempotency_db)

    def get_dlq_size(self):
        try:
            if not os.path.exists(self.dlq_path): return 0
            with open(self.dlq_path, "r") as f:
                return sum(1 for line in f if line.strip())
        except: return 0

    def check_queue_lag(self, signal_timestamp: float):
        current_time = time.time()
        lag = current_time - signal_timestamp
        if lag > 60:
            logger.warning(f"🐢 HIGH QUEUE LAG: {lag:.2f}s delay detected.")
            if lag > 300:
                self.alerts.send(f"🚨 CRITICAL LAG: Signal delayed by {lag/60:.1f}m", severity="WARNING", channel="SYSTEM")
        return lag

    def process_commands(self):
        updates = self.alerts.get_updates()
        if not updates: return
        for cmd_text in updates:
            cmd = cmd_text.lower().strip()
            if cmd == "/status":
                health = self.exchange.get_account_health()
                msg = f"📊 Live Status\n- Processed: {self.processed_count}\n- DLQ Size: {self.get_dlq_size()}"
                if health: msg += f"\n- Balance: ${health['available_balance']:.2f}"
                self.alerts.reply(msg, channel="SYSTEM")

    def handle_signal(self, event: dict) -> bool:
        """Core signal handler with Normalization and Idempotency."""
        try:
            signal_id = event.get("signal_id")
            
            # 🛡️ 1. IDEMPOTENCY CHECK (Don't process if already seen)
            if self.idempotency.is_seen(signal_id):
                logger.info(f"⏭️ Skipping already processed signal: {signal_id}")
                return True

            received_at = event.get("received_at", time.time())
            self.check_queue_lag(received_at)

            payload_raw = event.get("payload", {})
            
            # 📝 2. SCHEMA VALIDATION
            try:
                # Validate using Pydantic
                valid_payload = SignalPayload(**payload_raw)
                payload = valid_payload.dict()
            except Exception as schema_err:
                logger.error(f"❌ Schema Validation Failed: {schema_err}")
                self.move_to_dlq(event, f"Schema Error: {schema_err}")
                return True

            # --- NORMALIZATION ---
            raw_symbol = payload.get("symbol", "").upper()
            symbol = "BTCUSDT" if raw_symbol in ["BTCUSD", "BTC"] else raw_symbol

            original_action = payload.get("action", "").upper()
            side = "SELL" if original_action in ["SELL", "TP", "EXIT"] else "BUY"

            qty = float(payload.get("quantity", 0))
            price = float(payload.get("price", 0))

            strat_id = payload.get("strategy_id") or payload.get("strategy") or "Bot"
            indicator = payload.get("indicator", "N/A")

            # --- EXECUTION ---
            execution_res = self.exchange.execute_futures_order(symbol, side, qty, price, signal_id=signal_id)
            exec_status = execution_res.get("status")

            if exec_status == "SUCCESS":
                # 🛡️ 3. MARK AS SEEN (Only after successful execution)
                self.idempotency.mark_seen(signal_id)
                
                self.processed_count += 1
                self.ledger.apply_fill(symbol, side, qty, price)
                self.sheets_logger.log_trade(symbol=symbol, action=side, qty=qty, price=price)

                emoji = "🎯" if original_action == "TP" else ("🟢" if side == "BUY" else "🔴")
                rich_msg = (
                    f"{emoji} Bot Alert ({strat_id})\n\n"
                    f"✅ Executed: {original_action} {symbol}\n"
                    f"💰 Price: {price}\n"
                    f"📊 Indicator: {indicator}\n"
                    f"📦 Qty: {qty}\n"
                    f"🆔 ID: {signal_id}"
                )

                self.alerts.send(rich_msg, channel="TRADES")
                return True

            elif exec_status == "FAILED":
                reason = execution_res.get("reason", "unknown")
                self.alerts.send(f"❌ Trade Failed\nSymbol: {symbol}\nReason: {reason}", severity="CRITICAL", channel="SYSTEM")
                if reason != "permanent":
                    self.move_to_dlq(event, f"Exchange Failure: {reason}")
                return True

            return True

        except Exception as e:
            logger.error(f"❌ Critical Failure: {e}")
            self.move_to_dlq(event, str(e))
            return True

    def move_to_dlq(self, event: dict, error_msg: str):
        try:
            now = datetime.now()
            self.recent_failures.append(now)
            dlq_entry = {"timestamp": now.isoformat(), "error": error_msg, "original_event": event}
            with open(self.dlq_path, "a") as f:
                f.write(json.dumps(dlq_entry) + "\n")
            self.check_dlq_threshold()
        except Exception as dlq_err:
            logger.critical(f"🔥 DLQ WRITE FAILURE: {dlq_err}")

    def check_dlq_threshold(self):
        now = datetime.now()
        cutoff = now - timedelta(seconds=self.dlq_threshold_window)
        self.recent_failures = [t for t in self.recent_failures if t > cutoff]
        if len(self.recent_failures) >= self.dlq_threshold_count:
            self.alerts.send("🚨 *CRITICAL DLQ BURST DETECTED!*", severity="CRITICAL", channel="SYSTEM")

    def run(self):
        logger.info(f"🚀 Engine Live | Mode: {self.run_mode} | Real: {self.allow_real}")
        last_recon = time.time()
        while True:
            self.consumer.poll(handler=self.handle_signal, batch_size=5)
            self.process_commands()
            current_time = time.time()
            if current_time - self.last_heartbeat > 900:
                logger.info(f"💓 Heartbeat | Processed: {self.processed_count} | DLQ: {self.get_dlq_size()}")
                self.last_heartbeat = current_time
            if current_time - last_recon > 900:
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
