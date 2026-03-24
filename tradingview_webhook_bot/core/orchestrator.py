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

        # --- FIX: Anti Flip-Flop Cooldown ---
        # After executing a trade on a symbol, block further trades for COOLDOWN seconds
        self._symbol_cooldown = {}  # {symbol: last_trade_timestamp}
        self.COOLDOWN_SECONDS = 300  # 5 min cooldown - prevents flip-flop across strategies

        # --- FIX: Signal Deduplication (JSON + Plain Text duplicates) ---
        # Track recent signals by strategy+symbol+side to block duplicates within window
        self._recent_signals = {}  # {"strategy:symbol:side": timestamp}
        self.DEDUP_WINDOW_SECONDS = 120  # 2 min dedup - blocks duplicate JSON+PlainText signals

        # --- FIX: Per-Candle Signal Lock (First Signal Wins Per Symbol) ---
        self._candle_lock = {}  # {symbol: {"side": str, "time": float, "strategy": str}}
        self.CANDLE_LOCK_SECONDS = 3600  # 1 hour lock (matches hourly candle)

    def _is_candle_locked(self, symbol: str, side: str) -> bool:
        lock = self._candle_lock.get(symbol)
        if not lock:
            return False
        elapsed = time.time() - lock["time"]
        if elapsed >= self.CANDLE_LOCK_SECONDS:
            del self._candle_lock[symbol]
            return False
        if lock["side"] != side:
            logger.info(f"Candle Lock: {symbol} locked to {lock.get('side', '')} by {lock.get('strategy', '')} ({self.CANDLE_LOCK_SECONDS - elapsed:.0f}s left). Blocking {side}.")
            return True
        return False

    def _set_candle_lock(self, symbol: str, side: str, strategy: str):
        self._candle_lock[symbol] = {"side": side, "time": time.time(), "strategy": strategy}
        logger.info(f"🔒 Candle locked: {symbol} -> {side} by {strategy} for {self.CANDLE_LOCK_SECONDS}s")

    def _is_symbol_in_cooldown(self, symbol: str) -> bool:
        """Check if symbol is in cooldown period after recent trade."""
        last_trade = self._symbol_cooldown.get(symbol, 0)
        elapsed = time.time() - last_trade
        if elapsed < self.COOLDOWN_SECONDS:
            logger.info(f"⏳ Cooldown active for {symbol}: {self.COOLDOWN_SECONDS - elapsed:.0f}s remaining")
            return True
        return False

    def _mark_symbol_traded(self, symbol: str):
        """Mark symbol as recently traded (starts cooldown)."""
        self._symbol_cooldown[symbol] = time.time()

    def _is_duplicate_signal(self, strategy: str, symbol: str, side: str) -> bool:
        """Check if same strategy+symbol+side was seen within dedup window."""
        key = f"{strategy}:{symbol}:{side}".lower()
        now = time.time()
        last_seen = self._recent_signals.get(key, 0)
        if now - last_seen < self.DEDUP_WINDOW_SECONDS:
            logger.info(f"🔁 Duplicate signal blocked: {strategy} {side} {symbol} (seen {now - last_seen:.0f}s ago)")
            return True
        self._recent_signals[key] = now
        # Cleanup old entries every 100 signals
        if len(self._recent_signals) > 200:
            cutoff = now - self.DEDUP_WINDOW_SECONDS * 2
            self._recent_signals = {k: v for k, v in self._recent_signals.items() if v > cutoff}
        return False

    def check_tournament_alpha(self, symbol, strategy_name) -> tuple[bool, str, str]:
        if not os.path.exists(self.report_path):
            return True, "No report found, allowing", "ALPHA"
        try:
            df = pd.read_csv(self.report_path)
            # Normalize: underscores <-> spaces for fuzzy matching
            import re as _re
            def _normalize(s):
                # Strip underscores, quotes, brackets, +, commas, hyphens for fuzzy matching
                s = str(s)
                for ch in ['_', "'", '"', '[', ']', '+', ',', '-', '|']:
                    s = s.replace(ch, ' ')
                return _re.sub(r"\s+", " ", s).strip().lower()
            strat_clean = _normalize(strategy_name)
            def _strat_match(row_strat):
                row_clean = _normalize(row_strat)
                return strat_clean in row_clean or row_clean in strat_clean
            match = df[(df['Symbol'].str.contains(symbol, case=False)) & (df['Strategy'].apply(_strat_match))]
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
            # Strip suffixes like _PREMIUM, _PERP, _SPOT
            symbol = symbol_raw.split('_')[0]
            # Ensure proper format per exchange
            if target_exchange == "hyperliquid":
                symbol = symbol.replace("USDT", "").replace("USD", "")
            else:
                if "USDT" not in symbol:
                    symbol = f"{symbol.replace('USD', '')}USDT"

            # --- 🧠 1. BRAIN TIER CHECK ---
            is_allowed, reason, tier = self.check_tournament_alpha(symbol, strat_name)
            if not is_allowed:
                logger.warning(f"🚫 AI Blocked: {reason}")
                try:
                    self.sheets_logger.log_blocked_trade(
                        symbol=symbol, side="N/A", strategy=strat_name,
                        reason=f"Tier Block: {reason}", signal_id=signal_id)
                except Exception:
                    pass
                return True

            # --- 🔁 1.5. SIGNAL DEDUP CHECK (JSON + Plain Text duplicates) ---
            side_hint = str(payload_raw.get("action") or event.get("action") or "").upper()
            if self._is_duplicate_signal(strat_name, symbol, side_hint):
                logger.info(f"🔁 Blocked duplicate: {strat_name} {side_hint} {symbol}")
                return True

            # --- ⏳ 1.6. SYMBOL COOLDOWN CHECK (Anti Flip-Flop) ---
            if self._is_symbol_in_cooldown(symbol):
                logger.info(f"⏳ Cooldown block: {symbol} (strategy: {strat_name})")
                return True

            # --- 🔒 1.7. CANDLE LOCK (First Signal Wins Per Symbol) ---
            if self._is_candle_locked(symbol, side_hint):
                logger.info(f"🔒 Candle lock block: {symbol} {side_hint} (strategy: {strat_name})")
                try:
                    self.sheets_logger.log_blocked_trade(
                        symbol=symbol, side=side_hint, strategy=strat_name,
                        reason=f"Candle Lock: Symbol locked to opposite direction", signal_id=signal_id)
                except Exception:
                    pass
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
                    try:
                        self.sheets_logger.log_blocked_trade(
                            symbol=symbol, side="N/A", strategy=strat_name,
                            reason=f"ROI Guard: {incoming_roi}% (Negative)", signal_id=signal_id)
                    except Exception:
                        pass
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
                if raw_price <= 0:
                    logger.warning(f"🚫 Invalid price {raw_price} for {symbol}. Skipping.")
                    return True
                signal_data["price"] = raw_price
                signal_data["action"] = str(payload_raw.get("action") or event.get("action") or "BUY").upper()

                valid_payload = SignalPayload(**signal_data)
                payload = valid_payload.model_dump()
            except Exception as e:
                logger.error(f"❌ Data Parsing Error: {e}"); return True

            side = "SELL" if payload["action"] in ["SELL", "TP", "EXIT", "SHORT", "OFF"] else "BUY"
            qty, price_signal = float(payload["quantity"]), float(payload["price"])
            indicator_name = payload_raw.get("indicator") or "AI_Optimized"

            # --- 🔄 4.5. EXIT/CLOSE HANDLING (strategy.close() sends position=0) ---
            is_exit = payload_raw.get("is_exit", False)
            if is_exit:
                current_pos = self.ledger.get_position(f"{target_exchange}:{symbol}")
                if current_pos.quantity == 0:
                    logger.info(f"🔄 Exit signal for {symbol} but no position open. Skipping.")
                    return True
                # Close existing position: if long, sell; if short, buy
                if current_pos.quantity > 0:
                    side = "SELL"
                    qty = abs(current_pos.quantity)
                elif current_pos.quantity < 0:
                    side = "BUY"
                    qty = abs(current_pos.quantity)
                logger.info(f"🔄 Exit signal: closing {symbol} position ({current_pos.quantity}) with {side} {qty}")

            # --- 🛡️ 5. RISK GATES (skip position conflict check for exit signals) ---
            if is_exit:
                # Exit signals bypass position conflict check (closing IS the intended action)
                if not self.allow_real:
                    is_safe, risk_reason = False, "ALLOW_REAL_TRADES is disabled"
                else:
                    is_safe, risk_reason = True, "Exit signal - closing position"
            else:
                is_safe, risk_reason = self.check_safety_gate(symbol, qty, price_signal, side, exchange=target_exchange)
            if not is_safe:
                logger.warning(f"🚧 Safety Gate Block: {risk_reason}")
                msg = (f"🚧 <b>Safety Gate: Blocked</b>\n\n"
                       f"🔹 <b>Symbol:</b> `{symbol}`\n"
                       f"🔹 <b>Reason:</b> `{risk_reason}`")
                try: self.telegram.send(severity=AlertSeverity.WARNING, title="Risk Block", message=msg)
                except: pass
                try:
                    self.sheets_logger.log_blocked_trade(
                        symbol=symbol, side=side, strategy=strat_name,
                        reason=f"Safety Gate: {risk_reason}", signal_id=signal_id)
                except Exception:
                    pass
                return True

            # --- 🛡️ 5.5. MAX QUANTITY CAP (Prevent oversized positions) ---
            MAX_QTY = {"SOLUSDT": 1.0, "ETHUSDT": 0.05, "BTCUSDT": 0.003}
            max_allowed = MAX_QTY.get(symbol, 1.0)
            if qty > max_allowed:
                logger.warning(f"📐 Qty capped: {qty} -> {max_allowed} for {symbol}")
                qty = max_allowed

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
                self._mark_symbol_traded(symbol)  # Start cooldown for this symbol
                self._set_candle_lock(symbol, side, strat_name)  # Lock direction for candle
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
                exec_reason = execution_res.get('reason', 'Unknown API Error')
                exec_msg = execution_res.get('msg', '')
                logger.error(f"❌ Execution Failure: {exec_reason} | Detail: {exec_msg}")
                try:
                    self.sheets_logger.log_blocked_trade(
                        symbol=symbol, side=side, strategy=strat_name,
                        reason=f"Execution Failed: {exec_reason}", signal_id=signal_id)
                except Exception:
                    pass
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
