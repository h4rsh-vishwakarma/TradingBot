import time, logging, os, json, sys, signal as _signal, pandas as pd
from concurrent.futures import ThreadPoolExecutor
import re, uuid
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
    from tradingview_webhook_bot.core.metrics import metrics
    from tradingview_webhook_bot.tournament_rules import parse_auto_trade_flag
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
            logger.critical("WEBHOOK_SECRET not set in env_vars! Set it in /etc/tradingbot/env_vars")
            sys.exit(1)
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

        # Lighter.xyz DEX
        try:
            self.exchange_lighter = LighterClient()
            if not self.exchange_lighter.client:
                self.exchange_lighter = None
        except Exception as e:
            logger.warning("Lighter init skipped: %s" % e)
            self.exchange_lighter = None

        self.bt_engine = BacktestEngine()
        self.processed_count = 0
        self._thread_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix='sheets')
        self.last_heartbeat = time.time()
        self.last_reconcile = time.time()
        self.RECONCILE_INTERVAL = int(os.getenv("RECONCILE_INTERVAL_SECONDS", "900"))  # 15 min

        # Circuit Breaker
        cb_state = os.path.join(base_storage, "circuit_breaker_state.json")
        cb_config = {
            "daily_loss_limit_pct": float(os.getenv("CB_DAILY_LOSS_PCT", "5.0")),
            "max_consecutive_losses": int(os.getenv("CB_MAX_CONSECUTIVE_LOSSES", "8")),
            "cooldown_minutes": int(os.getenv("CB_COOLDOWN_MINUTES", "60")),
            "cumulative_dd_limit_pct": float(os.getenv("CB_CUMULATIVE_DD_PCT", "15.0")),
        }
        try:
            self.circuit_breaker = CircuitBreaker(cb_state, cb_config)
            logger.info("Circuit Breaker initialized")
        except Exception as e:
            logger.warning(f"Circuit Breaker init failed: {e}")
            self.circuit_breaker = None

        # Anti Flip-Flop controls — all configurable via env
        self._symbol_cooldown = {}
        self.COOLDOWN_SECONDS = int(os.getenv("SYMBOL_COOLDOWN_SECONDS", "60"))
        self._recent_signals = {}
        self.DEDUP_WINDOW_SECONDS = int(os.getenv("DEDUP_WINDOW_SECONDS", "120"))
        self._candle_lock = {}
        self.CANDLE_LOCK_SECONDS = int(os.getenv("CANDLE_LOCK_SECONDS", "60"))

        # Max qty caps — configurable via env (JSON format)
        default_max_qty = '{"SOLUSDT": 1.0, "ETHUSDT": 0.05, "BTCUSDT": 0.003, "BNBUSDT": 0.1, "ADAUSDT": 30.0, "LINKUSDT": 1.0, "DOTUSDT": 2.0}'
        self.MAX_QTY = json.loads(os.getenv("MAX_QTY_CAPS", default_max_qty))

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

    @staticmethod
    def _normalize_strategy(name):
        s = str(name)
        for ch in ['_', chr(39), chr(34), '[', ']', '+', ',', '-', '|', '.']:
            s = s.replace(ch, ' ')
        return re.sub(r'\s+', ' ', s).strip().lower()

    @staticmethod
    def _strategy_display_name(name) -> str:
        if isinstance(name, dict):
            for key in ("name", "strategy", "title", "id"):
                value = name.get(key)
                if value:
                    return str(value)
            try:
                return json.dumps(name, sort_keys=True)
            except Exception:
                return str(name)
        return str(name or "SMC")

    def _send_telegram_alert(self, severity, title: str, message: str, alert_key: str | None = None, force: bool = False):
        def _send():
            try:
                self.telegram.send(
                    severity=severity,
                    title=title,
                    message=message,
                    alert_key=alert_key,
                    force=force,
                )
            except Exception as e:
                logger.debug(f"Telegram failed: {e}")

        pool = getattr(self, "_thread_pool", None)
        if pool:
            try:
                pool.submit(_send)
                return
            except Exception:
                pass
        _send()

    def _log_blocked_trade_safe(self, symbol: str, side: str, strategy: str, reason: str, signal_id: str):
        try:
            self.sheets_logger.log_blocked_trade(
                symbol=symbol,
                side=side,
                strategy=strategy,
                reason=reason,
                signal_id=signal_id,
            )
        except Exception as e:
            logger.debug(f"Sheets log failed: {e}")

    def _send_auto_reject_alert(self, signal_id: str, symbol: str, side: str, strategy: str, reason: str, tier: str):
        self._send_telegram_alert(
            severity=AlertSeverity.WARNING,
            title="Auto Rejected",
            message=(
                "🚫 <b>Bot Alert: Auto Rejected</b>\n\n"
                f"📍 <b>Symbol:</b> <code>{symbol}</code>\n"
                f"🧭 <b>Side:</b> <code>{side or 'N/A'}</code>\n"
                f"📋 <b>Strategy:</b> <code>{strategy}</code>\n"
                f"📈 <b>Tier:</b> <code>{tier or 'NONE'}</code>\n"
                f"⚠️ <b>Reason:</b> {reason}\n"
                "🤖 <b>Decision:</b> No auto-trade executed.\n"
                f"🆔 <b>ID:</b> <code>{signal_id}</code>"
            ),
            alert_key=f"auto_reject_{signal_id}",
        )

    def _send_match_error_alert(self, signal_id: str, symbol: str, side: str, strategy: str, stage: str, reason: str):
        self._send_telegram_alert(
            severity=AlertSeverity.HIGH,
            title="Strategy Match Error",
            message=(
                "🛠️ <b>Bot Alert: Strategy Match Error</b>\n\n"
                f"📍 <b>Symbol:</b> <code>{symbol}</code>\n"
                f"🧭 <b>Side:</b> <code>{side or 'N/A'}</code>\n"
                f"📋 <b>Strategy:</b> <code>{strategy}</code>\n"
                f"🧪 <b>Stage:</b> <code>{stage}</code>\n"
                f"⚠️ <b>Error:</b> {reason}\n"
                "🤖 <b>Decision:</b> No auto-trade executed.\n"
                f"🆔 <b>ID:</b> <code>{signal_id}</code>"
            ),
            alert_key=f"match_error_{signal_id}_{stage}",
        )

    def _send_execution_failure_alert(self, signal_id: str, symbol: str, side: str, strategy: str, reason: str, detail: str = ""):
        extra_detail = f"\n🧾 <b>Detail:</b> {detail}" if detail else ""
        self._send_telegram_alert(
            severity=AlertSeverity.HIGH,
            title="Execution Failure",
            message=(
                "❌ <b>Bot Alert: Execution Failed</b>\n\n"
                f"📍 <b>Symbol:</b> <code>{symbol}</code>\n"
                f"🧭 <b>Side:</b> <code>{side or 'N/A'}</code>\n"
                f"📋 <b>Strategy:</b> <code>{strategy}</code>\n"
                f"⚠️ <b>Reason:</b> {reason}{extra_detail}\n"
                "🤖 <b>Decision:</b> Auto-trade was attempted but not executed.\n"
                f"🆔 <b>ID:</b> <code>{signal_id}</code>"
            ),
            alert_key=f"execution_failure_{signal_id}",
        )

    def _is_symbol_in_cooldown(self, symbol: str, strategy: str = "") -> bool:
        cooldown_key = f"{symbol}:{strategy}" if strategy else symbol
        last_trade = self._symbol_cooldown.get(cooldown_key, 0)
        elapsed = time.time() - last_trade
        if elapsed < self.COOLDOWN_SECONDS:
            logger.info(f"Cooldown active for {symbol}: {self.COOLDOWN_SECONDS - elapsed:.0f}s remaining")
            return True
        return False

    def _mark_symbol_traded(self, symbol: str, strategy: str = ""):
        cooldown_key = f"{symbol}:{strategy}" if strategy else symbol
        self._symbol_cooldown[cooldown_key] = time.time()

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
        if not os.path.exists(self.report_path):
            fallback = self.report_path + ".bak"
            if os.path.exists(fallback):
                logger.warning(f"Tournament CSV missing, using backup: {fallback}")
                self.report_path = fallback
            else:
                logger.warning("No tournament CSV found. Allowing signal.")
                return True, "No report found, allowing", "ALPHA"
        try:
            df = pd.read_csv(self.report_path)
            strat_clean = self._normalize_strategy(strategy_name)
            def _strat_match(row_strat):
                row_clean = self._normalize_strategy(row_strat)
                return strat_clean in row_clean or row_clean in strat_clean
            symbol_upper = str(symbol).upper()
            symbol_series = df['Symbol'].fillna('').astype(str)
            exact_symbol_match = symbol_series.str.upper() == symbol_upper
            if exact_symbol_match.any():
                symbol_mask = exact_symbol_match
            else:
                symbol_mask = symbol_series.str.contains(symbol_upper, case=False, na=False)
            match = df[symbol_mask & df['Strategy'].fillna('').astype(str).apply(_strat_match)]
            if match.empty:
                return False, f"Strategy {strategy_name} for {symbol} not in Leaderboard.", "NONE"
            row = match.iloc[0]
            tier = str(row.get('Tier', ''))
            auto_trade_eligible = parse_auto_trade_flag(row.get("Auto_Trade_Eligible"), None)
            auto_trade_reason = str(row.get("Auto_Trade_Reason", "")).strip()
            if auto_trade_eligible is False and "ALPHA" in tier:
                reason = auto_trade_reason or "Strategy no longer meets tournament auto-trade rules."
                return True, reason, "AVERAGE"
            if "ALPHA" in tier: return True, "Verified ALPHA: Direct Execution", "ALPHA"
            if "AVERAGE" in tier:
                reason = auto_trade_reason or "Verified AVERAGE: Human Approval Needed"
                return True, reason, "AVERAGE"
            return False, f"Strategy Tier is {tier}. Blocked.", tier
        except Exception as e:
            logger.error(f"Leaderboard Check Error: {e}")
            return False, f"Leaderboard check failed: {e}", "ERROR"

    def check_safety_gate(self, symbol, qty, price, side, exchange="binance", strategy="") -> tuple[bool, str]:
        if not self.allow_real: return False, "ALLOW_REAL_TRADES is disabled"
        current_pnl = self.ledger.get_daily_pnl()
        if current_pnl <= self.daily_loss_limit:
            return False, f"Daily loss limit hit: ${current_pnl:.2f}"
        # Per-strategy position check (Option C)
        pos_key = f"{exchange}:{symbol}:{strategy}" if strategy else f"{exchange}:{symbol}"
        current_pos = self.ledger.get_position(pos_key)
        if (side == "BUY" and current_pos.quantity > 0) or (side == "SELL" and current_pos.quantity < 0):
            return False, f"Already in {side} position for {symbol} ({strategy}) on {exchange}."
        return True, "Safe"

    def handle_signal(self, event: dict) -> bool:
        try:
            metrics.inc("bot_signals_received_total")
            correlation_id = str(uuid.uuid4())[:8]
            signal_id = event.get("signal_id")
            logger.info(f"[{correlation_id}] Processing signal {signal_id}")
            if self.idempotency.is_seen(signal_id):
                logger.info(f"[{correlation_id}] Skipping duplicate: {signal_id}")
                return True

            payload_raw = event.get("payload", {})
            signal_data = {**event, **payload_raw}
            if "secret" not in signal_data:
                signal_data["secret"] = self.webhook_secret

            target_exchange = str(payload_raw.get("exchange") or event.get("exchange") or "binance").lower()
            strat_name_raw = payload_raw.get("strategy") or event.get("strategy") or "SMC"
            strategy_display = self._strategy_display_name(strat_name_raw)
            strat_name = self._normalize_strategy(strategy_display)
            symbol_raw = str(payload_raw.get("symbol") or event.get("symbol") or "BTCUSDT").upper()
            side_hint = str(
                payload_raw.get("action")
                or event.get("action")
                or payload_raw.get("side")
                or event.get("side")
                or "N/A"
            ).upper()

            # --- SYMBOL CLEANING ---
            symbol = symbol_raw.split('_')[0]
            if target_exchange == "lighter":
                if not self.exchange_lighter:
                    logger.warning("Lighter client not available")
                    return True
                try:
                    is_buy = (side == "BUY")
                    res = self.exchange_lighter.market_order(symbol, is_buy, qty, price_signal, signal_id)
                    if res.get("status") == "ok":
                        execution_res = {"status": "SUCCESS"}
                        try:
                            fill_price = float(res["response"]["data"]["statuses"][0]["filled"]["avgPx"])
                        except (KeyError, IndexError, TypeError):
                            fill_price = price_signal
                    else:
                        execution_res = {"status": "FAILED", "reason": str(res.get("msg",""))}
                except Exception as e:
                    execution_res = {"status": "FAILED", "reason": str(e)}
            elif target_exchange == "hyperliquid":
                symbol = symbol.replace("USDT", "").replace("USD", "")
            else:
                if "USDT" not in symbol:
                    symbol = f"{symbol.replace('USD', '')}USDT"

            # --- 1. BRAIN TIER CHECK ---
            is_allowed, reason, tier = self.check_tournament_alpha(symbol, strat_name)
            if not is_allowed:
                logger.warning(f"[{correlation_id}] AI Blocked: {reason}")
                if tier == "ERROR":
                    self._send_match_error_alert(
                        signal_id=signal_id,
                        symbol=symbol,
                        side=side_hint,
                        strategy=strategy_display,
                        stage="leaderboard_check",
                        reason=reason,
                    )
                else:
                    self._send_auto_reject_alert(
                        signal_id=signal_id,
                        symbol=symbol,
                        side=side_hint,
                        strategy=strategy_display,
                        reason=reason,
                        tier=tier,
                    )
                self._log_blocked_trade_safe(
                    symbol=symbol,
                    side=side_hint,
                    strategy=strategy_display,
                    reason=f"Tier Block: {reason}",
                    signal_id=signal_id,
                )
                metrics.inc("bot_signals_blocked_total", labels={"reason": "tier_block"})
                return True

            # --- 1.5. SIGNAL DEDUP CHECK ---
            if self._is_duplicate_signal(strat_name, symbol, side_hint):
                return True

            # --- 1.6. SYMBOL COOLDOWN CHECK ---
            if self._is_symbol_in_cooldown(symbol):
                metrics.inc("bot_signals_blocked_total", labels={"reason": "cooldown"})
                logger.info(f"[{correlation_id}] Cooldown block: {symbol} (strategy: {strat_name})")
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
                    logger.warning(f"[{correlation_id}] ROI Guard: Signal blocked ({incoming_roi}%)")
                    self._send_auto_reject_alert(
                        signal_id=signal_id,
                        symbol=symbol,
                        side=side_hint,
                        strategy=strategy_display,
                        reason=f"ROI Guard blocked incoming ROI {incoming_roi}%",
                        tier="ROI_GUARD",
                    )
                    self._log_blocked_trade_safe(
                        symbol=symbol,
                        side=side_hint,
                        strategy=strategy_display,
                        reason=f"ROI Guard: {incoming_roi}% (Negative)",
                        signal_id=signal_id,
                    )
                    return True
            except (json.JSONDecodeError, ValueError, TypeError):
                pass  # ROI check is optional — strategy field is usually plain text

            # --- 3. TIER-BASED INTERACTIVE GATE ---
            if "AVERAGE" in tier:
                self._send_auto_reject_alert(
                    signal_id=signal_id,
                    symbol=symbol,
                    side=side_hint,
                    strategy=strategy_display,
                    reason=f"{reason} Manual review required.",
                    tier=tier,
                )
                self._log_blocked_trade_safe(
                    symbol=symbol,
                    side=side_hint,
                    strategy=strategy_display,
                    reason=f"AVERAGE Tier: {reason}",
                    signal_id=signal_id,
                )
                return True

            # --- 4. PREPARE EXECUTION DATA ---
            try:
                signal_data["strategy"] = strat_name
                signal_data["symbol"] = symbol
                signal_data["quantity"] = float(payload_raw.get("quantity") or event.get("quantity") or 0.003)

                raw_price = float(payload_raw.get("price") or event.get("price") or 0.0)
                if raw_price <= 0:
                    live_price = self.exchange_binance.get_mainnet_mark_price(symbol)
                    if live_price and live_price > 0:
                        raw_price = live_price
                        logger.info(f"[{correlation_id}] Resolved price for {symbol}: ${raw_price}")
                    else:
                        logger.warning(f"[{correlation_id}] Cannot resolve price for {symbol}. Skipping.")
                        self._send_match_error_alert(
                            signal_id=signal_id,
                            symbol=symbol,
                            side=side_hint,
                            strategy=strategy_display,
                            stage="price_resolution",
                            reason="Incoming alert had no usable price and mainnet price lookup failed.",
                        )
                        return True
                signal_data["price"] = raw_price
                signal_data["action"] = str(payload_raw.get("action") or event.get("action") or "BUY").upper()

                valid_payload = SignalPayload(**signal_data)
                payload = valid_payload.model_dump()
            except Exception as e:
                logger.error(f"[{correlation_id}] Data Parsing Error: {e}")
                self._send_match_error_alert(
                    signal_id=signal_id,
                    symbol=symbol,
                    side=side_hint,
                    strategy=strategy_display,
                    stage="payload_validation",
                    reason=str(e),
                )
                self._log_blocked_trade_safe(
                    symbol=symbol,
                    side=side_hint,
                    strategy=strategy_display,
                    reason=f"Payload Validation: {e}",
                    signal_id=signal_id,
                )
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
                current_pos = self.ledger.get_position(f"{target_exchange}:{symbol}:{strat_name}")
                if current_pos.quantity == 0:
                    logger.info(f"[{correlation_id}] Exit signal for {symbol} but no position open. Skipping.")
                    return True
                if current_pos.quantity > 0:
                    side = "SELL"
                    qty = abs(current_pos.quantity)
                elif current_pos.quantity < 0:
                    side = "BUY"
                    qty = abs(current_pos.quantity)
                logger.info(f"[{correlation_id}] Exit signal: closing {symbol} position ({current_pos.quantity}) with {side} {qty}")

            # --- 4.9. KILL SWITCH CHECK ---
            kill_file = os.path.join(os.path.dirname(self.ledger_path), "KILL_SWITCH")
            if os.path.exists(kill_file):
                logger.critical(f"[{correlation_id}] KILL SWITCH ACTIVE — blocking all trades")
                return True

            # --- 4.95. CIRCUIT BREAKER CHECK ---
            if self.circuit_breaker and not self.circuit_breaker.should_allow_trade():
                cb_reason = self.circuit_breaker.get_status().get('trip_reason', 'Circuit breaker tripped')
                logger.warning(f"[{correlation_id}] Circuit Breaker: {cb_reason}")
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
                is_safe, risk_reason = self.check_safety_gate(symbol, qty, price_signal, side, exchange=target_exchange, strategy=strat_name)
            if not is_safe:
                logger.warning(f"[{correlation_id}] Safety Gate Block: {risk_reason}")
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
                    health = self.exchange_binance.get_account_health()
                    if health:
                        avail = health.get("available_balance", 0)
                        if avail > 0 and price_signal > 0:
                            qty = (avail * equity_pct) / price_signal
                            logger.info(f"[{correlation_id}] Equity sizing: {equity_pct*100}% of ${avail:.2f} = {qty:.6f} {symbol}")
                except Exception as e:
                    logger.warning(f"[{correlation_id}] Equity sizing failed, using signal qty: {e}")

            # Max qty cap
            max_allowed = self.MAX_QTY.get(symbol, 1.0)
            if qty > max_allowed:
                logger.warning(f"[{correlation_id}] Qty capped: {qty} -> {max_allowed} for {symbol}")
                qty = max_allowed

            # --- 6. ACTUAL EXECUTION ---
            execution_res, fill_price = {}, price_signal
            if target_exchange == "lighter":
                if not self.exchange_lighter:
                    logger.warning("Lighter client not available")
                    return True
                try:
                    is_buy = (side == "BUY")
                    res = self.exchange_lighter.market_order(symbol, is_buy, qty, price_signal, signal_id)
                    if res.get("status") == "ok":
                        execution_res = {"status": "SUCCESS"}
                        try:
                            fill_price = float(res["response"]["data"]["statuses"][0]["filled"]["avgPx"])
                        except (KeyError, IndexError, TypeError):
                            fill_price = price_signal
                    else:
                        execution_res = {"status": "FAILED", "reason": str(res.get("msg",""))}
                except Exception as e:
                    execution_res = {"status": "FAILED", "reason": str(e)}
            elif target_exchange == "hyperliquid":
                if not self.exchange_hl:
                    logger.warning(f"[{correlation_id}] HL client not available, skipping {symbol}")
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
                    logger.error(f"[{correlation_id}] HL execution error: {e}")
                    execution_res = {"status": "FAILED", "reason": str(e)}
            else:
                execution_res = self.exchange_binance.execute_futures_order(symbol, side, qty, price_signal, signal_id=signal_id)
                if execution_res.get("status") == "SUCCESS":
                    fill_price = float(execution_res.get("avg_price") or price_signal)

            # --- 7. LOGGING & ALERTS ---
            if execution_res.get("status") == "SUCCESS":
                self.idempotency.mark_seen(signal_id)
                try:
                    pos_key = f"{target_exchange}:{symbol}:{strat_name}"
                    pos_snapshot = self.ledger.apply_fill(pos_key, side, qty, fill_price)
                except Exception as e:
                    logger.critical(f"[{correlation_id}] LEDGER WRITE FAILED: {e}. Trade OK but ledger desynced!")
                    def _alert_desync():
                        try:
                            self.telegram.send(severity=AlertSeverity.CRITICAL, title="LEDGER DESYNC",
                                message=f"Ledger write failed for {side} {qty} {symbol} @ {fill_price}. MANUAL FIX NEEDED.", force=True)
                        except: pass
                    self._thread_pool.submit(_alert_desync)
                    pos_snapshot = self.ledger.get_position(f"{target_exchange}:{symbol}:{strat_name}")

                self._mark_symbol_traded(symbol, strat_name)
                self._set_candle_lock(symbol, side, strat_name)

                # Place exchange-side stop-loss
                if not is_exit and target_exchange == "binance":
                    sl_pct = float(os.getenv("STOP_LOSS_PCT", "3.0"))
                    tp_pct = float(os.getenv("TAKE_PROFIT_PCT", "5.0"))
                    sl_res = self.exchange_binance.place_stop_loss(symbol, side, qty, fill_price, sl_pct=sl_pct, signal_id=signal_id)
                    if sl_res.get("status") == "SUCCESS":
                        logger.info(f"[{correlation_id}] SL placed for {symbol} @ ${sl_res.get('stopPrice')}")
                    else:
                        logger.warning(f"[{correlation_id}] SL placement failed for {symbol}: {sl_res.get('msg')}")
                    tp_res = self.exchange_binance.place_take_profit(symbol, side, qty, fill_price, tp_pct=tp_pct, signal_id=signal_id)
                    if tp_res.get("status") == "SUCCESS":
                        logger.info(f"[{correlation_id}] TP placed for {symbol} @ ${tp_res.get('tpPrice')}")
                    else:
                        logger.warning(f"[{correlation_id}] TP placement failed for {symbol}: {tp_res.get('msg')}")

                self.processed_count += 1
                metrics.inc("bot_trades_executed_total", labels={"symbol": symbol, "side": side})
                metrics.set_gauge("bot_last_trade_price", fill_price, labels={"symbol": symbol})
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
                metrics.set_gauge("bot_daily_pnl_usd", pos_snapshot.daily_realized_pnl)
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

                # Determine trade type: Open/Close Long/Short
                current_pos_qty = pos_snapshot.quantity if pos_snapshot else 0
                if is_exit:
                    if side == "SELL":
                        trade_type = "Close Long"
                        emoji = "🔴"
                    else:
                        trade_type = "Close Short"
                        emoji = "🟢"
                else:
                    if side == "BUY":
                        trade_type = "Open Long"
                        emoji = "🟢"
                    else:
                        trade_type = "Open Short"
                        emoji = "🔴"

                # Calculate SL/TP prices
                sl_info = ""
                tp_info = ""
                if not is_exit and target_exchange == "binance":
                    sl_pct_val = float(os.getenv("STOP_LOSS_PCT", "3.0"))
                    tp_pct_val = float(os.getenv("TAKE_PROFIT_PCT", "5.0"))
                    if side == "BUY":
                        sl_price_est = fill_price * (1 - sl_pct_val / 100)
                        tp_price_est = fill_price * (1 + tp_pct_val / 100)
                    else:
                        sl_price_est = fill_price * (1 + sl_pct_val / 100)
                        tp_price_est = fill_price * (1 - tp_pct_val / 100)
                    sl_info = f"\n🛡️ <b>Stop-Loss:</b> <code>${sl_price_est:,.2f}</code> ({sl_pct_val}%)"
                    tp_info = f"\n🎯 <b>Take-Profit:</b> <code>${tp_price_est:,.2f}</code> ({tp_pct_val}%)"
                try:
                    self.telegram.send(severity=AlertSeverity.INFO, title="Trade Success",
                        message=(f"{emoji} <b>Bot Alert: Auto Trade Executed</b>\n\n"
                                 f"✅ <b>Action:</b> {trade_type} {symbol}\n"
                                 f"💰 <b>Price:</b> <code>${fill_price:,.2f}</code>\n"
                                 f"📊 <b>Quantity:</b> <code>{qty}</code>\n"
                                 f"📋 <b>Strategy:</b> <code>{strat_name}</code>\n"
                                 f"📈 <b>BT Status:</b> Verified {tier}{sl_info}{tp_info}\n"
                                 f"💵 <b>Today PnL:</b> <code>${pos_snapshot.daily_realized_pnl:.2f}</code>\n"
                                 f"🆔 <b>ID:</b> <code>{signal_id}</code>"))
                except Exception as e:
                    logger.debug(f"Telegram failed: {e}")
                return True
            else:
                exec_reason = execution_res.get('reason', 'Unknown API Error')
                exec_msg = execution_res.get('msg', '')
                metrics.inc("bot_execution_failures_total")
                logger.error(f"[{correlation_id}] Execution Failure: {exec_reason} | Detail: {exec_msg}")
                self._send_execution_failure_alert(
                    signal_id=signal_id,
                    symbol=symbol,
                    side=side,
                    strategy=strategy_display,
                    reason=exec_reason,
                    detail=exec_msg,
                )
                self._log_blocked_trade_safe(
                    symbol=symbol,
                    side=side,
                    strategy=strategy_display,
                    reason=f"Execution Failed: {exec_reason}",
                    signal_id=signal_id,
                )
                if exec_reason == "permanent":
                    self.idempotency.mark_seen(signal_id)
                    return True
                return False

        except Exception as e:
            logger.error(f"[{correlation_id}] Critical Error in handle_signal: {e}")
            self._send_match_error_alert(
                signal_id=event.get("signal_id", "unknown"),
                symbol=str(event.get("symbol") or event.get("payload", {}).get("symbol") or "UNKNOWN"),
                side=str(event.get("action") or event.get("payload", {}).get("action") or "N/A").upper(),
                strategy=self._strategy_display_name(event.get("strategy") or event.get("payload", {}).get("strategy") or "SMC"),
                stage="handle_signal",
                reason=str(e),
            )
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

            # --- PERIODIC RECONCILER (every 15 min) ---
            if time.time() - self.last_reconcile > self.RECONCILE_INTERVAL:
                self.last_reconcile = time.time()
                def _run_reconcile():
                    try:
                        exchange_positions = self.exchange_binance.get_open_positions()
                        if exchange_positions:
                            exchange_data = {}
                            for pos in exchange_positions:
                                sym = pos.get('symbol', '')
                                qty = float(pos.get('positionAmt', 0))
                                if abs(qty) > 0:
                                    exchange_data[f"binance:{sym}"] = {
                                        'quantity': qty,
                                        'side': 'LONG' if qty > 0 else 'SHORT'
                                    }
                            alerts = self.reconciler.reconcile_with_exchange(exchange_data)
                            if alerts:
                                for alert_msg in alerts:
                                    self.telegram.send(
                                        severity=AlertSeverity.WARNING,
                                        title="🔧 Reconciler Fix",
                                        message=alert_msg
                                    )
                                logger.info(f"Reconciler: {len(alerts)} drift(s) fixed")
                            else:
                                logger.debug("Reconciler: Ledger synced with exchange")
                    except Exception as e:
                        logger.warning(f"Reconciler run failed: {e}")
                self._thread_pool.submit(_run_reconcile)

            if time.time() - self.last_heartbeat > 900:
                logger.info(f"Heartbeat: Orchestrator running. Processed: {self.processed_count}")
                self.last_heartbeat = time.time()
            time.sleep(1)

        logger.info("Shutting down thread pool...")
        self._thread_pool.shutdown(wait=True, cancel_futures=False)
        logger.info(f"Orchestrator stopped gracefully. Total processed: {self.processed_count}")


if __name__ == "__main__":
    Orchestrator().run()
