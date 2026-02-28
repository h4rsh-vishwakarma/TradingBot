import time, logging, os, json, sys, smtplib
from datetime import datetime, timedelta
from pathlib import Path
from email.mime.text import MIMEText

# --- 1. PATH RESOLUTION ---
BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from tradingview_webhook_bot.storage.sheets_logger import GoogleSheetsLogger
from tradingview_webhook_bot.storage.jsonl_consumer import JsonlOffsetConsumer
from tradingview_webhook_bot.ledger.positions import PositionLedger
from tradingview_webhook_bot.alerts.router import AlertRouter
from tradingview_webhook_bot.recon.reconciler import Reconciler
from tradingview_webhook_bot.exchange import BinanceClient

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
        self.run_mode = os.getenv("RUN_MODE", "development")
        self.dlq_path = os.getenv("DLQ_PATH", "storage/dlq.jsonl")

        # Email Config
        self.email_sender = os.getenv("EMAIL_SENDER")
        self.email_password = os.getenv("EMAIL_PASSWORD")
        self.email_receiver = os.getenv("EMAIL_RECEIVER")
        self.smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", 587))

        # Policy & Metrics
        self.allowed_symbols = os.getenv("ALLOWED_SYMBOLS", "BTCUSDT,ETHUSDT").split(",")
        self.manual_overrides = {}
        self.processed_count = 0
        self.last_heartbeat = time.time()

        # DLQ Thresholds
        self.dlq_threshold_count = int(os.getenv("DLQ_THRESHOLD", "5"))
        self.dlq_threshold_window = int(os.getenv("DLQ_WINDOW_SECONDS", "60"))
        self.recent_failures = []

        # Core Component Initialization
        self.ledger = PositionLedger(os.getenv("LEDGER_PATH", "storage/ledger_state.json"))
        self.alerts = AlertRouter(os.getenv("ALERTS_LOG", "storage/alerts.jsonl"))
        self.reconciler = Reconciler(self.ledger)
        self.sheets_logger = GoogleSheetsLogger(json_key="service_account.json")
        self.consumer = JsonlOffsetConsumer(os.getenv("QUEUE_PATH"), os.getenv("OFFSET_PATH"))
        self.exchange = BinanceClient()

    def send_email_alert(self, subject: str, body: str):
        """Sends a high-priority fail-safe email alert."""
        if not all([self.email_sender, self.email_password, self.email_receiver]):
            logger.warning("📧 Email credentials missing. Skipping email alert.")
            return

        try:
            msg = MIMEText(body)
            msg['Subject'] = f"🚨 Bot Critical: {subject}"
            msg['From'] = self.email_sender
            msg['To'] = self.email_receiver

            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.email_sender, self.email_password)
                server.send_message(msg)
                logger.info(f"📧 Fail-safe email sent: {subject}")
        except Exception as e:
            logger.error(f"❌ Failed to send email alert: {e}")

    def get_dlq_size(self):
        """Returns count of failed signals in DLQ file"""
        try:
            if not os.path.exists(self.dlq_path): return 0
            with open(self.dlq_path, "r") as f:
                return sum(1 for line in f if line.strip())
        except: return 0

    def is_gate_open(self, symbol: str) -> bool:
        """Safety Gate Logic with manual override support"""
        if self.allow_real: return True
        if symbol in self.manual_overrides:
            if time.time() < self.manual_overrides[symbol]: return True
            else:
                del self.manual_overrides[symbol]
                logger.info(f"🔒 Override expired for {symbol}")
        return False

    def handle_signal(self, event: dict) -> bool:
        """Processes signals with Step 2 Idempotency Logic"""
        try:
            current_status = event.get("status")
            if current_status not in ["received", "enqueued", "processing"]:
                return False

            payload = event.get("payload", {})
            symbol = payload.get("symbol")
            side = payload.get("action")
            qty = float(payload.get("quantity", 0))
            price = float(payload.get("price", 0))
            signal_id = event.get("signal_id")

            if not self.is_gate_open(symbol):
                logger.warning(f"🚨 POLICY BLOCK: {side} {symbol}")
                self.alerts.send(f"⚠️ Policy Block: Trade for {symbol} suppressed.", severity="WARNING", channel="SYSTEM")
                return True

            # --- STEP 2: EXECUTION WITH IDEMPOTENCY ---
            execution_res = self.exchange.execute_futures_order(symbol, side, qty, price, signal_id=signal_id)
            exec_status = execution_res.get("status")

            if exec_status == "SUCCESS":
                self.processed_count += 1
                self.ledger.apply_fill(symbol, side, qty, price)
                self.sheets_logger.log_trade(
                    symbol=symbol, action=side, qty=qty, price=price,
                    strategy=payload.get("strategy", "Auto")
                )
                self.alerts.send(f"✅ Processed {side} {symbol} (Signal: {signal_id})", channel="TRADES")
                return True

            elif exec_status == "SKIPPED":
                # Handle Idempotency / Safety Skip (No alert needed for duplicate)
                logger.info(f"⏭️ Signal {signal_id} Skipped. Reason: {execution_res.get('reason')}")
                return True

            elif exec_status == "FAILED":
                # Handle Hard Failures
                reason = execution_res.get("reason", "unknown")
                msg = execution_res.get("msg", "No details")
                
                logger.error(f"❌ Execution Failed [{reason}]: {msg}")
                self.alerts.send(f"🚨 EXECUTION FAILED: {side} {symbol}\nReason: {reason}\n{msg}", severity="CRITICAL", channel="SYSTEM")
                
                # Only move to DLQ if it's not a permanent rejection (e.g. timeout)
                if reason != "permanent":
                    self.move_to_dlq(event, f"Binance Failure: {reason} - {msg}")
                
                return True

            return False

        except Exception as e:
            err_msg = f"❌ Critical Orchestration Failure: {e}"
            logger.error(f"{err_msg} | Moving to DLQ")
            self.move_to_dlq(event, str(e))
            self.check_dlq_threshold()
            self.send_email_alert("Signal Processing Crash", f"Event ID: {event.get('signal_id')}\nError: {e}")
            return True

    def move_to_dlq(self, event: dict, error_msg: str):
        """Storage for failed signals"""
        try:
            now = datetime.now()
            self.recent_failures.append(now)
            dlq_entry = {
                "timestamp": now.isoformat(),
                "error": error_msg,
                "original_event": event
            }
            with open(self.dlq_path, "a") as f:
                f.write(json.dumps(dlq_entry) + "\n")
        except Exception as dlq_err:
            logger.critical(f"🔥 FAILED TO WRITE TO DLQ: {dlq_err}")

    def check_dlq_threshold(self):
        """Alerts SYSTEM channel and Email on rapid failures"""
        now = datetime.now()
        cutoff = now - timedelta(seconds=self.dlq_threshold_window)
        self.recent_failures = [t for t in self.recent_failures if t > cutoff]
        if len(self.recent_failures) >= self.dlq_threshold_count:
            msg = f"🚨 *CRITICAL DLQ BURST DETECTED!* ({len(self.recent_failures)} failures in window)"
            self.alerts.send(msg, severity="CRITICAL", channel="SYSTEM")
            self.send_email_alert("Rapid DLQ Burst", msg)

    def process_commands(self):
        """Processes interactive Telegram commands from the SYSTEM channel"""
        commands = self.alerts.get_updates()
        if not commands: return
        for cmd_text in commands:
            cmd = cmd_text.lower().strip()
            if cmd.startswith("/override"):
                try:
                    parts = cmd.split()
                    symbol = parts[1].upper()
                    self.manual_overrides[symbol] = time.time() + 3600
                    self.alerts.reply(f"⚡ *OVERRIDE:* `{symbol}` opened for 60m.", channel="SYSTEM")
                except: self.alerts.reply("❌ Usage: `/override SYMBOL`", channel="SYSTEM")
            elif cmd == "/status":
                health = self.exchange.get_account_health()
                msg = f"📊 *Live Status*\n- Processed: {self.processed_count}\n- DLQ Size: {self.get_dlq_size()}"
                if health: msg += f"\n- Balance: ${health['available_balance']:.2f}"
                self.alerts.reply(msg, channel="SYSTEM")

    def run(self):
        logger.info(f"🚀 Engine Live | Mode: {self.run_mode} | Real: {self.allow_real}")
        last_recon_time = time.time()

        while True:
            self.consumer.poll(handler=self.handle_signal, batch_size=10)
            self.process_commands()

            current_time = time.time()
            if current_time - self.last_heartbeat > 900:
                logger.info(f"💓 Internal Heartbeat | Processed: {self.processed_count} | DLQ: {self.get_dlq_size()}")
                self.last_heartbeat = current_time

            if current_time - last_recon_time > 900:
                try:
                    exchange_data = self.exchange.get_audit_data()
                    drifts = self.reconciler.reconcile_with_exchange(exchange_data)
                    if drifts:
                        msg = f"⚠️ RECON DRIFT DETECTED! System and Exchange positions do not match."
                        self.alerts.send(msg, severity="CRITICAL", channel="SYSTEM")
                        self.send_email_alert("Reconciliation Drift", msg)
                except Exception as e:
                    logger.error(f"Recon Failed: {e}")
                last_recon_time = current_time

            time.sleep(1)

if __name__ == "__main__":
    orchestrator = Orchestrator()
    orchestrator.run()
