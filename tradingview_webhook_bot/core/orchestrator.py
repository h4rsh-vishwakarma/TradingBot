import time, logging, os, json, sys
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

# --- 1. DYNAMIC PATH RESOLUTION (Structural Fix) ---
FILE_PATH = Path(__file__).resolve()
PROJECT_ROOT = FILE_PATH.parents[2] # ~/tradingview_webhook_bot
PACKAGE_ROOT = FILE_PATH.parents[1] # ~/tradingview_webhook_bot/tradingview_webhook_bot

# Path fix taaki saare modules (storage, exchange, etc.) mil sakein
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

# Production secrets path - Override ensures fresh token loading
ENV_VARS_PATH = "/etc/tradingbot/env_vars"
if os.path.exists(ENV_VARS_PATH):
    load_dotenv(dotenv_path=ENV_VARS_PATH, override=True)
else:
    load_dotenv(dotenv_path=PROJECT_ROOT / ".env", override=True)

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
    from tradingview_webhook_bot.alerts.telegram_alerts import TelegramAlert, AlertSeverity
    from tradingview_webhook_bot.recon.reconciler import Reconciler
    from tradingview_webhook_bot.exchange.binance_client import BinanceClient
    from backtesting.engine import BacktestEngine
    try:
        from tradingview_webhook_bot.exchange.hl_client import HyperliquidClient
    except ImportError:
        from tradingview_webhook_bot.exchanges.hl_client import HyperliquidClient
except ImportError as e:
    logger.error(f"❌ Import failed: {e}")
    sys.exit(1)

class Orchestrator:
    def __init__(self):
        # 🛡️ 3. RISK LIMITS & CONFIGURATION
        self.allow_real = os.getenv("ALLOW_REAL_TRADES", "false").lower() == "true"
        self.run_mode = os.getenv("RUN_MODE", "production")
        self.webhook_secret = os.getenv("WEBHOOK_SECRET", "squeeze_tradingview_cluster_2026_secure").strip()
        self.max_notional = float(os.getenv("MAX_NOTIONAL_PER_TRADE", "500.0"))
        self.daily_loss_limit = float(os.getenv("DAILY_LOSS_LIMIT", "-50.0"))

        # --- 📂 FORCED ABSOLUTE PATHS ---
        base_storage = "/home/ubuntu/tradingview_webhook_bot/tradingview_webhook_bot/storage"
        os.makedirs(base_storage, exist_ok=True)

        self.queue_path = f"{base_storage}/signals.jsonl"
        self.offset_path = f"{base_storage}/signals.offset"
        self.ledger_path = f"{base_storage}/ledger_state.json"
        self.idempotency_db = f"{base_storage}/idempotency.db"
        self.dlq_path = f"{base_storage}/dead_letter.jsonl"

        # Components
        self.ledger = PositionLedger(self.ledger_path)
        self.telegram = TelegramAlert() # Initialized with fresh env token
        self.reconciler = Reconciler(self.ledger)
        self.sheets_logger = GoogleSheetsLogger()
        self.consumer = JsonlOffsetConsumer(self.queue_path, self.offset_path)
        self.idempotency = IdempotencyStore(self.idempotency_db)

        # 🏦 Multi-Exchange Clients
        self.exchange_binance = BinanceClient()

        # --- HYPERLIQUID ACTIVATION FIX ---
        try:
            self.exchange_hl = HyperliquidClient()
        except Exception as e:
            logger.error(f"⚠️ HL Client initialization skipped: {e}")
            self.exchange_hl = None

        # 🧠 Brain Component
        self.bt_engine = BacktestEngine()
        self.processed_count = 0
        self.last_heartbeat = time.time()

    def check_safety_gate(self, symbol, qty, price, side, exchange="binance") -> tuple[bool, str]:
        """🛡️ Pre-Trade Risk Validation"""
        if not self.allow_real: return False, "ALLOW_REAL_TRADES is disabled"

        current_pnl = self.ledger.get_daily_pnl()
        if current_pnl <= self.daily_loss_limit:
            return False, f"Daily loss limit hit: ${current_pnl:.2f}"

        current_pos = self.ledger.get_position(f"{exchange}:{symbol}")
        if (side == "BUY" and current_pos.quantity > 0) or (side == "SELL" and current_pos.quantity < 0):
            return False, f"Already in {side} position for {symbol} on {exchange}."

        return True, "Safe"

    def handle_signal(self, event: dict) -> bool:
        """Core signal handler with robust Telegram alerts and execution."""
        try:
            signal_id = event.get("signal_id")
            if self.idempotency.is_seen(signal_id):
                logger.info(f"⏭️ Skipping duplicate: {signal_id}")
                return True

            payload_raw = event.get("payload", {})
            signal_data = {**event, **payload_raw}

            # Force secret for schema compliance
            if "secret" not in signal_data:
                signal_data["secret"] = self.webhook_secret

            # 📝 1. EXTRACTION
            target_exchange = str(payload_raw.get("exchange") or event.get("exchange") or "binance").lower()
            strat_name = payload_raw.get("strategy") or event.get("strategy") or "SMC"
            symbol = str(payload_raw.get("symbol") or event.get("symbol") or "BTCUSDT").upper()
            
            if target_exchange == "hyperliquid":
                symbol = symbol.replace("USDT", "").replace("USD", "")
            else:
                symbol = symbol if "USDT" in symbol else f"{symbol.replace('USD', '').split('_')[0]}USDT"

            try:
                signal_data["strategy"] = strat_name
                signal_data["symbol"] = symbol
                signal_data["quantity"] = float(payload_raw.get("quantity") or event.get("quantity") or 0.003)
                signal_data["price"] = float(payload_raw.get("price") or event.get("price") or 0.0)
                signal_data["action"] = str(payload_raw.get("action") or event.get("action") or "BUY").upper()

                try:
                    valid_payload = SignalPayload(**signal_data)
                    payload = valid_payload.model_dump()
                except Exception:
                    payload = signal_data 
            except Exception as e:
                logger.error(f"❌ Data Parsing Error: {e}")
                return True

            side = "SELL" if payload["action"] in ["SELL", "TP", "EXIT", "SHORT"] else "BUY"
            qty = float(payload["quantity"])
            price_signal = float(payload["price"])
            indicator_name = payload_raw.get("indicator") or "SMC_LuxAlgo"

            # 🧠 2. VALIDATION
            bt_win_rate = self.bt_engine.get_strategy_confidence(strat_name, symbol)

            # 🛡️ 3. RISK GATES
            is_safe, reason = self.check_safety_gate(symbol, qty, price_signal, side, exchange=target_exchange)
            if not is_safe:
                logger.warning(f"🚧 Safety Gate Block: {reason}")
                if "Already in" in reason:
                    # Clean markdown alert for risk block
                    safe_sym = symbol.replace("_", "\\_")
                    msg = (f"🚧 *Safety Gate: Blocked*\n\n"
                           f"🔹 *Symbol:* `{safe_sym}`\n"
                           f"🔹 *Reason:* `{reason}`\n"
                           f"💡 *Action:* Signal skipped to prevent duplication.")
                    try: self.telegram.send(severity=AlertSeverity.WARNING, title="Risk Block", message=msg)
                    except: pass
                return True

            # 🚀 4. EXECUTION
            execution_res = {}
            fill_price = price_signal

            if target_exchange == "hyperliquid":
                if not self.exchange_hl: return True
                res = self.exchange_hl.market_order(symbol, (side == "BUY"), qty)
                if res and res.get('status') == 'ok':
                    execution_res = {"status": "SUCCESS", "order_id": "hl_order"}
                    try: fill_price = float(res['response']['data']['statuses'][0]['filled']['avgPx'])
                    except: pass
                else: execution_res = {"status": "FAILED", "reason": str(res)}
            else:
                execution_res = self.exchange_binance.execute_futures_order(symbol, side, qty, price_signal, signal_id=signal_id)
                if execution_res.get("status") == "SUCCESS":
                    fill_price = float(execution_res.get("avg_price") or price_signal)

            # 📊 5. POST-EXECUTION (Reporting)
            if execution_res.get("status") == "SUCCESS":
                self.idempotency.mark_seen(signal_id)
                pos_snapshot = self.ledger.apply_fill(f"{target_exchange}:{symbol}", side, qty, fill_price)
                realized_pnl = pos_snapshot.daily_realized_pnl
                self.processed_count += 1

                # Log to Sheets
                try:
                    self.sheets_logger.log_trade(
                        signal_id=signal_id, symbol=f"{target_exchange.upper()}:{symbol}",
                        action=side, qty=qty, price=fill_price, strategy=strat_name,
                        indicator=indicator_name, pnl=realized_pnl
                    )
                except Exception as e: logger.error(f"❌ Sheets Error: {e}")

                # 🟢 Professional Telegram Success Alert
                emoji = "🟢" if side == "BUY" else "🔴"
                safe_id = str(signal_id).replace("_", "\\_").replace("-", "\\-")
                
                msg = (
                    f"{emoji} *Bot Alert: Trade Executed*\n\n"
                    f"✅ *Executed:* {side} {symbol}\n"
                    f"💰 *Price:* {fill_price}\n"
                    f"📦 *Qty:* {qty}\n"
                    f"📊 *Indicator:* {indicator_name}\n"
                    f"📈 *BT WinRate:* {bt_win_rate:.2f}\n"
                    f"💵 *Today PnL:* ${realized_pnl:.2f}\n"
                    f"🆔 *ID:* `{safe_id}`"
                )
                
                try:
                    self.telegram.send(severity=AlertSeverity.INFO, title="Trade Success", message=msg)
                    logger.info(f"✅ Alert sent for {signal_id}")
                except Exception as e:
                    logger.error(f"❌ Alert Failed (HTTP 401/Format): {e}")

                return True
            else:
                logger.error(f"❌ Execution Failure: {execution_res.get('reason')}")
                return True

        except Exception as e:
            logger.error(f"❌ Critical Error: {e}")
            return True

    def run(self):
        logger.info(f"🚀 Execution Engine Live | Watching: {self.queue_path}")
        while True:
            self.consumer.poll(handler=self.handle_signal, batch_size=1)
            if time.time() - self.last_heartbeat > 900:
                logger.info(f"💓 Heartbeat | Processed: {self.processed_count}")
                self.last_heartbeat = time.time()
            time.sleep(1)

if __name__ == "__main__":
    Orchestrator().run()
