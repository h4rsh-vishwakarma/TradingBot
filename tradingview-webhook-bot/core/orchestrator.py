import time, logging, os
from tradingview_webhook_bot.storage.sheets_logger import GoogleSheetsLogger
from tradingview_webhook_bot.storage.jsonl_consumer import JsonlOffsetConsumer
from tradingview_webhook_bot.ledger.positions import PositionLedger
from tradingview_webhook_bot.alerts.router import AlertRouter
from tradingview_webhook_bot.recon.reconciler import Reconciler

logger = logging.getLogger(__name__)

class Orchestrator:
    def __init__(self):
        # Load Env Configs
        self.allow_real = os.getenv("ALLOW_REAL_TRADES", "false").lower() == "true"
        self.run_mode = os.getenv("RUN_MODE", "development")
        
        # Paths
        self.ledger = PositionLedger(os.getenv("LEDGER_PATH", "storage/ledger_state.json"))
        self.alerts = AlertRouter(os.getenv("ALERTS_LOG", "storage/alerts.jsonl"))
        self.reconciler = Reconciler(self.ledger)
        self.sheets_logger = GoogleSheetsLogger(json_key="service_account.json")
        self.consumer = JsonlOffsetConsumer(os.getenv("QUEUE_PATH"), os.getenv("OFFSET_PATH"))

    def handle_signal(self, event: dict) -> bool:
        try:
            payload = event.get("payload", {})
            symbol, side = payload.get("symbol"), payload.get("action")
            qty, price = float(payload.get("quantity", 0)), float(payload.get("price", 0))

            # --- GAP: SAFETY GATE ---
            if not self.allow_real and self.run_mode == "production":
                logger.warning(f"🚨 TRADE BLOCKED: {side} {symbol} (Safety Gate Active)")
                self.alerts.send(f"⚠️ Safety Gate blocked trade for {symbol}", severity="WARNING")
                return True

            # Standard Execution
            self.ledger.apply_fill(symbol, side, qty, price)
            self.sheets_logger.log_trade(symbol, side, qty, price, payload.get("strategy", "Auto"))
            self.alerts.send(f"✅ Executed {side} {symbol} @ {price}")
            return True
        except Exception as e:
            logger.error(f"❌ Handle Error: {e}")
            return False

    def process_commands(self):
        commands = self.alerts.get_updates()
        for cmd in commands:
            cmd = cmd.lower().strip()
            if cmd == "/status":
                pos_data = getattr(self.ledger, 'positions', {})
                # --- GAP: RECONCILIATION INTEGRATION ---
                # Example: Reconciling with an empty dict for now (Mocking Exchange)
                drifts = self.reconciler.reconcile_with_exchange({}) 
                
                status_msg = "📊 *Live Status:*\n"
                for sym, data in pos_data.items():
                    status_msg += f"- `{sym}`: {data['quantity']} @ ${data.get('avg_price', 0)}\n"
                
                if drifts: status_msg += "\n⚠️ *Drift Alert:* Reconciliation Mismatch!"
                self.alerts.reply(status_msg)

    def run(self):
        logger.info(f"🚀 Engine Live | Mode: {self.run_mode} | Real Trades: {self.allow_real}")
        while True:
            self.consumer.poll(handler=self.handle_signal, batch_size=10)
            self.process_commands()
            time.sleep(1)
