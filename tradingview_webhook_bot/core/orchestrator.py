import time, logging, os, json, sys, pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

# --- 1. DYNAMIC PATH RESOLUTION ---
FILE_PATH = Path(__file__).resolve()
PROJECT_ROOT = FILE_PATH.parents[2]
PACKAGE_ROOT = FILE_PATH.parents[1]

if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))
if str(PACKAGE_ROOT) not in sys.path: sys.path.insert(0, str(PACKAGE_ROOT))

ENV_VARS_PATH = "/etc/tradingbot/env_vars"
if os.path.exists(ENV_VARS_PATH):
    load_dotenv(dotenv_path=ENV_VARS_PATH, override=True)
else:
    load_dotenv(dotenv_path=PROJECT_ROOT / ".env", override=True)

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
        self.allow_real = os.getenv("ALLOW_REAL_TRADES", "false").lower() == "true"
        self.run_mode = os.getenv("RUN_MODE", "production")
        self.webhook_secret = os.getenv("WEBHOOK_SECRET", "squeeze_tradingview_cluster_2026_secure").strip()
        self.max_notional = float(os.getenv("MAX_NOTIONAL_PER_TRADE", "500.0"))
        self.daily_loss_limit = float(os.getenv("DAILY_LOSS_LIMIT", "-50.0"))

        base_storage = "/home/ubuntu/tradingview_webhook_bot/tradingview_webhook_bot/storage"
        os.makedirs(base_storage, exist_ok=True)

        self.queue_path = f"{base_storage}/signals.jsonl"
        self.offset_path = f"{base_storage}/signals.offset"
        self.ledger_path = f"{base_storage}/ledger_state.json"
        self.idempotency_db = f"{base_storage}/idempotency.db"
        self.dlq_path = f"{base_storage}/dead_letter.jsonl"
        self.report_path = "/home/ubuntu/tradingview_webhook_bot/storage/reports/tournament_winners.csv"

        self.ledger = PositionLedger(self.ledger_path)
        self.telegram = TelegramAlert()
        self.reconciler = Reconciler(self.ledger)
        self.sheets_logger = GoogleSheetsLogger()
        self.consumer = JsonlOffsetConsumer(self.queue_path, self.offset_path)
        self.idempotency = IdempotencyStore(self.idempotency_db)
        self.exchange_binance = BinanceClient()

        try:
            if os.getenv("HL_WALLET_ADDRESS") and os.getenv("HL_PRIVATE_KEY"):
                self.exchange_hl = HyperliquidClient()
            else:
                logger.warning("⚠️ HL Credentials missing in env_vars")
                self.exchange_hl = None
        except Exception as e:
            logger.error(f"⚠️ HL Client initialization failed: {e}")
            self.exchange_hl = None

        self.bt_engine = BacktestEngine()
        self.processed_count = 0
        self.last_heartbeat = time.time()

    def check_tournament_alpha(self, symbol, strategy_name) -> tuple[bool, str, str]:
        if not os.path.exists(self.report_path):
            return True, "No report found, allowing", "ALPHA"
        try:
            df = pd.read_csv(self.report_path)
            match = df[(df['Symbol'].str.contains(symbol, case=False)) & (df['Strategy'].str.contains(strategy_name, case=False))]
            if match.empty:
                return False, f"Strategy {strategy_name} for {symbol} not in Leaderboard.", "NONE"
            row = match.iloc[0]
            tier = str(row.get('Tier', ''))
            if "ALPHA" in tier: return True, "Verified ALPHA: Direct Execution", "ALPHA"
            if "AVERAGE" in tier: return True, "Verified AVERAGE: Human Approval Needed", "AVERAGE"
            return False, f"Strategy Tier is {tier}. Blocked.", tier
        except Exception as e:
            logger.error(f"❌ Leaderboard Check Error: {e}")
            return True, "Error in check, allowing", "ALPHA"

    def check_safety_gate(self, symbol, qty, price, side, exchange="binance") -> tuple[bool, str]:
        if not self.allow_real: return False, "ALLOW_REAL_TRADES is disabled"
        current_pnl = self.ledger.get_daily_pnl()
        if current_pnl <= self.daily_loss_limit:
            return False, f"Daily loss limit hit: ${current_pnl:.2f}"
        current_pos = self.ledger.get_position(f"{exchange}:{symbol}")
        if (side == "BUY" and current_pos.quantity > 0) or (side == "SELL" and current_pos.quantity < 0):
            return False, f"Already in {side} position for {symbol} on {exchange}."
        return True, "Safe"

    def handle_signal(self, event: dict) -> bool:
        try:
            signal_id = event.get("signal_id")
            if self.idempotency.is_seen(signal_id):
                logger.info(f"⏭️ Skipping duplicate: {signal_id}")
                return True

            payload_raw = event.get("payload", {})
            signal_data = {**event, **payload_raw}
            if "secret" not in signal_data:
                signal_data["secret"] = self.webhook_secret

            target_exchange = str(payload_raw.get("exchange") or event.get("exchange") or "binance").lower()
            strat_name = payload_raw.get("strategy") or event.get("strategy") or "SMC"
            symbol_raw = str(payload_raw.get("symbol") or event.get("symbol") or "BTCUSDT").upper()

            # --- 🛠️ FIX 1: SYMBOL CLEANING ---
            symbol = symbol_raw.split('_')[0]
            if target_exchange == "hyperliquid":
                symbol = symbol.replace("USDT", "").replace("USD", "")
            else:
                symbol = symbol if "USDT" in symbol else f"{symbol.replace('USD', '')}USDT"

            # --- 🧠 1. BRAIN TIER CHECK ---
            is_allowed, reason, tier = self.check_tournament_alpha(symbol, strat_name)
            if not is_allowed:
                logger.warning(f"🚫 AI Blocked: {reason}")
                return True

            # --- 🛡️ 2. ROI GUARD (NEW) ---
            try:
                # Extract ROI from the nested strategy string (JSON within JSON)
                strat_info = json.loads(payload_raw.get("strategy", "{}"))
                incoming_roi = float(strat_info.get("ROI", "0").replace("%", ""))
                logger.info(f"📊 Signal ROI Check for {symbol}: {incoming_roi}%")
                
                if incoming_roi <= 0:
                    logger.warning(f"🚫 ROI Guard: Signal blocked ({incoming_roi}%)")
                    msg = (f"🛡️ <b>ROI Guard: Blocked</b>\n\n"
                           f"🔹 <b>Symbol:</b> {symbol}\n"
                           f"📉 <b>1Y ROI:</b> {incoming_roi}%\n"
                           f"⚠️ Negative history. Capital protected.")
                    try: self.telegram.send(severity=AlertSeverity.WARNING, title="Negative ROI Block", message=msg)
                    except: pass
                    return True
            except Exception as e:
                logger.debug(f"ROI Check skipped or failed: {e}")

            # --- ⚖️ 3. TIER-BASED INTERACTIVE GATE ---
            if "AVERAGE" in tier:
                logger.info(f"⚖️ AVERAGE Signal: Waiting for approval for {symbol}")
                msg = (f"⚖️ <b>AVERAGE Strategy Alert</b>\n\n"
                       f"🔹 <b>Symbol:</b> `{symbol}`\n"
                       f"🔹 <b>Strategy:</b> `{strat_name}`\n"
                       f"⚠️ Strategy is AVERAGE. No auto-trade.\n"
                       f"🆔 <b>ID:</b> `{signal_id}`")
                try: self.telegram.send(severity=AlertSeverity.WARNING, title="Manual Sync Needed", message=msg)
                except: pass
                return True

            # --- 🧠 4. PREPARE EXECUTION DATA ---
            try:
                signal_data["strategy"] = strat_name
                signal_data["symbol"] = symbol
                signal_data["quantity"] = float(payload_raw.get("quantity") or event.get("quantity") or 0.003)
                
                raw_price = float(payload_raw.get("price") or event.get("price") or 0.0)
                signal_data["price"] = raw_price if raw_price > 0 else 0.0 
                signal_data["action"] = str(payload_raw.get("action") or event.get("action") or "BUY").upper()

                valid_payload = SignalPayload(**signal_data)
                payload = valid_payload.model_dump()
            except Exception as e:
                logger.error(f"❌ Data Parsing Error: {e}"); return True

            side = "SELL" if payload["action"] in ["SELL", "TP", "EXIT", "SHORT", "OFF"] else "BUY"
            qty, price_signal = float(payload["quantity"]), float(payload["price"])
            indicator_name = payload_raw.get("indicator") or "AI_Optimized"

            # --- 🛡️ 5. RISK GATES ---
            is_safe, risk_reason = self.check_safety_gate(symbol, qty, price_signal, side, exchange=target_exchange)
            if not is_safe:
                logger.warning(f"🚧 Safety Gate Block: {risk_reason}")
                msg = (f"🚧 <b>Safety Gate: Blocked</b>\n\n"
                       f"🔹 <b>Symbol:</b> `{symbol}`\n"
                       f"🔹 <b>Reason:</b> `{risk_reason}`")
                try: self.telegram.send(severity=AlertSeverity.WARNING, title="Risk Block", message=msg)
                except: pass
                return True

            # --- 🚀 6. ACTUAL EXECUTION ---
            execution_res, fill_price = {}, price_signal
            if target_exchange == "hyperliquid":
                if not self.exchange_hl: return True
                res = self.exchange_hl.market_order(symbol, (side == "BUY"), qty)
                if res and res.get('status') == 'ok':
                    execution_res = {"status": "SUCCESS"}
                    try: fill_price = float(res['response']['data']['statuses'][0]['filled']['avgPx'])
                    except: pass
                else: execution_res = {"status": "FAILED", "reason": str(res)}
            else:
                execution_res = self.exchange_binance.execute_futures_order(symbol, side, qty, price_signal, signal_id=signal_id)
                if execution_res.get("status") == "SUCCESS":
                    fill_price = float(execution_res.get("avg_price") or price_signal)

            # --- 📊 7. LOGGING & ALERTS ---
            if execution_res.get("status") == "SUCCESS":
                self.idempotency.mark_seen(signal_id)
                pos_snapshot = self.ledger.apply_fill(f"{target_exchange}:{symbol}", side, qty, fill_price)
                self.processed_count += 1
                try:
                    self.sheets_logger.log_trade(signal_id=signal_id, symbol=f"{target_exchange.upper()}:{symbol}",
                        action=side, qty=qty, price=fill_price, strategy=strat_name, indicator=indicator_name, pnl=pos_snapshot.daily_realized_pnl)
                except: pass

                emoji = "🟢" if side == "BUY" else "🔴"
                msg = (f"{emoji} <b>Bot Alert: Trade Executed</b>\n\n"
                       f"✅ <b>Executed:</b> {side} {symbol}\n"
                       f"💰 <b>Price:</b> {fill_price}\n"
                       f"📈 <b>BT Status:</b> Verified ALPHA\n"
                       f"💵 <b>Today PnL:</b> ${pos_snapshot.daily_realized_pnl:.2f}")
                try: self.telegram.send(severity=AlertSeverity.INFO, title="Trade Success", message=msg)
                except: pass
                return True
            else:
                logger.error(f"❌ Execution Failure: {execution_res.get('reason')}")
                return True

        except Exception as e:
            logger.error(f"❌ Critical Error in handle_signal: {e}"); return True

    def run(self):
        logger.info(f"🚀 Execution Engine Live | Dynamic Brain Mode ACTIVE")
        while True:
            self.consumer.poll(handler=self.handle_signal, batch_size=1)
            if time.time() - self.last_heartbeat > 900:
                logger.info(f"💓 Heartbeat: Orchestrator is running. Processed: {self.processed_count}")
                self.last_heartbeat = time.time()
            time.sleep(1)

if __name__ == "__main__":
    Orchestrator().run()
