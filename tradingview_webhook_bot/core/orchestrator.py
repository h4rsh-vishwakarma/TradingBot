import time, logging, os, json, sys
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

# --- 1. DYNAMIC PATH RESOLUTION ---
FILE_PATH = Path(__file__).resolve()
PROJECT_ROOT = FILE_PATH.parents[2] 

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Production secrets path
ENV_VARS_PATH = "/etc/tradingbot/env_vars"
if os.path.exists(ENV_VARS_PATH):
    load_dotenv(dotenv_path=ENV_VARS_PATH)
else:
    load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

# --- 2. LOGGING CONFIGURATION ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Core & Backtesting Imports
try:
    from tradingview_webhook_bot.storage.idempotency_store import IdempotencyStore
    from tradingview_webhook_bot.core.schemas import SignalPayload
    from tradingview_webhook_bot.storage.sheets_logger import GoogleSheetsLogger
    from tradingview_webhook_bot.storage.jsonl_consumer import JsonlOffsetConsumer
    from tradingview_webhook_bot.ledger.positions import PositionLedger
    from tradingview_webhook_bot.alerts.router import AlertRouter
    from tradingview_webhook_bot.recon.reconciler import Reconciler
    from tradingview_webhook_bot.exchange.binance_client import BinanceClient
    from backtesting.engine import BacktestEngine
except ImportError as e:
    logger.error(f"❌ Import failed, trying direct fallback: {e}")
    from storage.idempotency_store import IdempotencyStore
    from core.schemas import SignalPayload
    from storage.sheets_logger import GoogleSheetsLogger
    from storage.jsonl_consumer import JsonlOffsetConsumer
    from ledger.positions import PositionLedger
    from alerts.router import AlertRouter
    from recon.reconciler import Reconciler
    from exchange.binance_client import BinanceClient
    from backtesting.engine import BacktestEngine

class Orchestrator:
    def __init__(self):
        # 🛡️ 3. RISK LIMITS & CONFIGURATION
        self.allow_real = os.getenv("ALLOW_REAL_TRADES", "false").lower() == "true"
        self.run_mode = os.getenv("RUN_MODE", "production")

        self.max_notional = float(os.getenv("MAX_NOTIONAL_PER_TRADE", "500.0"))
        self.daily_loss_limit = float(os.getenv("DAILY_LOSS_LIMIT", "-50.0"))
        self.allowed_symbols = os.getenv("ALLOWED_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",")

        storage_dir = PROJECT_ROOT / "tradingview_webhook_bot" / "storage"
        storage_dir.mkdir(parents=True, exist_ok=True)

        self.dlq_path = str(storage_dir / "dead_letter.jsonl")
        self.idempotency_db = str(storage_dir / "idempotency.db")
        self.ledger_path = str(storage_dir / "ledger_state.json")
        self.alerts_log = str(storage_dir / "alerts.jsonl")
        self.queue_path = str(storage_dir / "signals.jsonl")
        self.offset_path = str(storage_dir / "signals.offset")

        # Components
        self.ledger = PositionLedger(self.ledger_path)
        self.alerts = AlertRouter(self.alerts_log)
        self.reconciler = Reconciler(self.ledger)
        self.sheets_logger = GoogleSheetsLogger()
        self.consumer = JsonlOffsetConsumer(self.queue_path, self.offset_path)
        self.exchange = BinanceClient()
        self.idempotency = IdempotencyStore(self.idempotency_db)
        
        # 🧠 Brain Component: Hybrid Validator
        self.bt_engine = BacktestEngine()

        self.processed_count = 0
        self.last_heartbeat = time.time()

    def check_safety_gate(self, symbol, qty, price, side) -> tuple[bool, str]:
        """🛡️ Pre-Trade Risk Validation"""
        if not self.allow_real: return False, "ALLOW_REAL_TRADES is disabled"

        current_pnl = self.ledger.get_daily_pnl()
        if current_pnl <= self.daily_loss_limit:
            return False, f"Daily loss limit hit: ${current_pnl:.2f}"

        current_pos = self.ledger.get_position(symbol)
        if (side == "BUY" and current_pos.quantity > 0) or (side == "SELL" and current_pos.quantity < 0):
            return False, f"Already in {side} position for {symbol}."

        return True, "Safe"

    def handle_signal(self, event: dict) -> bool:
        """Core signal handler with Hybrid Validation and Robust Extraction."""
        try:
            signal_id = event.get("signal_id")
            if self.idempotency.is_seen(signal_id):
                logger.info(f"⏭️ Skipping duplicate: {signal_id}")
                return True

            payload_raw = event.get("payload", {})

            # 📝 1. SMART EXTRACTION & DYNAMIC MAPPING
            try:
                # Merge main event and nested payload
                signal_data = {**event, **payload_raw}

                # Priority Extraction for Strategy
                strat_name = payload_raw.get("strategy") or event.get("strategy") or \
                             payload_raw.get("strategy_id") or event.get("strategy_id") or "SMC"
                
                # Dynamic Symbol Cleaning (e.g., ETHUSDH2026 -> ETHUSDT)
                raw_sym = str(payload_raw.get("symbol") or event.get("symbol") or "BTCUSDT").upper()
                symbol = raw_sym if "USDT" in raw_sym else f"{raw_sym.replace('USD', '').split('_')[0]}USDT"

                signal_data["strategy"] = strat_name
                signal_data["symbol"] = symbol
                signal_data["quantity"] = float(payload_raw.get("quantity") or event.get("quantity") or 0.003)
                signal_data["price"] = float(payload_raw.get("price") or event.get("price") or 0.0)
                signal_data["action"] = str(payload_raw.get("action") or event.get("action") or "BUY").upper()

                # Validate with Pydantic
                valid_payload = SignalPayload(**signal_data)
                payload = valid_payload.model_dump()
                payload["strategy"] = strat_name # Override ensure

            except Exception as schema_err:
                logger.error(f"❌ Schema Validation Failed: {schema_err}")
                self.move_to_dlq(event, f"Schema Error: {schema_err}")
                return True

            # 🛡️ 2. MAPPING & EXTRACTION
            side = "SELL" if payload["action"] in ["SELL", "TP", "EXIT", "SHORT", "TP"] else "BUY"
            qty = float(payload["quantity"])
            price_from_signal = float(payload["price"])
            strat_id = payload["strategy"]
            indicator_name = payload_raw.get("indicator") or "SMC_LuxAlgo"

            # 🧠 3. HYBRID VALIDATION GATE (CSV + Ledger)
            bt_win_rate = self.bt_engine.get_strategy_confidence(strat_id, symbol)
            is_bt_valid, confidence_score = self.bt_engine.validate_signal(strat_id, symbol, self.ledger)

            if not is_bt_valid:
                logger.warning(f"🚫 HYBRID REJECTED: {strat_id} | Score: {confidence_score:.2f}")
                self.alerts.send(
                    f"🚧 *Hybrid Risk Block*\n\n"
                    f"📍 *Symbol:* {symbol}\n"
                    f"📈 *BT WinRate:* {bt_win_rate:.2f}\n"
                    f"⚖️ *Hybrid Score:* {confidence_score:.2f}\n"
                    f"⚠️ Below {self.bt_engine.min_win_rate} Threshold",
                    severity="LOW"
                )
                return True

            # 🛡️ 4. RISK GATES
            is_safe, reason = self.check_safety_gate(symbol, qty, price_from_signal, side)
            if not is_safe:
                if "Already in" not in reason:
                    self.alerts.send(f"🚧 *Safety Gate Block:* {symbol}\nReason: {reason}", severity="WARNING")
                return True

            # 🚀 5. EXECUTION
            execution_res = self.exchange.execute_futures_order(symbol, side, qty, price_from_signal, signal_id=signal_id)

            if execution_res.get("status") == "SUCCESS":
                self.idempotency.mark_seen(signal_id, client_order_id=execution_res.get("order_id", "manual"))

                # ⭐ THE NO-ZERO PRICE LOGIC (Weighted Average from Fills)
                fill_price = 0.0
                fills = execution_res.get("fills", [])
                
                if fills:
                    # Layer 1: Calculate from Binance Fills array
                    total_qty = sum(float(f.get('qty', 0)) for f in fills)
                    total_cost = sum(float(f.get('price', 0)) * float(f.get('qty', 0)) for f in fills)
                    fill_price = round(total_cost / total_qty, 2) if total_qty > 0 else 0.0
                
                if fill_price == 0.0:
                    # Layer 2: Check avg_price field in root response
                    fill_price = float(execution_res.get("avg_price") or execution_res.get("price") or 0.0)
                
                if fill_price == 0.0:
                    # Layer 3: Use the price from the signal as last resort
                    fill_price = price_from_signal
                
                if fill_price == 0.0:
                    # Layer 4: Emergency - fetch ticker price
                    try:
                        ticker = self.exchange.client.futures_symbol_ticker(symbol=symbol)
                        fill_price = float(ticker.get('price', 0.0))
                    except:
                        fill_price = 0.0

                # Update Ledger
                pos_snapshot = self.ledger.apply_fill(symbol, side, qty, fill_price)
                realized_pnl = pos_snapshot.daily_realized_pnl
                self.processed_count += 1

                # 📊 LOGGING
                self.sheets_logger.log_trade(
                    signal_id=signal_id, symbol=symbol, action=side, qty=qty,
                    price=fill_price, strategy=strat_id, indicator=indicator_name, pnl=realized_pnl
                )

                # 🟢 Mixed Style Professional Notification
                emoji = "🟢" if side == "BUY" else "🔴"
                msg = (
                    f"{emoji} *Bot Alert: Trade Executed*\n\n"
                    f"✅ *Executed:* {side} {symbol}\n"
                    f"💰 *Price:* {fill_price}\n"
                    f"📦 *Qty:* {qty}\n"
                    f"📊 *Indicator:* {indicator_name}\n"
                    f"📈 *BT WinRate:* {bt_win_rate:.2f}\n"
                    f"⚖️ *Hybrid Score:* {confidence_score:.2f}\n"
                    f"💵 *Today PnL:* ${realized_pnl:.2f}\n"
                    f"🆔 *ID:* {signal_id}"
                )
                self.alerts.send(msg, channel="TRADES")
                return True
            else:
                reason = execution_res.get("reason", "unknown_api")
                logger.error(f"❌ Execution Failed: {symbol} - {reason}")
                self.move_to_dlq(event, f"Exchange Failure: {reason}")
                return True

        except Exception as e:
            logger.error(f"❌ Critical Error: {e}")
            self.move_to_dlq(event, str(e))
            return True

    def move_to_dlq(self, event, error):
        try:
            with open(self.dlq_path, "a") as f:
                f.write(json.dumps({"ts": datetime.now().isoformat(), "err": error, "event": event}) + "\n")
        except: pass

    def run(self):
        logger.info(f"🚀 Risk-Aware Hybrid Engine Live | Mode: {self.run_mode}")
        last_recon = time.time()
        while True:
            self.consumer.poll(handler=self.handle_signal, batch_size=5)
            current_time = time.time()
            if current_time - self.last_heartbeat > 900:
                logger.info(f"💓 Heartbeat | Processed: {self.processed_count}")
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
    Orchestrator().run()
