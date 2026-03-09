import time, logging, os, json, sys
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

# --- 1. PATH RESOLUTION & ENV LOAD ---
CORE_DIR = Path(__file__).resolve().parent
BASE_DIR = CORE_DIR.parent

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
        # 🛡️ 3. RISK LIMITS & CONFIGURATION
        self.allow_real = os.getenv("ALLOW_REAL_TRADES", "false").lower() == "true"
        self.run_mode = os.getenv("RUN_MODE", "production")

        # Financial Gates
        self.max_notional = float(os.getenv("MAX_NOTIONAL_PER_TRADE", "500.0"))
        self.daily_loss_limit = float(os.getenv("DAILY_LOSS_LIMIT", "-50.0"))
        self.allowed_symbols = os.getenv("ALLOWED_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",")

        # Storage Paths
        storage_dir = Path("/home/ubuntu/tradingview_webhook_bot/tradingview_webhook_bot/storage")
        storage_dir.mkdir(parents=True, exist_ok=True)

        self.dlq_path = str(storage_dir / "dead_letter.jsonl")
        self.idempotency_db = os.getenv("IDEMPOTENCY_DB_PATH") or str(storage_dir / "idempotency.db")
        self.ledger_path = os.getenv("LEDGER_PATH") or str(storage_dir / "ledger_state.json")
        self.alerts_log = os.getenv("ALERTS_LOG") or str(storage_dir / "alerts.jsonl")
        self.queue_path = os.getenv("QUEUE_PATH") or str(storage_dir / "signals.jsonl")
        self.offset_path = os.getenv("OFFSET_PATH") or str(storage_dir / "signals.offset")

        # Init Components
        self.ledger = PositionLedger(self.ledger_path)
        self.alerts = AlertRouter(self.alerts_log)
        self.reconciler = Reconciler(self.ledger)
        self.sheets_logger = GoogleSheetsLogger()
        self.consumer = JsonlOffsetConsumer(self.queue_path, self.offset_path)
        self.exchange = BinanceClient()
        self.idempotency = IdempotencyStore(self.idempotency_db)

        self.processed_count = 0
        self.last_heartbeat = time.time()

    def check_safety_gate(self, symbol, qty, price, side) -> tuple[bool, str]:
        """🛡️ Pre-Trade Risk Validation & Redundancy Check"""
        if not self.allow_real:
            return False, "ALLOW_REAL_TRADES is disabled"

        # 1. Daily Loss Limit Check
        try:
            current_pnl = self.ledger.get_daily_pnl()
            if current_pnl <= self.daily_loss_limit:
                return False, f"Daily loss limit hit: ${current_pnl:.2f}"
        except Exception as e:
            logger.error(f"Risk Check Error: {e}")
            return False, "Ledger PnL calculation failed"

        # 2. Redundant Trade Protection (Over-trading)
        current_pos = self.ledger.get_position(symbol)
        if side == "BUY" and current_pos.quantity > 0:
            return False, f"Already LONG {symbol}. Blocking redundant BUY."
        if side == "SELL" and current_pos.quantity < 0:
            return False, f"Already SHORT {symbol}. Blocking redundant SELL."

        # 3. Notional Size Check
        notional_value = qty * price
        if notional_value > self.max_notional:
            return False, f"Notional size ${notional_value:.2f} exceeds max ${self.max_notional}"

        # 4. Symbol Whitelist
        if symbol not in self.allowed_symbols:
            return False, f"Symbol {symbol} not in allowed whitelist"

        return True, "Safe"

    def handle_signal(self, event: dict) -> bool:
        """Core signal handler with Analytics and Safety Gates."""
        try:
            signal_id = event.get("signal_id")
            if self.idempotency.is_seen(signal_id):
                logger.info(f"⏭️ Skipping already processed signal: {signal_id}")
                return True

            payload_raw = event.get("payload", {})

            # 📝 1. SCHEMA VALIDATION & CLEANING
            try:
                if not payload_raw.get("action"):
                    ind = str(payload_raw.get("indicator", "")).upper()
                    payload_raw["action"] = "BUY" if any(x in ind for x in ["BULL", "LONG", "BOS"]) else "SELL"

                if not payload_raw.get("quantity"):
                    payload_raw["quantity"] = 0.003 

                valid_payload = SignalPayload(**payload_raw)
                payload = valid_payload.model_dump()
            except Exception as schema_err:
                logger.error(f"❌ Schema Validation Failed: {schema_err}")
                self.move_to_dlq(event, f"Schema Error: {schema_err}")
                return True

            # 🛡️ 2. ADAPTIVE SYMBOL SECURITY
            raw_symbol = str(payload.get("symbol", "")).upper()
            if "USDT" not in raw_symbol:
                if "BTC" in raw_symbol: symbol = "BTCUSDT"
                elif "ETH" in raw_symbol: symbol = "ETHUSDT"
                elif "SOL" in raw_symbol: symbol = "SOLUSDT"
                else:
                    clean = raw_symbol.replace("USD", "").replace("H2026", "").replace(".P", "")
                    symbol = f"{clean}USDT"
            else:
                symbol = raw_symbol

            logger.info(f"🔄 Routing Signal: {raw_symbol} -> {symbol}")

            # 3. EXTRACTION
            original_action = payload.get("action", "").upper()
            side = "SELL" if original_action in ["SELL", "TP", "EXIT", "SHORT"] else "BUY"
            qty = float(payload.get("quantity", 0))
            price = float(payload.get("price", 0))
            strat_id = payload.get("strategy_id") or payload.get("strategy") or "Bot_Strategy"
            indicator_name = payload.get("indicator") or "SMC_LuxAlgo"

            # 🛡️ 4. RISK GATE & REDUNDANCY VERIFICATION
            is_safe, reason = self.check_safety_gate(symbol, qty, price, side)
            if not is_safe:
                logger.warning(f"🚧 SAFETY GATE BLOCKED: {symbol} - {reason}")
                if "redundant" not in reason.lower():
                    self.alerts.send(f"🚧 *Safety Gate Blocked Trade*\nSymbol: {symbol}\nReason: {reason}", severity="WARNING")
                return True

            # 5. EXECUTION
            execution_res = self.exchange.execute_futures_order(symbol, side, qty, price, signal_id=signal_id)

            if execution_res.get("status") == "SUCCESS":
                client_oid = execution_res.get("order_id", "manual")
                self.idempotency.mark_seen(signal_id, client_order_id=client_oid)

                # Update Ledger and get Realized PnL
                pos_snapshot = self.ledger.apply_fill(symbol, side, qty, price)
                realized_pnl = pos_snapshot.daily_realized_pnl # Use daily realized or total realized

                self.processed_count += 1
                
                # 📊 LOG TO GOOGLE SHEETS (Detailed for Analytics)
                self.sheets_logger.log_trade(
                    signal_id=signal_id,
                    symbol=symbol,
                    action=side,
                    qty=qty,
                    price=price,
                    strategy=strat_id,
                    indicator=indicator_name,
                    pnl=realized_pnl
                )

                # --- 🟢 PROFESSIONAL NOTIFICATION ---
                emoji = "🟢" if side == "BUY" else "🔴"
                msg = (
                    f"{emoji} *Bot Alert*\n\n"
                    f"✅ *Executed:* {side} {symbol}\n"
                    f"💰 *Price:* {price}\n"
                    f"📊 *Indicator:* {indicator_name}\n"
                    f"📦 *Qty:* {qty}\n"
                    f"🆔 *ID:* {signal_id}\n"
                    f"💵 *Realized PnL:* ${realized_pnl:.2f}"
                )

                self.alerts.send(msg, channel="TRADES")
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

    def get_dlq_size(self):
        try:
            if not os.path.exists(self.dlq_path): return 0
            with open(self.dlq_path, "r") as f:
                return sum(1 for line in f if line.strip())
        except: return 0

    def run(self):
        logger.info(f"🚀 Risk-Aware Engine Live | Mode: {self.run_mode}")
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
