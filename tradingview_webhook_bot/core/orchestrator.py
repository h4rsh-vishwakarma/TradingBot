import time, logging, os, json, sys, re, signal as _signal, pandas as pd
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
    from tradingview_webhook_bot.exchange.hl_client import HyperliquidClient
    from tradingview_webhook_bot.exchange.lighter_client import LighterClient
    from tradingview_webhook_bot.utils.position_summary import (
        build_position_snapshot,
        format_positions_for_log,
        format_positions_for_telegram,
    )
except ImportError as e:
    logger.error(f"Import failed: {e}")
    sys.exit(1)

from scripts.execution_telemetry import append_execution_metric, estimate_fee_bps, execution_metrics_path


class Orchestrator:
    def __init__(self):
        # Testnet/mainnet safety invariant: refuse to boot if paper_only is
        # live-enabled while running against real-capital exchange endpoints.
        try:
            from scripts.check_testnet_invariant import check as _testnet_check
            _ok, _msg = _testnet_check()
            if not _ok:
                logger.critical(_msg)
                try:
                    from alerts.telegram_alerts import TelegramAlert as _GuardTg, AlertSeverity as _GuardSev
                    _GuardTg().send(
                        severity=_GuardSev.CRITICAL,
                        title="ORCHESTRATOR REFUSED TO START",
                        message=_msg,
                    )
                except Exception:
                    pass
                raise SystemExit(1)
            logger.info(f"[testnet-invariant OK] {_msg}")
        except SystemExit:
            raise
        except Exception as _e:
            logger.warning(f"testnet invariant check skipped: {_e}")

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
        self.approval_manifest_path = os.getenv(
            "APPROVAL_MANIFEST_PATH",
            str(PROJECT_ROOT / "config" / "approved_strategies.json"),
        )
        self.require_approval_manifest = os.getenv("REQUIRE_APPROVAL_MANIFEST", "true").lower() == "true"

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

        self.processed_count = 0
        self._thread_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix='sheets')
        self.last_heartbeat = time.time()
        self.last_reconcile = time.time()
        self.RECONCILE_INTERVAL = int(os.getenv("RECONCILE_INTERVAL_SECONDS", "900"))
        self._symbol_cooldown = {}
        self.COOLDOWN_SECONDS = int(os.getenv("SYMBOL_COOLDOWN_SECONDS", "300"))
        self._recent_signals = {}
        self.DEDUP_WINDOW_SECONDS = int(os.getenv("DEDUP_WINDOW_SECONDS", "120"))
        self._candle_lock = {}
        self.CANDLE_LOCK_SECONDS = int(os.getenv("CANDLE_LOCK_SECONDS", "3600"))
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
            # Pre-seed daily_start_balance so the daily-loss check is live
            # from the very first signal, not lazy-initialized on the 2nd.
            self._cb_balance_cache = None
            self._cb_balance_cache_ts = 0.0
            try:
                _seed = self._get_cb_balance()
                if _seed is not None:
                    self.circuit_breaker.should_allow_trade(current_balance=_seed)
                    logger.info(f"Circuit breaker baseline primed: ${_seed:.2f}")
            except Exception as _e:
                logger.debug(f"CB baseline prime skipped: {_e}")
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

        self._load_exec_locks()

        # Max qty caps — configurable via env (JSON format)
        default_max_qty = '{"SOLUSDT": 1.0, "ETHUSDT": 0.05, "BTCUSDT": 0.003}'
        self.MAX_QTY = json.loads(os.getenv("MAX_QTY_CAPS", default_max_qty))
        self.execution_metrics_path = str(execution_metrics_path())

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

    @staticmethod
    def _normalize_strategy(name):
        s = str(name)
        for ch in ['_', chr(39), chr(34), '[', ']', '+', ',', '-', '|', '.']:
            s = s.replace(ch, ' ')
        return re.sub(r'\s+', ' ', s).strip().lower()

    def _exchange_enabled(self, exchange: str) -> bool:
        allowed_exchanges_raw = os.getenv("ALLOWED_EXCHANGES", "").strip().lower()
        if not allowed_exchanges_raw:
            return True
        allowed_exchanges = {ex.strip() for ex in allowed_exchanges_raw.split(",") if ex.strip()}
        return str(exchange or "").lower() in allowed_exchanges

    def _load_approval_manifest(self) -> dict:
        try:
            with open(self.approval_manifest_path, encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    data.setdefault("approvals", [])
                    return data
        except FileNotFoundError:
            logger.warning(f"Approval manifest not found: {self.approval_manifest_path}")
        except Exception as e:
            logger.warning(f"Could not load approval manifest {self.approval_manifest_path}: {e}")
        return {"approvals": []}

    def check_strategy_approval(self, symbol: str, strategy_name: str, exchange: str, timeframe: str = "") -> tuple[bool, str, dict]:
        if not getattr(self, "require_approval_manifest", True):
            return True, "Approval manifest disabled", {"status": "disabled"}

        manifest = self._load_approval_manifest()
        approvals = manifest.get("approvals", [])
        if not approvals:
            return False, "No approved strategies configured", {}

        symbol_upper = str(symbol or "").upper()
        exchange_lower = str(exchange or "").lower()
        strategy_norm = self._normalize_strategy(strategy_name)
        timeframe_norm = str(timeframe or "").strip().lower()

        for approval in approvals:
            approval_strategy = self._normalize_strategy(approval.get("strategy", ""))
            approval_exchange = str(approval.get("exchange", exchange_lower)).strip().lower()
            approval_symbols = [str(s).upper() for s in approval.get("symbols", ["*"])]
            approval_timeframes = [str(tf).strip().lower() for tf in approval.get("timeframes", ["*"])]
            approval_class = str(approval.get("approval_class", "")).strip()

            symbol_ok = "*" in approval_symbols or symbol_upper in approval_symbols
            timeframe_ok = not timeframe_norm or "*" in approval_timeframes or timeframe_norm in approval_timeframes
            if (
                approval_strategy == strategy_norm
                and approval_exchange == exchange_lower
                and symbol_ok
                and timeframe_ok
            ):
                allowed_classes = {
                    cls.strip().lower()
                    for cls in os.getenv(
                        "LIVE_APPROVAL_CLASSES",
                        "candidate_for_tiny_capital,live_approved,approved",
                    ).split(",")
                    if cls.strip()
                }
                approval_class_norm = approval_class.lower()
                if approval_class_norm and approval_class_norm not in allowed_classes:
                    return False, (
                        f"Approval class '{approval_class}' is not live-enabled "
                        f"(allowed: {', '.join(sorted(allowed_classes))})"
                    ), approval
                operator = approval.get("operator", "unknown")
                approved_at = approval.get("approved_at", "unknown")
                class_note = f", class={approval_class}" if approval_class else ""
                return True, f"Approved by manifest ({operator} @ {approved_at}{class_note})", approval

        return False, f"{strategy_name} / {symbol_upper} is not approved in the live manifest", {}

    def _notify_signal_decision(self, title: str, reason: str, signal_id: str = "", symbol: str = "",
                                strategy: str = "", action: str = "", severity=AlertSeverity.INFO):
        def _send():
            try:
                self.telegram.send(
                    severity=severity,
                    title=title,
                    message=(f"<b>{title}</b>\n\n"
                             f"<b>Symbol:</b> {symbol or 'N/A'}\n"
                             f"<b>Action:</b> {str(action or 'N/A').upper()}\n"
                             f"<b>Strategy:</b> <code>{strategy or 'N/A'}</code>\n"
                             f"<b>Reason:</b> {reason}\n"
                             f"<b>ID:</b> <code>{signal_id or 'N/A'}</code>")
                )
            except Exception as e:
                logger.debug(f"Telegram decision alert failed: {e}")

        try:
            self._thread_pool.submit(_send)
        except Exception:
            _send()

    def _lookup_position_mark_price(self, exchange: str, asset: str) -> float | None:
        try:
            if exchange == "lighter" and self.exchange_lighter:
                price = self.exchange_lighter.get_mark_price(asset)
                if price and price > 0:
                    return float(price)
        except Exception as exc:
            logger.debug(f"Lighter mark price lookup skipped for {asset}: {exc}")

        try:
            price = self.exchange_binance.get_mainnet_mark_price(asset)
            if price and price > 0:
                return float(price)
        except Exception as exc:
            logger.debug(f"Mark price lookup skipped for {asset}: {exc}")

        return None

    def _build_open_position_snapshot(self) -> dict:
        price_cache = {}

        def _price_lookup(exchange: str, asset: str) -> float | None:
            cache_key = f"{exchange}:{asset}"
            if cache_key not in price_cache:
                price_cache[cache_key] = self._lookup_position_mark_price(exchange, asset)
            return price_cache[cache_key]

        return build_position_snapshot(getattr(self.ledger, "positions", {}), price_lookup=_price_lookup)

    def _get_cb_balance(self, max_age_sec: float = 60.0):
        """Return the wallet balance for circuit breaker checks, cached for 60s.

        Returns None if balance cannot be fetched (e.g., exchange API down).
        The CB gracefully no-ops on None, preserving the previous behavior.
        """
        import time as _time
        now = _time.time()
        if (self._cb_balance_cache is not None
                and (now - self._cb_balance_cache_ts) < max_age_sec):
            return self._cb_balance_cache
        try:
            health = self.exchange_binance.get_account_health()
            if health and health.get('total_wallet_balance') is not None:
                self._cb_balance_cache = float(health['total_wallet_balance'])
                self._cb_balance_cache_ts = now
                return self._cb_balance_cache
        except Exception as exc:
            logger.debug(f"CB balance fetch failed: {exc}")
        return None

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
        """
        Brain tier check: look up strategy+symbol in tournament leaderboard.
        Criteria:
          ALPHA   = Net_DD >= -30%  AND  Daily_ROI >= 0.5%  → allowed to trade
          BLOCKED = anything else                            → rejected
        Falls back to ALPHA for unknown strategies (not in CSV yet).
        """
        import csv as _csv
        csv_paths = [
            os.path.join(os.path.dirname(__file__), "..", "..", "tournament_winners.csv"),
            "/home/ubuntu/tradingview_webhook_bot/tournament_winners.csv",
        ]
        leaderboard = None
        for p in csv_paths:
            p = os.path.abspath(p)
            if os.path.exists(p):
                try:
                    with open(p, encoding="utf-8") as f:
                        leaderboard = list(_csv.DictReader(f))
                    break
                except Exception:
                    pass

        if not leaderboard:
            logger.warning(f"Leaderboard CSV not found — open pass for {symbol} {strategy_name}")
            return True, "Leaderboard unavailable — open pass", "ALPHA"

        # Normalise for fuzzy matching
        def _norm(s):
            return re.sub(r"[^a-z0-9]", "", str(s or "").lower())

        sym_norm   = _norm(symbol)
        strat_norm = _norm(strategy_name)

        best_match = None
        for row in leaderboard:
            r_sym   = _norm(row.get("Symbol", ""))
            r_strat = _norm(row.get("Strategy", ""))
            if r_sym == sym_norm and r_strat == strat_norm:
                best_match = row
                break
            # Partial match fallback
            if best_match is None and r_sym == sym_norm and (
                strat_norm in r_strat or r_strat in strat_norm
            ):
                best_match = row

        if best_match is None:
            logger.info(f"Strategy not in leaderboard — open pass: {symbol} / {strategy_name}")
            return True, "Not in leaderboard — open pass", "ALPHA"

        tier = str(best_match.get("Tier", "")).upper()
        ndd  = float(best_match.get("Net_DD_%") or 0)
        roi  = float(best_match.get("Daily_ROI_%") or 0)

        if "BLOCKED" in tier or ndd < -30.0 or roi < 0.5:
            reason = f"Blocked: NDD={ndd:.1f}% (need>=-30%) ROI={roi:.3f}% (need>=0.5%)"
            logger.warning(f"🚫 Brain Blocked {symbol}/{strategy_name}: {reason}")
            return False, reason, "BLOCKED"

        logger.info(f"✅ Brain Approved [{tier.strip()}] {symbol}/{strategy_name} NDD={ndd:.1f}% ROI={roi:.3f}%")
        return True, f"Approved [{tier.strip()}]", tier.strip()

    def check_safety_gate(self, symbol, qty, price, side, exchange="binance", strategy="") -> tuple[bool, str]:
        if not self.allow_real:
            return False, "ALLOW_REAL_TRADES is disabled"

        notional = abs(float(qty) * float(price or 0))
        if self.max_notional > 0 and notional > self.max_notional:
            return False, f"Max notional exceeded: ${notional:.2f} > ${self.max_notional:.2f}"

        realized_pnl = self.ledger.get_daily_pnl()
        unrealized_pnl = 0.0
        try:
            if exchange == "lighter" and self.exchange_lighter:
                open_positions = self.exchange_lighter.get_open_positions()
            else:
                open_positions = self.exchange_binance.get_open_positions()
            for pos in open_positions or []:
                unrealized_pnl += float(pos.get("unrealizedProfit", pos.get("unrealized_pnl", 0)) or 0)
        except Exception as exc:
            logger.debug(f"Safety gate unrealized PnL fetch skipped: {exc}")

        total_pnl = realized_pnl + unrealized_pnl
        if total_pnl <= self.daily_loss_limit:
            return False, (
                f"Daily loss limit hit: realized=${realized_pnl:.2f} "
                f"unrealized=${unrealized_pnl:.2f} total=${total_pnl:.2f}"
            )

        base_key = f"{exchange}:{symbol}"
        strategy_key = f"{base_key}:{strategy}" if strategy else base_key
        for key, pos_obj in getattr(self.ledger, "positions", {}).items():
            if key != base_key and not key.startswith(f"{base_key}:"):
                continue
            open_qty = float(getattr(pos_obj, "quantity", 0) or 0)
            if key == strategy_key and (
                (side == "BUY" and open_qty > 0) or
                (side == "SELL" and open_qty < 0)
            ):
                return False, f"Already in {side} position for {symbol} ({strategy or 'aggregate'}) on {exchange}."

        max_strats = int(os.getenv("MAX_STRATEGIES_PER_SYMBOL", "2"))
        active_strat_count = sum(
            1 for key, pos_obj in getattr(self.ledger, "positions", {}).items()
            if (key == base_key or key.startswith(f"{base_key}:"))
            and abs(float(getattr(pos_obj, "quantity", 0) or 0)) > 0
        )
        if active_strat_count >= max_strats:
            return False, f"Max strategies per symbol reached: {active_strat_count}/{max_strats} on {symbol}"

        max_open = int(os.getenv("MAX_OPEN_POSITIONS", "16"))
        total_open = sum(
            1 for pos_obj in getattr(self.ledger, "positions", {}).values()
            if abs(float(getattr(pos_obj, "quantity", 0) or 0)) > 0
        )
        if total_open >= max_open:
            return False, f"Global position limit reached: {total_open}/{max_open} open positions"

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
            if not self._exchange_enabled(target_exchange):
                logger.warning(f"Exchange {target_exchange} not enabled by ALLOWED_EXCHANGES")
                self._notify_signal_decision(
                    title="Signal Blocked",
                    reason=f"Exchange {target_exchange} is not enabled on this bot",
                    signal_id=signal_id,
                    symbol=symbol_raw,
                    strategy=strat_name,
                    action=payload_raw.get("action") or event.get("action") or "N/A",
                    severity=AlertSeverity.WARNING,
                )
                return True

            # --- SYMBOL CLEANING ---
            symbol = symbol_raw.split('_')[0]
            if target_exchange in ("hyperliquid", "lighter"):
                symbol = symbol.replace("USDT", "").replace("USD", "") if target_exchange == "hyperliquid" else symbol
            else:
                if "USDT" not in symbol:
                    symbol = f"{symbol.replace('USD', '')}USDT"

            side_hint = str(payload_raw.get("action") or event.get("action") or "").upper()
            timeframe_hint = str(
                payload_raw.get("timeframe")
                or event.get("timeframe")
                or payload_raw.get("interval")
                or event.get("interval")
                or ""
            ).strip()
            is_exit_hint = bool(payload_raw.get("is_exit", False))
            if not is_exit_hint:
                pos_size_hint = str(payload_raw.get("position_size", event.get("position_size", ""))).strip().lower()
                if pos_size_hint in ("0", "0.0", "flat"):
                    is_exit_hint = True
                raw_body_hint = str(event.get("raw_body", ""))
                if "position is 0" in raw_body_hint.lower():
                    is_exit_hint = True

            _allowed_raw = os.getenv("ALLOWED_SYMBOLS", "").strip()
            if _allowed_raw:
                _allowed_list = [s.strip().upper() for s in _allowed_raw.split(",") if s.strip()]
                if _allowed_list and symbol not in _allowed_list:
                    logger.info(f"Symbol {symbol} not in ALLOWED_SYMBOLS {_allowed_list} - skipping")
                    self._notify_signal_decision(
                        title="Signal Blocked",
                        reason=f"Symbol {symbol} not in ALLOWED_SYMBOLS",
                        signal_id=signal_id,
                        symbol=symbol,
                        strategy=strat_name,
                        action=side_hint,
                        severity=AlertSeverity.WARNING,
                    )
                    return True

            approval_label = "EXIT_ONLY"
            if not is_exit_hint:
                is_allowed, reason, approval = self.check_strategy_approval(
                    symbol=symbol,
                    strategy_name=strat_name,
                    exchange=target_exchange,
                    timeframe=timeframe_hint,
                )
                if not is_allowed:
                    logger.warning(f"Approval Blocked: {reason}")
                    self._notify_signal_decision(
                        title="Signal Blocked",
                        reason=reason,
                        signal_id=signal_id,
                        symbol=symbol,
                        strategy=strat_name,
                        action=side_hint,
                        severity=AlertSeverity.WARNING,
                    )
                    try:
                        self.sheets_logger.log_blocked_trade(
                            symbol=symbol, side="N/A", strategy=strat_name,
                            reason=f"Approval Manifest: {reason}", signal_id=signal_id)
                    except Exception as e:
                        logger.debug(f"Sheets log failed: {e}")
                    return True
                approval_label = str(approval.get("label") or approval.get("status") or "APPROVED_MANIFEST")

            # --- 1.5. SIGNAL DEDUP CHECK ---
            if self._is_duplicate_signal(strat_name, symbol, side_hint):
                self._notify_signal_decision(
                    title="Signal Skipped",
                    reason=f"Duplicate {side_hint} signal seen within {self.DEDUP_WINDOW_SECONDS}s window",
                    signal_id=signal_id,
                    symbol=symbol,
                    strategy=strat_name,
                    action=side_hint,
                    severity=AlertSeverity.INFO,
                )
                return True

            # --- 1.6. SYMBOL COOLDOWN CHECK ---
            if self._is_symbol_in_cooldown(symbol, strat_name):
                logger.info(f"Cooldown block: {symbol} (strategy: {strat_name})")
                self._notify_signal_decision(
                    title="Signal Blocked",
                    reason=f"Cooldown active for {symbol}/{strat_name}",
                    signal_id=signal_id,
                    symbol=symbol,
                    strategy=strat_name,
                    action=side_hint,
                    severity=AlertSeverity.WARNING,
                )
                return True

            # --- 1.7. CANDLE LOCK ---
            if self._is_candle_locked(symbol, side_hint):
                try:
                    self.sheets_logger.log_blocked_trade(
                        symbol=symbol, side=side_hint, strategy=strat_name,
                        reason="Candle Lock: Symbol locked to opposite direction", signal_id=signal_id)
                except Exception as e:
                    logger.debug(f"Sheets log failed: {e}")
                self._notify_signal_decision(
                    title="Signal Blocked",
                    reason="Candle lock active: symbol locked to opposite direction",
                    signal_id=signal_id,
                    symbol=symbol,
                    strategy=strat_name,
                    action=side_hint,
                    severity=AlertSeverity.WARNING,
                )
                return True

            # --- 2. ROI GUARD (disabled: live path uses manifest approval, not research metadata) ---
            try:
                if False:
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

            # --- 3. TIER-BASED INTERACTIVE GATE (disabled: manifest approval is canonical) ---
            if False:
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

                signal_price = float(payload_raw.get("price") or event.get("price") or 0.0)

                # ── LIVE PRICE OVERRIDE (always use real Binance price) ──────────
                # Signal price from TradingView may be wrong/stale/hardcoded.
                # Prefer the target exchange price when available; otherwise
                # fall back to Binance mainnet as a common market reference.
                live_price = None
                if target_exchange == "lighter" and self.exchange_lighter:
                    live_price = self.exchange_lighter.get_mark_price(symbol)
                if not live_price:
                    live_price = self.exchange_binance.get_mainnet_mark_price(symbol)

                if live_price and live_price > 0:
                    if signal_price > 0:
                        deviation = abs(signal_price - live_price) / live_price * 100
                        if deviation > 5.0:
                            logger.warning(
                                f"⚠️ Price override [{symbol}]: signal=${signal_price:,.4f} → "
                                f"live=${live_price:,.4f} (deviation={deviation:.1f}%)"
                            )
                        else:
                            logger.debug(
                                f"Price OK [{symbol}]: signal=${signal_price:,.4f} "
                                f"live=${live_price:,.4f} ({deviation:.1f}% diff)"
                            )
                    raw_price = live_price  # ALWAYS use live price
                elif signal_price > 0:
                    # Live fetch failed — fallback to signal price with safety check
                    logger.warning(f"Live price fetch failed for {symbol}. Using signal price ${signal_price:,.4f} as fallback.")
                    raw_price = signal_price
                else:
                    logger.warning(f"Cannot resolve price for {symbol} (no live price, no signal price). Skipping.")
                    return True
                # ── END LIVE PRICE OVERRIDE ───────────────────────────────────────

                signal_data["price"] = raw_price
                signal_data["action"] = str(payload_raw.get("action") or event.get("action") or "BUY").upper()

                valid_payload = SignalPayload(**signal_data)
                payload = valid_payload.model_dump()
            except Exception as e:
                logger.error(f"Data Parsing Error: {e}")
                self._notify_signal_decision(
                    title="Signal Blocked",
                    reason=f"Data parsing error: {e}",
                    signal_id=signal_id,
                    symbol=symbol,
                    strategy=strat_name,
                    action=payload_raw.get("action") or event.get("action") or "N/A",
                    severity=AlertSeverity.WARNING,
                )
                return True

            side = "SELL" if payload["action"] in ["SELL", "TP", "EXIT", "SHORT", "OFF"] else "BUY"
            qty, price_signal = float(payload["quantity"]), float(payload["price"])
            indicator_name = payload_raw.get("indicator") or "AI_Optimized"
            ledger_pos_key = f"{target_exchange}:{symbol}:{strat_name}"

            # --- 4.5. EXIT/CLOSE HANDLING ---
            is_exit = payload_raw.get("is_exit", False)
            if not is_exit:
                pos_size = str(payload_raw.get("position_size", event.get("position_size", ""))).strip()
                if pos_size in ("0", "0.0", "flat"):
                    is_exit = True
                raw_body = str(event.get("raw_body", ""))
                if "position is 0" in raw_body.lower() or "position is -" in raw_body.lower():
                    is_exit = True
            # --- AUTO-DETECT EXIT: if signal opposes current position, treat as exit ---
            if not is_exit:
                try:
                    # Check exact strategy key first
                    current_check = self.ledger.get_position(ledger_pos_key)
                    pos_qty = float(current_check.quantity)
                    # Cross-strategy position matching DISABLED 2026-04-15
                    # Rationale: exit signals must only close the same strategy's position.
                    # Fallback to sibling strategies causes cross-routing (verified 3 cases Apr 8-14).
                    # If the exact strategy key has no position, auto-exit is not triggered.
                    if pos_qty != 0:
                        is_long = pos_qty > 0
                        signal_is_sell = side == "SELL"
                        if (is_long and signal_is_sell) or (not is_long and not signal_is_sell):
                            is_exit = True
                            logger.info(f"Auto-detected exit: {side} signal opposes open {'LONG' if is_long else 'SHORT'} on {ledger_pos_key}")
                except (TypeError, ValueError, AttributeError):
                    pass  # ledger not available or quantity not numeric

            if is_exit:
                strategy_pos_key = ledger_pos_key
                aggregate_pos_key = f"{target_exchange}:{symbol}"
                current_pos = self.ledger.get_position(strategy_pos_key)
                if current_pos.quantity == 0:
                    # Cross-strategy aggregate fallback DISABLED 2026-04-15
                    # Exit must match the exact strategy key — no cross-routing.
                    logger.info(
                        f"Exit signal for {strat_name}/{symbol} but no open position on "
                        f"{strategy_pos_key}. Skipping to prevent cross-routing."
                    )
                    self._notify_signal_decision(
                        title="Signal Skipped",
                        reason=(
                            f"Exit signal received for {strat_name} on {symbol}, "
                            f"but no open position exists under {strategy_pos_key}. "
                            f"Cross-routing prevention active."
                        ),
                        signal_id=signal_id,
                        symbol=symbol,
                        strategy=strat_name,
                        action=payload.get("action", side),
                        severity=AlertSeverity.INFO,
                    )
                    return True
                if current_pos.quantity > 0:
                    side = "SELL"
                    qty = abs(current_pos.quantity)
                elif current_pos.quantity < 0:
                    side = "BUY"
                    qty = abs(current_pos.quantity)
                logger.info(f"Exit signal: closing {ledger_pos_key} position ({current_pos.quantity}) with {side} {qty}")
                try:
                    if target_exchange == "binance":
                        cancel_ok = self.exchange_binance.cancel_open_orders(symbol)
                    elif target_exchange == "lighter" and self.exchange_lighter:
                        cancel_ok = self.exchange_lighter.cancel_open_orders(symbol)
                    else:
                        cancel_ok = True
                    logger.info(f"Protective order cancel before exit: {'OK' if cancel_ok else 'WARN'}")
                except Exception as cancel_error:
                    logger.warning(f"Protective order cancel before exit failed: {cancel_error}")

            # --- 4.9. KILL SWITCH CHECK ---
            kill_file = os.path.join(os.path.dirname(self.ledger_path), "KILL_SWITCH")
            if os.path.exists(kill_file):
                logger.critical("KILL SWITCH ACTIVE — blocking all trades")
                return True

            # --- 4.95. CIRCUIT BREAKER CHECK ---
            if self.circuit_breaker and not self.circuit_breaker.should_allow_trade(
                    current_balance=self._get_cb_balance()):
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
                is_safe, risk_reason = self.check_safety_gate(
                    symbol, qty, price_signal, side, exchange=target_exchange, strategy=strat_name
                )
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
            if not is_exit and size_mode == "equity_pct":
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

            # Max qty cap for new entries. Exits must be allowed to close full size.
            if not is_exit:
                max_allowed = self.MAX_QTY.get(symbol, 1.0)
                if qty > max_allowed:
                    logger.warning(f"Qty capped: {qty} -> {max_allowed} for {symbol}")
                    qty = max_allowed
                final_notional = abs(float(qty) * float(price_signal or 0))
                if self.max_notional > 0 and final_notional > self.max_notional:
                    reason = f"Max notional exceeded after sizing: ${final_notional:.2f} > ${self.max_notional:.2f}"
                    logger.warning(f"Safety Gate Block: {reason}")
                    self._notify_signal_decision(
                        title="Signal Blocked",
                        reason=reason,
                        signal_id=signal_id,
                        symbol=symbol,
                        strategy=strat_name,
                        action=side,
                        severity=AlertSeverity.WARNING,
                    )
                    try:
                        self.sheets_logger.log_blocked_trade(
                            symbol=symbol, side=side, strategy=strat_name,
                            reason=f"Safety Gate: {reason}", signal_id=signal_id)
                    except Exception as e:
                        logger.debug(f"Sheets log failed: {e}")
                    return True

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
                pre_snapshot = self.ledger.get_position(ledger_pos_key).model_copy(deep=True)
                # Resolve actual filled qty from exchange response (fix_quantity rounds up inside
                # execute_futures_order, so ledger must use the same adjusted qty to avoid drift).
                _exec_qty = float(execution_res.get("executedQty") or execution_res.get("origQty") or 0)
                ledger_qty = _exec_qty if _exec_qty > 0 else qty
                try:
                    pos_snapshot = self.ledger.apply_fill(ledger_pos_key, side, ledger_qty, fill_price)
                except Exception as e:
                    logger.critical(f"LEDGER WRITE FAILED: {e}. Trade OK but ledger desynced!")
                    def _alert_desync():
                        try:
                            self.telegram.send(severity=AlertSeverity.CRITICAL, title="LEDGER DESYNC",
                                message=f"Ledger write failed for {side} {qty} {symbol} @ {fill_price}. MANUAL FIX NEEDED.", force=True)
                        except: pass
                    self._thread_pool.submit(_alert_desync)
                    pos_snapshot = self.ledger.get_position(ledger_pos_key)

                self._mark_symbol_traded(symbol, strat_name)

                try:
                    signal_price_used = float(price_signal or 0.0)
                except (TypeError, ValueError):
                    signal_price_used = 0.0
                try:
                    reference_price = float(execution_res.get("reference_price") or signal_price_used or fill_price or 0.0)
                except (TypeError, ValueError):
                    reference_price = float(fill_price or 0.0)
                estimated_fee_bps = estimate_fee_bps(target_exchange, execution_res)
                fill_notional = abs(float(ledger_qty) * float(fill_price or 0.0))
                estimated_fee_usd = fill_notional * estimated_fee_bps / 10000 if fill_notional > 0 else 0.0
                latency_impact_usd = abs(reference_price - signal_price_used) * abs(float(ledger_qty)) if reference_price > 0 and signal_price_used > 0 else 0.0
                execution_slippage_usd = abs(float(fill_price or 0.0) - reference_price) * abs(float(ledger_qty)) if float(fill_price or 0.0) > 0 and reference_price > 0 else 0.0
                realized_pnl_delta = float(pos_snapshot.realized_pnl - pre_snapshot.realized_pnl)
                gross_edge_usd = None
                if is_exit:
                    gross_edge_usd = realized_pnl_delta + estimated_fee_usd + latency_impact_usd + execution_slippage_usd
                try:
                    append_execution_metric({
                        "timestamp_epoch": time.time(),
                        "signal_id": signal_id,
                        "exchange": target_exchange,
                        "symbol": symbol,
                        "strategy": strat_name,
                        "side": side,
                        "is_exit": bool(is_exit),
                        "qty": float(qty),
                        "signal_price": signal_price_used,
                        "reference_price": reference_price,
                        "fill_price": float(fill_price or 0.0),
                        "fill_notional_usd": fill_notional,
                        "estimated_fee_bps": estimated_fee_bps,
                        "estimated_fee_usd": estimated_fee_usd,
                        "latency_impact_usd": latency_impact_usd,
                        "execution_slippage_usd": execution_slippage_usd,
                        "realized_pnl_usd": realized_pnl_delta,
                        "gross_edge_usd": gross_edge_usd,
                        "order_type_used": execution_res.get("order_type_used", ""),
                        "paper": bool(execution_res.get("paper", False)),
                    }, path=self.execution_metrics_path)
                except Exception as telemetry_error:
                    logger.warning(f"Execution telemetry append failed: {telemetry_error}")

                # Place exchange-side stop-loss
                if not is_exit and target_exchange == "lighter" and self.exchange_lighter:
                    sig_sl = float(payload_raw.get("sl_pct", 0) or 0)
                    sig_tp = float(payload_raw.get("tp_pct", 0) or 0)
                    sl_pct = sig_sl if 0 < sig_sl < 20.0 else float(os.getenv("STOP_LOSS_PCT", "3.0"))
                    tp_pct = sig_tp if 0 < sig_tp < 50.0 else float(os.getenv("TAKE_PROFIT_PCT", "4.5"))
                    sl_res = self.exchange_lighter.place_stop_loss(symbol, side, qty, fill_price, sl_pct=sl_pct, signal_id=signal_id)
                    if sl_res.get("status") == "SUCCESS":
                        logger.info(f"Lighter SL placed for {symbol} @ ${sl_res.get('stopPrice')}")
                    else:
                        logger.warning(f"Lighter SL failed for {symbol}: {sl_res.get('msg')}")
                    tp_res = self.exchange_lighter.place_take_profit(symbol, side, qty, fill_price, tp_pct=tp_pct, signal_id=signal_id)
                    if tp_res.get("status") == "SUCCESS":
                        logger.info(f"Lighter TP placed for {symbol} @ ${tp_res.get('tpPrice')}")
                    else:
                        logger.warning(f"Lighter TP failed for {symbol}: {tp_res.get('msg')}")
                if not is_exit and target_exchange == "binance":
                    sig_sl = float(payload_raw.get("sl_pct", 0) or 0)
                    sig_tp = float(payload_raw.get("tp_pct", 0) or 0)
                    sl_pct = sig_sl if 0 < sig_sl < 20.0 else float(os.getenv("STOP_LOSS_PCT", "3.0"))
                    tp_pct = sig_tp if 0 < sig_tp < 50.0 else float(os.getenv("TAKE_PROFIT_PCT", "4.5"))
                    sl_res = self.exchange_binance.place_stop_loss(symbol, side, qty, fill_price, sl_pct=sl_pct, signal_id=signal_id)
                    if sl_res.get("status") == "SUCCESS":
                        logger.info(f"SL placed for {symbol} @ ${sl_res.get('stopPrice')}")
                    else:
                        logger.warning(f"SL placement failed for {symbol}: {sl_res.get('msg')}")
                    tp_res = self.exchange_binance.place_take_profit(symbol, side, qty, fill_price, tp_pct=tp_pct, signal_id=signal_id)
                    if tp_res.get("status") == "SUCCESS":
                        logger.info(f"TP placed for {symbol} @ ${tp_res.get('tpPrice')}")
                    else:
                        logger.warning(f"TP placement failed for {symbol}: {tp_res.get('msg')}")

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

                # Record win/loss for circuit breaker (only on exit/close trades)
                if self.circuit_breaker and is_exit:
                    self.circuit_breaker.record_trade_result(pos_snapshot.daily_realized_pnl >= 0)

                # Auto-update analytics on every trade
                # Async: non-blocking analytics update
                def _update_analytics():
                    try:
                        self.analytics.update_today()
                    except Exception as ae:
                        logger.warning(f"Analytics update skipped (async): {ae}")
                self._thread_pool.submit(_update_analytics)

                # Determine trade type: Open Long/Short or Close Long/Short
                if is_exit:
                    trade_type = "Close Long" if side == "SELL" else "Close Short"
                    trade_emoji = "🔻" if side == "SELL" else "🔺"
                else:
                    trade_type = "Open Long" if side == "BUY" else "Open Short"
                    trade_emoji = "🟢" if side == "BUY" else "🔴"

                # Build SL/TP info for entry trades
                sl_tp_info = ""
                if not is_exit and target_exchange in ("binance", "lighter"):
                    sig_sl = float(payload_raw.get("sl_pct", 0) or 0)
                    sig_tp = float(payload_raw.get("tp_pct", 0) or 0)
                    sl_pct_val = sig_sl if 0 < sig_sl < 20.0 else float(os.getenv("STOP_LOSS_PCT", "3.0"))
                    tp_pct_val = sig_tp if 0 < sig_tp < 50.0 else float(os.getenv("TAKE_PROFIT_PCT", "4.5"))
                    if side == "BUY":
                        sl_price_est = fill_price * (1 - sl_pct_val / 100)
                        tp_price_est = fill_price * (1 + tp_pct_val / 100)
                    else:
                        sl_price_est = fill_price * (1 + sl_pct_val / 100)
                        tp_price_est = fill_price * (1 - tp_pct_val / 100)
                    sl_tp_info = (
                        f"\n🛡️ <b>Stop-Loss:</b> <code>${sl_price_est:,.2f}</code> ({sl_pct_val}%)"
                        f"\n🎯 <b>Take-Profit:</b> <code>${tp_price_est:,.2f}</code> ({tp_pct_val}%)"
                    )

                # Build P&L info for exit trades
                pnl_info = f"\n💵 <b>Today PnL:</b> <code>${pos_snapshot.daily_realized_pnl:.2f}</code>"
                if is_exit and pos_snapshot.realized_pnl != 0:
                    pnl_info += f"\n📊 <b>Realized PnL:</b> <code>${pos_snapshot.realized_pnl:.2f}</code>"
                open_position_info = format_positions_for_telegram(
                    self._build_open_position_snapshot(),
                    limit=3,
                )

                try:
                    self.telegram.send(severity=AlertSeverity.INFO, title="Trade Success",
                        message=(f"{trade_emoji} <b>{trade_type}: {symbol}</b>\n\n"
                                 f"📌 <b>Type:</b> {trade_type}\n"
                                 f"💰 <b>Price:</b> <code>${fill_price:,.2f}</code>\n"
                                 f"📊 <b>Quantity:</b> <code>{qty}</code>\n"
                                 f"📋 <b>Strategy:</b> <code>{strat_name}</code>\n"
                                 f"📈 <b>Approval:</b> {approval_label}"
                                 f"{sl_tp_info}"
                                 f"{pnl_info}\n\n"
                                 f"{open_position_info}\n"
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

    def _run_reconcile(self):
        exchange_data = {}
        if self._exchange_enabled("binance"):
            try:
                for pos in self.exchange_binance.get_open_positions() or []:
                    sym = pos.get("symbol", "")
                    qty = float(pos.get("positionAmt", 0) or 0)
                    if abs(qty) > 0:
                        exchange_data[f"binance:{sym}"] = {
                            "quantity": qty,
                            "side": "LONG" if qty > 0 else "SHORT",
                            "entry_price": float(pos.get("entryPrice") or 0),
                        }
            except Exception as exc:
                logger.warning(f"Binance reconciler fetch failed: {exc}")
        else:
            logger.debug("Binance reconciler skipped by ALLOWED_EXCHANGES")

        if self.exchange_lighter and self._exchange_enabled("lighter"):
            if not getattr(self.exchange_lighter, "can_trade", False):
                logger.debug("Lighter reconciler skipped in paper mode")
            else:
                try:
                    for pos in self.exchange_lighter.get_open_positions() or []:
                        sym = pos.get("symbol", "")
                        qty = float(pos.get("quantity", pos.get("positionAmt", 0)) or 0)
                        if abs(qty) > 0:
                            exchange_data[f"lighter:{sym}"] = {
                                "quantity": qty,
                                "side": "LONG" if qty > 0 else "SHORT",
                                "entry_price": float(pos.get("entry_price", pos.get("entryPrice", 0)) or 0),
                            }
                except Exception as exc:
                    logger.warning(f"Lighter reconciler fetch failed: {exc}")
        elif self.exchange_lighter:
            logger.debug("Lighter reconciler skipped by ALLOWED_EXCHANGES")

        if not exchange_data:
            return

        alerts = self.reconciler.reconcile_with_exchange(exchange_data)
        for alert_msg in alerts:
            try:
                self.telegram.send(
                    severity=AlertSeverity.WARNING,
                    title="Reconciler Fix",
                    message=alert_msg,
                )
            except Exception:
                pass
        if alerts:
            logger.info(f"Reconciler: {len(alerts)} drift(s) fixed")

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
            if time.time() - self.last_reconcile > self.RECONCILE_INTERVAL:
                self.last_reconcile = time.time()
                self._thread_pool.submit(self._run_reconcile)
            if time.time() - self.last_heartbeat > 900:
                heartbeat_snapshot = self._build_open_position_snapshot()
                logger.info(
                    "Heartbeat: Orchestrator running. Processed: %s | %s",
                    self.processed_count,
                    format_positions_for_log(heartbeat_snapshot, limit=5),
                )
                self.last_heartbeat = time.time()
            time.sleep(1)

        logger.info("Shutting down thread pool...")
        self._thread_pool.shutdown(wait=True, cancel_futures=False)
        logger.info(f"Orchestrator stopped gracefully. Total processed: {self.processed_count}")


if __name__ == "__main__":
    Orchestrator().run()
