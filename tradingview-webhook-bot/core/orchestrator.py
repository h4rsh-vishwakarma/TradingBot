import time, logging, os, json, sys
from datetime import datetime, timedelta
from pathlib import Path

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
        
        # Task C & G: Policy & Metrics
        self.allowed_symbols = os.getenv("ALLOWED_SYMBOLS", "BTCUSDT,ETHUSDT").split(",")
        self.manual_overrides = {}
        self.processed_count = 0
        self.last_heartbeat = time.time()

        # Task B: DLQ Thresholds
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

    def get_dlq_size(self):
        """Task G Metrics: Returns count of failed signals in DLQ file"""
        try:
            if not os.path.exists(self.dlq_path): return 0
            with open(self.dlq_path, "r") as f:
                return sum(1 for line in f if line.strip())
        except: return 0

    def is_gate_open(self, symbol: str) -> bool:
        """Task C: Safety Gate Logic"""
        if self.allow_real: return True
        if symbol in self.manual_overrides:
            if time.time() < self.manual_overrides[symbol]: return True
            else: 
                del self.manual_overrides[symbol]
                logger.info(f"🔒 Override expired for {symbol}")
        return False

    def handle_signal(self, event: dict) -> bool:
        """Processes signals and updates Task G metrics"""
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

            # --- SAFETY GATE ---
            if not self.is_gate_open(symbol):
                logger.warning(f"🚨 POLICY BLOCK: {side} {symbol}")
                self.alerts.send(f"⚠️ Policy Block: Trade for {symbol} suppressed.", severity="WARNING")
                return True

            # --- EXECUTION ---
            execution_res = self.exchange.execute_futures_order(symbol, side, qty, price, signal_id=signal_id)

            # --- ACCOUNTING & METRICS (Task G) ---
            # Hum isse 'processed' tabhi maante hain jab execution fail na ho (Dry-run skip is considered a process success)
            if execution_res and execution_res.get("status") != "FAILED":
                self.processed_count += 1 
                
                # Agar trade skip nahi hua (real fill ya dry-run logic update)
                if execution_res.get("status") != "SKIPPED":
                    self.ledger.apply_fill(symbol, side, qty, price)
                    self.sheets_logger.log_trade(
                        symbol=symbol, action=side, qty=qty, price=price,
                        strategy=payload.get("strategy", "Auto")
                    )
                
                self.alerts.send(f"✅ Processed {side} {symbol} (Signal: {signal_id})")
            
            return True

        except Exception as e:
            logger.error(f"❌ Critical Failure: {e} | Moving to DLQ")
            self.move_to_dlq(event, str(e))
            self.check_dlq_threshold()
            return True 

    def move_to_dlq(self, event: dict, error_msg: str):
        """Task B & E: DLQ Storage"""
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
        """Task B: Alert on rapid failures"""
        now = datetime.now()
        cutoff = now - timedelta(seconds=self.dlq_threshold_window)
        self.recent_failures = [t for t in self.recent_failures if t > cutoff]
        if len(self.recent_failures) >= self.dlq_threshold_count:
            self.alerts.send(f"🚨 *CRITICAL DLQ BURST DETECTED!*", severity="CRITICAL")

    def process_commands(self):
        """Task G: Command Processing"""
        commands = self.alerts.get_updates()
        if not commands: return
        for cmd_text in commands:
            cmd = cmd_text.lower().strip()
            if cmd.startswith("/override"):
                try:
                    parts = cmd.split()
                    symbol = parts[1].upper()
                    self.manual_overrides[symbol] = time.time() + 3600
                    self.alerts.reply(f"⚡ *OVERRIDE:* `{symbol}` opened for 60m.")
                except: self.alerts.reply("❌ Usage: `/override SYMBOL`")
            elif cmd == "/status":
                health = self.exchange.get_account_health()
                msg = f"📊 *Live Status*\n- Processed: {self.processed_count}\n- DLQ Size: {self.get_dlq_size()}"
                if health: msg += f"\n- Balance: ${health['available_balance']:.2f}"
                self.alerts.reply(msg)

    def run(self):
        logger.info(f"🚀 Engine Live | Mode: {self.run_mode} | Real: {self.allow_real}")
        last_recon_time = time.time()
        
        while True:
            # 1. Poll Signals
            self.consumer.poll(handler=self.handle_signal, batch_size=10)
            
            # 2. Process Telegram Commands
            self.process_commands()

            current_time = time.time()
            # 3. Task G: Heartbeat (Every 15 mins)
            if current_time - self.last_heartbeat > 900:
                stats = f"💓 *Engine Heartbeat*\n- Processed: {self.processed_count}\n- DLQ Size: {self.get_dlq_size()}"
                self.alerts.send(stats, severity="INFO")
                self.last_heartbeat = current_time

            # 4. Periodic Reconciliation (Every 15 mins)
            if current_time - last_recon_time > 900:
                try:
                    exchange_data = self.exchange.get_audit_data()
                    drifts = self.reconciler.reconcile_with_exchange(exchange_data)
                    if drifts: self.alerts.send(f"⚠️ RECON DRIFT DETECTED!", severity="CRITICAL")
                except Exception as e: logger.error(f"Recon Failed: {e}")
                last_recon_time = current_time

            time.sleep(1)

if __name__ == "__main__":
    orchestrator = Orchestrator()
    orchestrator.run()
