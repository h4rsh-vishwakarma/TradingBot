import time, logging, os, json, sys, signal as _signal, pandas as pd
from concurrent.futures import ThreadPoolExecutor
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
    from tradingview_webhook_bot.storage.analytics_writer import AnalyticsWriter
    from tradingview_webhook_bot.storage.jsonl_consumer import JsonlOffsetConsumer
    from tradingview_webhook_bot.storage.signal_queue import DurableSignalQueue
    from tradingview_webhook_bot.ledger.positions import PositionLedger
    from tradingview_webhook_bot.alerts.telegram_alerts import TelegramAlert, AlertSeverity
    from tradingview_webhook_bot.recon.reconciler import Reconciler
    from tradingview_webhook_bot.exchange.binance_client import BinanceClient
    from tradingview_webhook_bot.core.circuit_breaker import CircuitBreaker
    from backtesting.engine import BacktestEngine
    from tradingview_webhook_bot.exchange.hl_client import HyperliquidClient
    from tradingview_webhook_bot.exchange.lighter_client import LighterClient
except ImportError as e:
    logger.error(f"Import failed: {e}")
    sys.exit(1)


class Orchestrator:
    def __init__(self):
        self.allow_real = os.getenv("ALLOW_REAL_TRADES", "false").lower() == "true"
        self.run_mode = os.getenv("RUN_MODE", "production")
        self.webhook_secret = os.getenv("WEBHOOK_SECRET", "").strip()
        if not self.webhook_secret:
            logger.warning("WEBHOOK_SECRET not configured — secret validation disabled")
        self.max_notional = float(os.getenv("MAX_NOTIONAL_PER_TRADE", "500.0"))
        self.daily_loss_limit = float(os.getenv("DAILY_LOSS_LIMIT", "-50.0"))

        # Storage paths — configurable via env
        base_storage = os.getenv("BOT_STORAGE_PATH",
            str(PROJECT_ROOT / "tradingview_webhook_bot" / "storage"))
        os.makedirs(base_storage, exist_ok=True)

        self.queue_path = os.path.join(base_storage, "signals.jsonl")
        self.offset_path = os.path.join(base_storage, "signals.offset")
        self.ledger_path = os.path.join(base_storage, "ledger_state.json")
        self.idempotency_db = os.path.join(base_storage, "idempotency.db")
        self.dlq_path = os.path.join(base_storage, "dead_letter.jsonl")
        self.report_path = os.getenv("TOURNAMENT_REPORT_PATH",
            str(PROJECT_ROOT / "storage" / "reports" / "tournament_winners.csv"))

        self.ledger = PositionLedger(self.ledger_path)
        self.telegram = TelegramAlert()
        self.reconciler = Reconciler(self.ledger)
        self.sheets_logger = GoogleSheetsLogger()
        self.analytics = AnalyticsWriter()

        # Dual queue: SQLite (primary, durable) + JSONL (legacy fallback)
        self.queue_db_path = os.path.join(base_storage, "signal_queue.db")
        self.durable_queue = DurableSignalQueue(self.queue_db_path, max_retries=3)
        self.consumer = JsonlOffsetConsumer(self.queue_path, self.offset_path)
        self.use_durable_queue = os.getenv("USE_DURABLE_QUEUE", "true").lower() == "true"
        self.idempotency = IdempotencyStore(self.idempotency_db)
        self.exchange_binance = BinanceClient()

        try:
            if os.getenv("HL_WALLET_ADDRESS") and os.getenv("HL_PRIVATE_KEY"):
                self.exchange_hl = HyperliquidClient()
            else:
                self.exchange_hl = None
        except Exception as e:
            logger.warning(f"HL Client initialization failed: {e}")
            self.exchange_hl = None

        try:
            lighter_key = os.getenv("LIGHTER_API_PRIVATE_KEY") or os.getenv("LIGHTER_PRIVATE_KEY")
            if lighter_key:
                self.exchange_lighter = LighterClient()
                logger.info("Lighter client initialized [%s]",
                            "TESTNET" if self.exchange_lighter.is_testnet else "MAINNET")
            else:
                self.exchange_lighter = None
                logger.info("Lighter client disabled — LIGHTER_PRIVATE_KEY not set")
        except Exception as e:
            logger.warning(f"Lighter Client initialization failed: {e}")
            self.exchange_lighter = None

        self.bt_engine = BacktestEngine()
        self.processed_count = 0
        self._thread_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix='sheets')
        self.last_heartbeat = time.time()
        self._exec_lock_path = os.path.join(base_storage, "execution_locks.json")
        self._load_exec_locks()

        # Circuit Breaker
        cb_state = os.path.join(base_storage, "circuit_breaker_state.json")
        cb_config = {
            "daily_loss_limit_pct": float(os.getenv("CB_DAILY_LOSS_PCT", "5.0")),
            "max_consecutive_losses": int(os.getenv("CB_MAX_CONSECUTIVE_LOSSES", "8")),
            "cooldown_minutes": int(os.getenv("CB_COOLDOWN_MINUTES", "60")),
        }
        try:
            self.circuit_breaker = CircuitBreaker(cb_state, cb_config)
            logger.info("Circuit Breaker initialized")
        except Exception as e:
            logger.warning(f"Circuit Breaker init failed: {e}")
            self.circuit_breaker = None

        # Anti Flip-Flop controls — all configurable via env
        self._symbol_cooldown = {}
        self.COOLDOWN_SECONDS = int(os.getenv("SYMBOL_COOLDOWN_SECONDS", "300"))
        self._recent_signals = {}
        self.DEDUP_WINDOW_SECONDS = int(os.getenv("DEDUP_WINDOW_SECONDS", "120"))
        self._candle_lock = {}
        self.CANDLE_LOCK_SECONDS = int(os.getenv("CANDLE_LOCK_SECONDS", "3600"))

        # Max qty caps — configurable via env (JSON format)
        default_max_qty = '{"SOLUSDT": 1.0, "ETHUSDT": 0.05, "BTCUSDT": 0.003}'
        self.MAX_QTY = json.loads(os.getenv("MAX_QTY_CAPS", default_max_qty))

    # ── Persistent execution locks (survive restarts, safe across instances) ──

    def _load_exec_locks(self):
        """Load persisted symbol execution locks from disk."""
        try:
            if os.path.exists(self._exec_lock_path):
                with open(self._exec_lock_path, 'r') as f:
                    data = json.load(f)
                # Merge disk locks into in-memory cooldown dict
                now = time.time()
                for sym, ts in data.items():
                    if now - ts < self.COOLDOWN_SECONDS:
                        self._symbol_cooldown[sym] = ts
        except Exception as e:
            logger.warning(f"Could not load exec locks: {e}")

    def _persist_exec_lock(self, symbol: str):
        """Write execution lock to disk immediately (atomic)."""
        try:
            self._symbol_cooldown[symbol] = time.time()
            tmp = self._exec_lock_path + ".tmp"
            with open(tmp, 'w') as f:
                json.dump(self._symbol_cooldown, f)
            os.replace(tmp, self._exec_lock_path)
        except Exception as e:
            logger.warning(f"Could not persist exec lock for {symbol}: {e}")

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
        logger.info(f"Candle locked: {symbol} -> {side} by {strategy} for {self.CANDLE_LOCK_SECONDS}s")

    def _is_symbol_in_cooldown(self, symbol: str) -> bool:
        last_trade = self._symbol_cooldown.get(symbol, 0)
        elapsed = time.time() - last_trade
        if elapsed < self.COOLDOWN_SECONDS:
            logger.info(f"Cooldown active for {symbol}: {self.COOLDOWN_SECONDS - elapsed:.0f}s remaining")
            return True
        return False

    def _mark_symbol_traded(self, symbol: str):
        self._symbol_cooldown[symbol] = time.time()

    def _is_duplicate_signal(self, strategy: str, symbol: str, side: str) -> bool:
        key = f"{strategy}:{symbol}:{side}".lower()
        now = time.time()
        last_seen = self._recent_signals.get(key, 0)
        if now - last_seen < self.DEDUP_WINDOW_SECONDS:
            logger.info(f"Duplicate signal blocked: {strategy} {side} {symbol} (seen {now - last_seen:.0f}s ago)")
            return True
        self._recent_signals[key] = now
        if len(self._recent_signals) > 200:
            cutoff = now - self.DEDUP_WINDOW_SECONDS * 2
            self._recent_signals = {k: v for k, v in self._recent_signals.items() if v > cutoff}
        return False

    def check_tournament_alpha(self, symbol, strategy_name) -> tuple[bool, str, str]:
        # All USDT symbols are allowed — no leaderboard restriction
        if symbol.upper().endswith("USDT"):
            logger.info(f"✅ Open pass: {symbol} {strategy_name}")
            return True, "All USDT symbols allowed", "ALPHA"
        return False, f"Non-USDT symbol {symbol} not supported", "NONE"

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
                logger.info(f"Skipping duplicate: {signal_id}")
                return True

            payload_raw = event.get("payload", {})
            signal_data = {**event, **payload_raw}
            if "secret" not in signal_data:
                signal_data["secret"] = self.webhook_secret

            target_exchange = str(payload_raw.get("exchange") or event.get("exchange") or "binance").lower()
            strat_name = payload_raw.get("strategy") or event.get("strategy") or "SMC"
            symbol_raw = str(payload_raw.get("symbol") or event.get("symbol") or "BTCUSDT").upper()

            # --- SYMBOL CLEANING ---
            symbol = symbol_raw.split('_')[0]
            if target_exchange in ("hyperliquid", "lighter"):
                symbol = symbol.replace("USDT", "").replace("USD", "") if target_exchange == "hyperliquid" else symbol
            else:
                if "USDT" not in symbol:
                    symbol = f"{symbol.replace('USD', '')}USDT"

            # --- 1. BRAIN TIER CHECK ---
            is_allowed, reason, tier = self.check_tournament_alpha(symbol, strat_name)
            if not is_allowed:
                logger.warning(f"AI Blocked: {reason}")
                try:
                    self.sheets_logger.log_blocked_trade(
                        symbol=symbol, side="N/A", strategy=strat_name,
                        reason=f"Tier Block: {reason}", signal_id=signal_id)
                except Exception as e:
                    logger.debug(f"Sheets log failed: {e}")
                return True

            # --- 1.5. SIGNAL DEDUP CHECK ---
            side_hint = str(payload_raw.get("action") or event.get("action") or "").upper()
            if self._is_duplicate_signal(strat_name, symbol, side_hint):
                return True

            # --- 1.6. SYMBOL COOLDOWN CHECK ---
            if self._is_symbol_in_cooldown(symbol):
                logger.info(f"Cooldown block: {symbol} (strategy: {strat_name})")
                return True

            # --- 1.7. CANDLE LOCK ---
            if self._is_candle_locked(symbol, side_hint):
                try:
                    self.sheets_logger.log_blocked_trade(
                        symbol=symbol, side=side_hint, strategy=strat_name,
                        reason="Candle Lock: Symbol locked to opposite direction", signal_id=signal_id)
                except Exception as e:
                    logger.debug(f"Sheets log failed: {e}")
                return True

            # --- 2. ROI GUARD ---
            try:
                strat_info = json.loads(payload_raw.get("strategy", "{}"))
                incoming_roi = float(strat_info.get("ROI", "0").replace("%", ""))
                if incoming_roi <= 0:
                    logger.warning(f"ROI Guard: Signal blocked ({incoming_roi}%)")
                    try:
                        self.sheets_logger.log_blocked_trade(
                            symbol=symbol, side="N/A", strategy=strat_name,
                            reason=f"ROI Guard: {incoming_roi}% (Negative)", signal_id=signal_id)
                    except Exception as e:
                        logger.debug(f"Sheets log failed: {e}")
                    return True
            except (json.JSONDecodeError, ValueError, TypeError):
                pass  # ROI check is optional — strategy field is usually plain text

            # --- 3. TIER-BASED INTERACTIVE GATE ---
            if "AVERAGE" in tier:
                try:
                    self.telegram.send(severity=AlertSeverity.WARNING, title="Manual Sync Needed",
                        message=f"AVERAGE Strategy: {strat_name} for {symbol}. No auto-trade. ID: {signal_id}")
                except Exception as e:
                    logger.debug(f"Telegram failed: {e}")
                return True

            # --- 4. PREPARE EXECUTION DATA ---
            try:
                signal_data["strategy"] = strat_name
                signal_data["symbol"] = symbol
                signal_data["quantity"] = float(payload_raw.get("quantity") or event.get("quantity") or 0.003)

                raw_price = float(payload_raw.get("price") or event.get("price") or 0.0)
                live_price = self.exchange_binance.get_mainnet_mark_price(symbol)
                if raw_price <= 0:
                    if live_price and live_price > 0:
                        raw_price = live_price
                        logger.info(f"Resolved missing price for {symbol}: ${raw_price}")
                    else:
                        logger.warning(f"Cannot resolve price for {symbol}. Skipping.")
                        return True
                elif live_price and live_price > 0:
                    deviation = abs(raw_price - live_price) / live_price
                    if deviation > 0.80:
                        logger.warning(
                            f"⚠️ Signal price ${raw_price:,.2f} deviates {deviation*100:.0f}% from "
                            f"market ${live_price:,.2f} for {symbol}. Replacing with market price."
                        )
                        raw_price = live_price
                signal_data["price"] = raw_price
                signal_data["action"] = str(payload_raw.get("action") or event.get("action") or "BUY").upper()

                valid_payload = SignalPayload(**signal_data)
                payload = valid_payload.model_dump()
            except Exception as e:
                logger.error(f"Data Parsing Error: {e}")
                return True

            side = "SELL" if payload["action"] in ["SELL", "TP", "EXIT", "SHORT", "OFF"] else "BUY"
            qty, price_signal = float(payload["quantity"]), float(payload["price"])
            indicator_name = payload_raw.get("indicator") or "AI_Optimized"

            # --- 4.5. EXIT/CLOSE HANDLING ---
            is_exit = payload_raw.get("is_exit", False)
            if not is_exit:
                pos_size = str(payload_raw.get("position_size", event.get("position_size", ""))).strip()
                if pos_size in ("0", "0.0", "flat"):
                    is_exit = True
                raw_body = str(event.get("raw_body", ""))
                if "position is 0" in raw_body.lower() or "position is -" in raw_body.lower():
                    is_exit = True
            if is_exit:
                current_pos = self.ledger.get_position(f"{target_exchange}:{symbol}")
                if current_pos.quantity == 0:
                    logger.info(f"Exit signal for {symbol} but no position open. Skipping.")
                    return True
                if current_pos.quantity > 0:
                    side = "SELL"
                    qty = abs(current_pos.quantity)
                elif current_pos.quantity < 0:
                    side = "BUY"
                    qty = abs(current_pos.quantity)
                logger.info(f"Exit signal: closing {symbol} position ({current_pos.quantity}) with {side} {qty}")

            # --- 4.9. KILL SWITCH CHECK ---
            kill_file = os.path.join(os.path.dirname(self.ledger_path), "KILL_SWITCH")
            if os.path.exists(kill_file):
                logger.critical("KILL SWITCH ACTIVE — blocking all trades")
                return True

            # --- 4.95. CIRCUIT BREAKER CHECK ---
            if self.circuit_breaker and not self.circuit_breaker.should_allow_trade():
                cb_reason = self.circuit_breaker.get_status().get('trip_reason', 'Circuit breaker tripped')
                logger.warning(f"Circuit Breaker: {cb_reason}")
                def _cb_alert():
                    try:
                        self.telegram.send(severity=AlertSeverity.CRITICAL, title="CIRCUIT BREAKER TRIPPED",
                            message=f"Trading HALTED: {cb_reason}\nAll signals blocked until cooldown.", force=True)
                    except: pass
                self._thread_pool.submit(_cb_alert)
                try:
                    self.sheets_logger.log_blocked_trade(symbol=symbol, side=side, strategy=strat_name,
                        reason=f"Circuit Breaker: {cb_reason}", signal_id=signal_id)
                except Exception as e:
                    logger.debug(f"Sheets log failed: {e}")
                return True

            # --- 5. RISK GATES ---
            if is_exit:
                if not self.allow_real:
                    is_safe, risk_reason = False, "ALLOW_REAL_TRADES is disabled"
                else:
                    is_safe, risk_reason = True, "Exit signal - closing position"
            else:
                is_safe, risk_reason = self.check_safety_gate(symbol, qty, price_signal, side, exchange=target_exchange)
            if not is_safe:
                logger.warning(f"Safety Gate Block: {risk_reason}")
                try:
                    self.telegram.send(severity=AlertSeverity.WARNING, title="Risk Block",
                        message=f"Safety Gate: {symbol} - {risk_reason}")
                except Exception as e:
                    logger.debug(f"Telegram failed: {e}")
                try:
                    self.sheets_logger.log_blocked_trade(
                        symbol=symbol, side=side, strategy=strat_name,
                        reason=f"Safety Gate: {risk_reason}", signal_id=signal_id)
                except Exception as e:
                    logger.debug(f"Sheets log failed: {e}")
                return True

            # --- 5.5. POSITION SIZING ---
            size_mode = os.getenv("POSITION_SIZE_MODE", "fixed")
            if size_mode == "equity_pct":
                equity_pct = float(os.getenv("EQUITY_PCT_PER_TRADE", "5.0")) / 100
                try:
                    if target_exchange == "lighter" and self.exchange_lighter:
                        avail = self.exchange_lighter.get_account_balance() or 0
                        sizing_price = self.exchange_lighter.get_mark_price(symbol) or price_signal
                    else:
                        health = self.exchange_binance.get_account_health()
                        avail = float(health.get("available_balance", 0)) if health else 0
                        sizing_price = self.exchange_binance.get_mainnet_mark_price(symbol) or price_signal
                    if avail > 0 and sizing_price > 0:
                        qty = (avail * equity_pct) / sizing_price
                        logger.info(f"Equity sizing [{target_exchange}]: {equity_pct*100}% of ${avail:.2f} @ ${sizing_price:.2f} = {qty:.6f} {symbol}")
                except Exception as e:
                    logger.warning(f"Equity sizing failed, using signal qty: {e}")

            # Max qty cap
            max_allowed = self.MAX_QTY.get(symbol, 1.0)
            if qty > max_allowed:
                logger.warning(f"Qty capped: {qty} -> {max_allowed} for {symbol}")
                qty = max_allowed

            # --- 6. ACTUAL EXECUTION ---
            # ⚡ Lock symbol BEFORE calling exchange — prevents duplicate orders from
            # concurrent strategies firing the same candle close (race condition fix).
            # Lock is persisted to disk so it survives service restarts.
            self._persist_exec_lock(symbol)
            self._set_candle_lock(symbol, side, strat_name)

            execution_res, fill_price = {}, price_signal
            if target_exchange == "lighter":
                if not self.exchange_lighter:
                    logger.warning(f"Lighter client not available, skipping {symbol}")
                    return True
                execution_res = self.exchange_lighter.execute_futures_order(
                    symbol, side, qty, price=price_signal, signal_id=signal_id
                )
                if execution_res.get("status") == "SUCCESS":
                    fill_price = float(
                        execution_res.get("avg_price") or
                        self.exchange_lighter.get_mark_price(symbol) or
                        price_signal
                    )
            elif target_exchange == "hyperliquid":
                if not self.exchange_hl:
                    logger.warning(f"HL client not available, skipping {symbol}")
                    return True
                try:
                    res = self.exchange_hl.market_order(symbol, (side == "BUY"), qty)
                    if res and res.get('status') == 'ok':
                        execution_res = {"status": "SUCCESS"}
                        try:
                            fill_price = float(res['response']['data']['statuses'][0]['filled']['avgPx'])
                        except (KeyError, IndexError, TypeError):
                            pass
                    else:
                        execution_res = {"status": "FAILED", "reason": str(res)}
                except Exception as e:
                    logger.error(f"HL execution error: {e}")
                    execution_res = {"status": "FAILED", "reason": str(e)}
            else:
                execution_res = self.exchange_binance.execute_futures_order(symbol, side, qty, price_signal, signal_id=signal_id)
                if execution_res.get("status") == "SUCCESS":
                    fill_price = float(
                        execution_res.get("avg_price") or
                        self.exchange_binance.get_mainnet_mark_price(symbol) or
                        price_signal
                    )

            # --- 7. LOGGING & ALERTS ---
            if execution_res.get("status") == "SUCCESS":
                self.idempotency.mark_seen(signal_id)
                try:
                    pos_snapshot = self.ledger.apply_fill(f"{target_exchange}:{symbol}", side, qty, fill_price)
                except Exception as e:
                    logger.critical(f"LEDGER WRITE FAILED: {e}. Trade OK but ledger desynced!")
                    def _alert_desync():
                        try:
                            self.telegram.send(severity=AlertSeverity.CRITICAL, title="LEDGER DESYNC",
                                message=f"Ledger write failed for {side} {qty} {symbol} @ {fill_price}. MANUAL FIX NEEDED.", force=True)
                        except: pass
                    self._thread_pool.submit(_alert_desync)
                    pos_snapshot = self.ledger.get_position(f"{target_exchange}:{symbol}")

                # Place exchange-side stop-loss
                if not is_exit and target_exchange == "lighter" and self.exchange_lighter:
                    sl_pct = float(os.getenv("STOP_LOSS_PCT", "3.0"))
                    sl_res = self.exchange_lighter.place_stop_loss(symbol, side, qty, fill_price, sl_pct=sl_pct, signal_id=signal_id)
                    if sl_res.get("status") == "SUCCESS":
                        logger.info(f"Lighter SL placed for {symbol} @ ${sl_res.get('stopPrice')}")
                    else:
                        logger.warning(f"Lighter SL failed for {symbol}: {sl_res.get('msg')}")
                if not is_exit and target_exchange == "binance":
                    sl_pct = float(os.getenv("STOP_LOSS_PCT", "3.0"))
                    sl_res = self.exchange_binance.place_stop_loss(symbol, side, qty, fill_price, sl_pct=sl_pct, signal_id=signal_id)
                    if sl_res.get("status") == "SUCCESS":
                        logger.info(f"SL placed for {symbol} @ ${sl_res.get('stopPrice')}")
                    else:
                        logger.warning(f"SL placement failed for {symbol}: {sl_res.get('msg')}")

                self.processed_count += 1
                # Async: non-blocking Sheets write
                def _log_trade():
                    try:
                        self.sheets_logger.log_trade(signal_id=signal_id, symbol=f"{target_exchange.upper()}:{symbol}",
                            action=side, qty=qty, price=fill_price, strategy=strat_name, indicator=indicator_name,
                            pnl=pos_snapshot.daily_realized_pnl)
                    except Exception as e:
                        logger.warning(f"Sheets trade log failed (async): {e}")
                self._thread_pool.submit(_log_trade)

                # Record win/loss for circuit breaker
                if self.circuit_breaker:
                    self.circuit_breaker.record_trade_result(pos_snapshot.daily_realized_pnl >= 0)

                # Auto-update analytics on every trade
                # Async: non-blocking analytics update
                def _update_analytics():
                    try:
                        self.analytics.update_today()
                    except Exception as ae:
                        logger.warning(f"Analytics update skipped (async): {ae}")
                self._thread_pool.submit(_update_analytics)

                emoji = "🟢" if side == "BUY" else "🔴"
                sl_info = ""
                if not is_exit and target_exchange in ("binance", "lighter"):
                    sl_pct_val = float(os.getenv("STOP_LOSS_PCT", "3.0"))
                    sl_price_est = fill_price * (1 - sl_pct_val / 100) if side == "BUY" else fill_price * (1 + sl_pct_val / 100)
                    sl_info = f"\n🛡️ <b>Stop-Loss:</b> <code>${sl_price_est:,.2f}</code> ({sl_pct_val}%)"
                try:
                    self.telegram.send(severity=AlertSeverity.INFO, title="Trade Success",
                        message=(f"{emoji} <b>Bot Alert: Trade Executed</b>\n\n"
                                 f"✅ <b>Executed:</b> {side} {symbol}\n"
                                 f"💰 <b>Price:</b> <code>${fill_price:,.2f}</code>\n"
                                 f"📊 <b>Quantity:</b> <code>{qty}</code>\n"
                                 f"📋 <b>Strategy:</b> <code>{strat_name}</code>\n"
                                 f"📈 <b>BT Status:</b> Verified {tier}{sl_info}\n"
                                 f"💵 <b>Today PnL:</b> <code>${pos_snapshot.daily_realized_pnl:.2f}</code>\n"
                                 f"🆔 <b>ID:</b> <code>{signal_id}</code>"))
                except Exception as e:
                    logger.debug(f"Telegram failed: {e}")
                return True
            else:
                exec_reason = execution_res.get('reason', 'Unknown API Error')
                exec_msg = execution_res.get('msg', '')
                logger.error(f"Execution Failure: {exec_reason} | Detail: {exec_msg}")
                try:
                    self.sheets_logger.log_blocked_trade(
                        symbol=symbol, side=side, strategy=strat_name,
                        reason=f"Execution Failed: {exec_reason}", signal_id=signal_id)
                except Exception as e:
                    logger.debug(f"Sheets log failed: {e}")
                if exec_reason in ("permanent", "timeout_unknown"):
                    # timeout_unknown: order status unclear — mark seen to prevent double-fill
                    if exec_reason == "timeout_unknown":
                        try:
                            self.telegram.send(
                                severity=AlertSeverity.CRITICAL,
                                title="⏱️ ORDER TIMEOUT — CHECK MANUALLY",
                                message=(f"⚠️ <b>{side} {symbol}</b> via <code>{strat_name}</code>\n"
                                         f"Order sent to Binance but response timed out.\n"
                                         f"<b>Status unknown — verify on Binance NOW.</b>\n"
                                         f"Signal NOT retried to avoid double-fill.\n"
                                         f"🆔 <code>{signal_id}</code>"),
                                force=True)
                        except Exception:
                            pass
                    self.idempotency.mark_seen(signal_id)
                    return True
                return False

        except Exception as e:
            logger.error(f"Critical Error in handle_signal: {e}")
            try:
                with open(self.dlq_path, 'a') as dlq:
                    dlq.write(json.dumps({"ts": datetime.utcnow().isoformat(), "err": str(e), "event": event}) + "\n")
            except Exception:
                logger.error(f"DLQ write also failed for signal: {event.get('signal_id', 'unknown')}")
            return True

    def run(self):
        self._running = True

        def _shutdown(signum, frame):
            logger.info(f"Received signal {signum}, shutting down gracefully...")
            self._running = False

        _signal.signal(_signal.SIGTERM, _shutdown)
        _signal.signal(_signal.SIGINT, _shutdown)

        queue_type = "SQLite Durable" if self.use_durable_queue else "JSONL Legacy"
        logger.info(f"Execution Engine Live | Queue: {queue_type}")
        while self._running:
            # Check kill switch in run loop too
            kill_file = os.path.join(os.path.dirname(self.ledger_path), "KILL_SWITCH")
            if os.path.exists(kill_file):
                if not hasattr(self, '_kill_logged'):
                    logger.critical("KILL SWITCH ACTIVE — pausing signal processing")
                    self._kill_logged = True
                time.sleep(5)
                continue
            elif hasattr(self, '_kill_logged'):
                logger.info("KILL SWITCH deactivated — resuming signal processing")
                del self._kill_logged

            if self.use_durable_queue:
                self.durable_queue.poll(handler=self.handle_signal, batch_size=1)
            else:
                self.consumer.poll(handler=self.handle_signal, batch_size=1)
            if time.time() - self.last_heartbeat > 900:
                logger.info(f"Heartbeat: Orchestrator running. Processed: {self.processed_count}")
                self.last_heartbeat = time.time()
            time.sleep(1)

        logger.info("Shutting down thread pool...")
        self._thread_pool.shutdown(wait=True, cancel_futures=False)
        logger.info(f"Orchestrator stopped gracefully. Total processed: {self.processed_count}")


if __name__ == "__main__":
    Orchestrator().run()
