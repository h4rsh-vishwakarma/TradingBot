import time, logging, os, json, sys
from datetime import datetime
from pathlib import Path

# --- 1. PATH RESOLUTION (Senior Standard) ---
# Fixes ModuleNotFoundError for hyphenated project directories
BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from tradingview_webhook_bot.storage.sheets_logger import GoogleSheetsLogger
from tradingview_webhook_bot.storage.jsonl_consumer import JsonlOffsetConsumer
from tradingview_webhook_bot.ledger.positions import PositionLedger
from tradingview_webhook_bot.alerts.router import AlertRouter
from tradingview_webhook_bot.recon.reconciler import Reconciler
from tradingview_webhook_bot.exchange import BinanceClient

# --- 2. SECRETS REDACTION FILTER (Day 1 Compliance) ---
class SensitiveFilter(logging.Filter):
    def filter(self, record):
        msg = str(record.msg)
        secrets = [os.getenv("WEBHOOK_SECRET"), os.getenv("BINANCE_API_KEY"), os.getenv("BINANCE_API_SECRET")]
        for s in secrets:
            if s and len(s) > 5 and s in msg:
                record.msg = msg.replace(s, "********")
        return True

logger = logging.getLogger(__name__)
logger.addFilter(SensitiveFilter())

class Orchestrator:
    def __init__(self):
        # --- 3. CONFIGURATION LOAD (Day 4 Monitoring) ---
        self.allow_real = os.getenv("ALLOW_REAL_TRADES", "false").lower() == "true"
        self.run_mode = os.getenv("RUN_MODE", "development")
        self.dlq_path = os.getenv("DLQ_PATH", "storage/dlq.jsonl")

        # Core Component Initialization
        self.ledger = PositionLedger(os.getenv("LEDGER_PATH", "storage/ledger_state.json"))
        self.alerts = AlertRouter(os.getenv("ALERTS_LOG", "storage/alerts.jsonl"))
        self.reconciler = Reconciler(self.ledger)
        self.sheets_logger = GoogleSheetsLogger(json_key="service_account.json")
        self.consumer = JsonlOffsetConsumer(os.getenv("QUEUE_PATH"), os.getenv("OFFSET_PATH"))
        self.exchange = BinanceClient()

    def handle_signal(self, event: dict) -> bool:
        """Processes incoming signals based on schema-compliant status"""
        try:
            # --- SCHEMA COMPLIANCE FIX ---
            # Must accept 'received' as per Pydantic Enum constraints
            current_status = event.get("status")
            if current_status not in ["received", "enqueued", "processing"]:
                return False

            payload = event.get("payload", {})
            symbol = payload.get("symbol")
            side = payload.get("action")
            qty = float(payload.get("quantity", 0))
            price = float(payload.get("price", 0))

            # --- SAFETY GATE (Day 1 Requirement) ---
            if not self.allow_real and self.run_mode == "production":
                logger.warning(f"🚨 TRADE BLOCKED: {side} {symbol} (Safety Gate Active)")
                self.alerts.send(f"⚠️ Safety Gate blocked trade for {symbol}", severity="WARNING")
                return True

            # --- DAY 3: EXTERNAL EXECUTION (Testnet or Live) ---
            execution_res = self.exchange.execute_futures_order(symbol, side, qty, price)

            # --- INTERNAL ACCOUNTING (Ledger & Sheets) ---
            if execution_res and execution_res.get("status") != "SKIPPED":
                self.ledger.apply_fill(symbol, side, qty, price)
                
                # Updated to match GoogleSheetsLogger.log_trade arguments
                self.sheets_logger.log_trade(
                    symbol=symbol, 
                    action=side, 
                    qty=qty, 
                    price=price, 
                    strategy=payload.get("strategy", "Auto")
                )
                self.alerts.send(f"✅ Executed {side} {symbol} @ {price}")

            return True

        except Exception as e:
            # --- DLQ BEHAVIOR (Day 3 Recovery) ---
            logger.error(f"❌ Critical Failure: {e} | Moving to DLQ")
            self.move_to_dlq(event, str(e))
            self.alerts.send(f"🚨 ALERT: Signal processing failed. Check DLQ.", severity="CRITICAL")
            return False

    def run_auto_reconcile(self):
        """Day 4 Requirement: Automated Reconciliation & Alert Rules"""
        try:
            logger.info("🔍 Running Automated Reconciliation...")
            exchange_data = self.exchange.get_audit_data()
            drifts = self.reconciler.reconcile_with_exchange(exchange_data)

            if drifts:
                msg = f"⚠️ RECON DRIFT DETECTED!\n{drifts}"
                logger.warning(msg)
                self.alerts.send(msg, severity="CRITICAL")
                return True

            logger.info("✅ Reconciliation Clean: No drift detected.")
            return False
        except Exception as e:
            logger.error(f"Reconciliation Loop Failed: {e}")

    def process_commands(self):
        """Monitoring via External Commands (Day 4 Metric Monitoring)"""
        commands = self.alerts.get_updates()
        if not commands: return
        
        for cmd in commands:
            cmd = cmd.lower().strip()
            if cmd == "/status":
                health = self.exchange.get_account_health()
                pos_data = getattr(self.ledger, 'positions', {})

                status_msg = "📊 *Live Status:*\n"
                if health:
                    status_msg += f"💰 Balance: ${health['available_balance']:.2f}\n"
                    status_msg += f"📈 Margin Ratio: {health['margin_ratio']:.2%}\n\n"

                for sym, data in pos_data.items():
                    status_msg += f"- `{sym}`: {data.quantity} @ ${data.avg_price:.2f}\n"

                self.alerts.reply(status_msg)

    def move_to_dlq(self, event: dict, error_msg: str):
        """Saves failed signals for manual recovery"""
        try:
            dlq_entry = {
                "timestamp": datetime.now().isoformat(),
                "error": error_msg,
                "original_event": event
            }
            with open(self.dlq_path, "a") as f:
                f.write(json.dumps(dlq_entry) + "\n")
        except Exception as dlq_err:
            logger.critical(f"🔥 FAILED TO WRITE TO DLQ: {dlq_err}")

    def run(self):
        """Main Loop with Day 4 Heartbeats & Periodic Recon"""
        logger.info(f"🚀 Engine Live | Mode: {self.run_mode} | Real Trades: {self.allow_real}")
        last_recon_time = 0

        while True:
            # 1. Main Signal Processing
            self.consumer.poll(handler=self.handle_signal, batch_size=10)

            # 2. Command Processing
            self.process_commands()

            # 3. Automated Reconciliation Loop (Every 15 mins)
            current_time = time.time()
            if current_time - last_recon_time > 900:  # 900s = 15 min
                self.run_auto_reconcile()
                last_recon_time = current_time

            time.sleep(1)
