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

    def auto_register_strategy(self, symbol: str, strategy_name: str) -> tuple[str, dict]:
        """
        Auto-backtest a brand-new strategy on live historical data and register
        it in tournament_winners.csv.  Called the first time an unknown strategy
        sends a signal.  Returns (tier, result_dict).
        """
        import csv as _csv
        import requests as _requests

        BASE        = str(PROJECT_ROOT)
        DATA_DIR    = os.path.join(BASE, "storage", "backtest_data")
        PINE_FOLDER = os.path.join(BASE, "backtesting", "pine")
        ROOT_CSV    = os.path.join(BASE, "tournament_winners.csv")
        REPORT_CSV  = self.report_path

        logger.info(f"[AutoRegister] 🆕 Unknown strategy '{strategy_name}' on {symbol} — starting auto-backtest…")

        # ── 1. Create pine stub (filename = strategy name) ──────────────────
        os.makedirs(PINE_FOLDER, exist_ok=True)
        pine_path = os.path.join(PINE_FOLDER, strategy_name)
        if not os.path.exists(pine_path):
            with open(pine_path, "w") as _f:
                _f.write(strategy_name)
            logger.info(f"[AutoRegister] Created pine stub: {pine_path}")

        # ── 2. Ensure historical data exists ────────────────────────────────
        os.makedirs(DATA_DIR, exist_ok=True)
        data_path = os.path.join(DATA_DIR, f"{symbol}_3y_15m.csv")
        if not os.path.exists(data_path) or os.path.getsize(data_path) < 100_000:
            logger.info(f"[AutoRegister] Downloading 3y 15m data for {symbol}…")
            try:
                url       = "https://fapi.binance.com/fapi/v1/klines"
                all_kl    = []
                start_ms  = int((time.time() - 3 * 365 * 24 * 3600) * 1000)
                while True:
                    resp   = _requests.get(url, params={"symbol": symbol, "interval": "15m",
                                                        "startTime": start_ms, "limit": 1500}, timeout=20)
                    klines = resp.json()
                    if not isinstance(klines, list) or not klines:
                        break
                    all_kl.extend(klines)
                    if len(klines) < 1500:
                        break
                    start_ms = klines[-1][0] + 1
                    time.sleep(0.3)
                if len(all_kl) >= 500:
                    with open(data_path, "w", newline="") as _f:
                        w = _csv.writer(_f)
                        w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
                        for k in all_kl:
                            w.writerow([k[0], k[1], k[2], k[3], k[4], k[5]])
                    logger.info(f"[AutoRegister] Downloaded {len(all_kl):,} candles for {symbol}")
                else:
                    logger.warning(f"[AutoRegister] Only {len(all_kl)} candles fetched for {symbol} — too few")
            except Exception as _e:
                logger.warning(f"[AutoRegister] Data download failed for {symbol}: {_e}")

        # ── 3. Load data ─────────────────────────────────────────────────────
        try:
            df_raw = pd.read_csv(data_path)
            for _col in ["open", "high", "low", "close", "volume"]:
                df_raw[_col] = pd.to_numeric(df_raw[_col], errors="coerce")
            df_raw["pct"] = df_raw["close"].pct_change()
            if len(df_raw) < 500:
                raise ValueError(f"Only {len(df_raw)} rows — insufficient")
        except Exception as _e:
            logger.warning(f"[AutoRegister] Cannot load data for {symbol}: {_e} — blocking until data is available")
            return "🚫 BLOCKED", {}

        # ── 4. Run param grid backtest ───────────────────────────────────────
        PARAM_GRID = [
            {"mult": 1.5, "len": 7},
            {"mult": 2.0, "len": 11},
            {"mult": 2.5, "len": 14},
            {"mult": 3.0, "len": 18},
            {"mult": 3.5, "len": 21},
        ]
        try:
            scripts_dir = os.path.join(BASE, "scripts")
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)
            from scripts.strategy_tournament import run_test, run_test_oos  # noqa
        except Exception as _e:
            logger.warning(f"[AutoRegister] Cannot import strategy_tournament: {_e} — blocking until engine available")
            return "🚫 BLOCKED", {}

        best_daily = -999
        best_res   = None
        for _i, _p in enumerate(PARAM_GRID):
            try:
                _mult   = _p["mult"] + (_i * 0.01)
                _length = _p["len"]  + (_i % 3)
                _res    = run_test(df_raw, strategy_name, True, _mult, _length)
                _daily, _gdd, _ndd, _wr, _sh, _tr, _st, _gd, _nd, *_ = _res
                if _daily > best_daily and _st != "💀 ERROR":
                    best_daily = _daily
                    best_res   = (_daily, _gdd, _ndd, _wr, _sh, _tr, _st,
                                  {"mult": _mult, "len": _length}, _gd, _nd)
            except Exception:
                continue

        if not best_res:
            logger.warning(f"[AutoRegister] All backtest runs failed for {strategy_name}/{symbol} — blocking")
            return "🚫 BLOCKED", {}

        daily_roi, gross_dd, net_dd, win_rate, sharpe, trades, _, opt_p, gdd_date, ndd_date = best_res

        # ── 5. Out-of-sample validation ──────────────────────────────────────
        oos_roi = oos_dd = oos_sharpe = 0.0
        try:
            _, _oos = run_test_oos(df_raw, strategy_name, opt_p["mult"], opt_p["len"])
            oos_roi    = _oos[0]
            oos_dd     = _oos[1]
            oos_sharpe = _oos[4]
        except Exception:
            pass

        # ── 6. Tier decision: NDD >= -30% AND ROI >= 0.5% ───────────────────
        tier = "✅ ALPHA" if (net_dd >= -30.0 and daily_roi >= 0.5) else "🚫 BLOCKED"

        result_row = {
            "Symbol":       symbol,
            "Strategy":     strategy_name,
            "Daily_ROI_%":  round(daily_roi, 3),
            "Gross_DD_%":   round(gross_dd, 2),
            "Net_DD_%":     round(net_dd, 2),
            "Win_Rate_%":   win_rate,
            "Sharpe_Ratio": sharpe,
            "Trade_Count":  trades,
            "OOS_ROI_%":    round(oos_roi, 3),
            "OOS_DD_%":     round(oos_dd, 2),
            "OOS_Sharpe":   round(oos_sharpe, 2),
            "Best_Mult":    round(opt_p["mult"], 2),
            "Best_Len":     opt_p["len"],
            "Max_DD_Date":  gdd_date,
            "NDD_Date":     ndd_date,
            "Tier":         tier,
        }

        # ── 7. Append to both CSV copies ────────────────────────────────────
        _fnames = ["Symbol","Strategy","Daily_ROI_%","Gross_DD_%","Net_DD_%",
                   "Win_Rate_%","Sharpe_Ratio","Trade_Count","OOS_ROI_%","OOS_DD_%",
                   "OOS_Sharpe","Best_Mult","Best_Len","Max_DD_Date","NDD_Date","Tier"]
        for _csv_path in set([REPORT_CSV, ROOT_CSV]):
            try:
                _exists = os.path.exists(_csv_path)
                with open(_csv_path, "a", newline="", encoding="utf-8") as _f:
                    _w = _csv.DictWriter(_f, fieldnames=_fnames)
                    if not _exists:
                        _w.writeheader()
                    _w.writerow(result_row)
            except Exception as _e:
                logger.warning(f"[AutoRegister] CSV write to {_csv_path} failed: {_e}")

        logger.info(f"[AutoRegister] ✅ Registered '{strategy_name}' / {symbol}: "
                    f"{tier} | ROI={daily_roi:.3f}%/day | GDD={gross_dd:.2f}% | NDD={net_dd:.2f}% | WR={win_rate}% | Trades={trades}")

        # ── 8. If BLOCKED, test REVERSE strategy ─────────────────────────────
        reverse_tier = None
        reverse_row  = {}
        if "BLOCKED" in tier:
            logger.info(f"[AutoRegister] Strategy BLOCKED — testing REVERSE signals for '{strategy_name}' / {symbol}…")
            rev_best_daily = -999
            rev_best_res   = None
            for _i, _p in enumerate(PARAM_GRID):
                try:
                    _mult   = _p["mult"] + (_i * 0.01)
                    _length = _p["len"]  + (_i % 3)
                    _res    = run_test(df_raw, strategy_name, True, _mult, _length, reverse=True)
                    _daily, _gdd, _ndd, _wr, _sh, _tr, _st, _gd, _nd, *_ = _res
                    if _daily > rev_best_daily and _st != "💀 ERROR":
                        rev_best_daily = _daily
                        rev_best_res   = (_daily, _gdd, _ndd, _wr, _sh, _tr, _st,
                                          {"mult": _mult, "len": _length}, _gd, _nd)
                except Exception:
                    continue

            if rev_best_res:
                r_roi, r_gdd, r_ndd, r_wr, r_sh, r_tr, _, r_opt, r_gd, r_nd = rev_best_res
                r_oos_roi = r_oos_dd = r_oos_sh = 0.0
                try:
                    _, _roos = run_test_oos(df_raw, strategy_name, r_opt["mult"], r_opt["len"], reverse=True)
                    r_oos_roi = _roos[0]; r_oos_dd = _roos[1]; r_oos_sh = _roos[4] if len(_roos) > 4 else 0.0
                except Exception:
                    pass

                reverse_tier = "✅ REVERSE_ALPHA" if (r_ndd >= -30.0 and r_roi >= 0.5) else "🚫 REVERSE_BLOCKED"
                rev_name     = f"REVERSE_{strategy_name}"

                reverse_row = {
                    "Symbol": symbol, "Strategy": rev_name,
                    "Daily_ROI_%": round(r_roi, 3), "Gross_DD_%": round(r_gdd, 2),
                    "Net_DD_%": round(r_ndd, 2), "Win_Rate_%": r_wr,
                    "Sharpe_Ratio": r_sh, "Trade_Count": r_tr,
                    "OOS_ROI_%": round(r_oos_roi, 3), "OOS_DD_%": round(r_oos_dd, 2),
                    "OOS_Sharpe": round(r_oos_sh, 2),
                    "Best_Mult": round(r_opt["mult"], 2), "Best_Len": r_opt["len"],
                    "Max_DD_Date": r_gd, "NDD_Date": r_nd, "Tier": reverse_tier,
                }
                for _csv_path in set([REPORT_CSV, ROOT_CSV]):
                    try:
                        _exists = os.path.exists(_csv_path)
                        with open(_csv_path, "a", newline="", encoding="utf-8") as _f:
                            _w = _csv.DictWriter(_f, fieldnames=_fnames)
                            if not _exists:
                                _w.writeheader()
                            _w.writerow(reverse_row)
                    except Exception as _e:
                        logger.warning(f"[AutoRegister] Reverse CSV write failed: {_e}")

                logger.info(f"[AutoRegister] Reverse result: {reverse_tier} | ROI={r_roi:.3f}% | NDD={r_ndd:.2f}%")

        # ── 9. Telegram notification ──────────────────────────────────────────
        try:
            _icon    = "✅" if "ALPHA" in tier else "🚫"
            _verdict = "Signal APPROVED ✅" if "ALPHA" in tier else "Signal BLOCKED 🚫"

            _rev_section = ""
            if reverse_tier is not None:
                _r_icon = "✅" if "ALPHA" in reverse_tier else "🚫"
                _r_roi  = reverse_row.get("Daily_ROI_%", "?")
                _r_ndd  = reverse_row.get("Net_DD_%", "?")
                _r_wr   = reverse_row.get("Win_Rate_%", "?")
                _rev_section = (f"\n\n🔄 <b>Reverse Test:</b>\n"
                                f"  {_r_icon} <b>Tier:</b> {reverse_tier}\n"
                                f"  📈 ROI: {_r_roi}%  📉 NDD: {_r_ndd}%  🎯 WR: {_r_wr}%\n"
                                f"  {'✅ Reverse signal will execute (BUY↔SELL flipped)' if 'ALPHA' in str(reverse_tier) else '🚫 Reverse also blocked'}")

            self.telegram.send(
                severity=AlertSeverity.INFO,
                title="New Strategy Auto-Registered",
                message=(f"🧠 <b>Auto-Backtest Complete</b>\n\n"
                         f"📋 <b>Strategy:</b> <code>{strategy_name}</code>\n"
                         f"💹 <b>Symbol:</b> {symbol}\n"
                         f"{_icon} <b>Tier:</b> {tier}\n"
                         f"📈 <b>Daily ROI:</b> {daily_roi:.3f}%\n"
                         f"📉 <b>Max NDD:</b> {net_dd:.2f}%\n"
                         f"📉 <b>Gross DD:</b> {gross_dd:.2f}%\n"
                         f"🎯 <b>Win Rate:</b> {win_rate}%\n"
                         f"🔢 <b>Trades:</b> {trades}\n"
                         f"📊 <b>OOS ROI:</b> {oos_roi:.3f}%"
                         f"{_rev_section}\n\n"
                         f"<b>{_verdict}</b>"))
        except Exception:
            pass

        # If original BLOCKED but reverse is ALPHA — surface REVERSE_ALPHA as the effective tier
        effective_tier = reverse_tier if (reverse_tier and "ALPHA" in str(reverse_tier)) else tier
        return effective_tier, result_row

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
            import re as _re
            # Drop rows with corrupted Tier values (e.g. date strings like "2023-10-16")
            _valid_tier_re = _re.compile(r'ALPHA|AVERAGE|REJECT|ERROR', _re.IGNORECASE)
            df = df[df['Tier'].astype(str).apply(lambda t: bool(_valid_tier_re.search(t)))]
            def _normalize(s):
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
                # Check if a REVERSE_ version was already registered
                rev_name   = f"REVERSE_{strategy_name}"
                rev_clean  = _normalize(rev_name)
                def _rev_match(s): n = _normalize(s); return rev_clean in n or n in rev_clean
                rev_match  = df[(df['Symbol'].str.contains(symbol, case=False)) & (df['Strategy'].apply(_rev_match))]
                if not rev_match.empty:
                    rev_tier = str(rev_match.iloc[0].get('Tier', ''))
                    if "ALPHA" in rev_tier:
                        logger.info(f"[AutoRegister] Reverse ALPHA found for '{strategy_name}' / {symbol} — flipping signal")
                        return True, f"REVERSE_ALPHA: {rev_name}", "REVERSE_ALPHA"

                # ── AUTO-REGISTER: run instant backtest, add to CSV ──────────
                logger.info(f"[AutoRegister] Strategy '{strategy_name}' not in leaderboard for {symbol}. "
                            f"Triggering auto-backtest…")
                tier, result = self.auto_register_strategy(symbol, strategy_name)
                if "REVERSE_ALPHA" in tier or ("ALPHA" in tier and "REVERSE" not in tier):
                    if "REVERSE" in tier:
                        return True, f"Auto-registered ✅ REVERSE_ALPHA: {strategy_name}", "REVERSE_ALPHA"
                    return True, f"Auto-registered ✅ ALPHA: {strategy_name}", "ALPHA"
                else:
                    roi = result.get("Daily_ROI_%", "?")
                    ndd = result.get("Net_DD_%", "?")
                    return False, (f"Auto-registered 🚫 BLOCKED: {strategy_name} "
                                   f"| ROI={roi}%/day  NDD={ndd}%"), "BLOCKED"
            row = match.iloc[0]
            tier = str(row.get('Tier', ''))
            if "ALPHA" in tier: return True, "Verified ALPHA: Direct Execution", "ALPHA"
            if "AVERAGE" in tier: return True, "Verified AVERAGE: Human Approval Needed", "AVERAGE"
            return False, f"Strategy Tier is {tier}. Blocked.", tier
        except Exception as e:
            logger.error(f"Leaderboard Check Error: {e}")
            return False, f"Leaderboard check failed: {e}", "ERROR"

    def check_safety_gate(self, symbol, qty, price, side, exchange="binance", strategy="") -> tuple[bool, str]:
        if not self.allow_real: return False, "ALLOW_REAL_TRADES is disabled"

        # --- Realized PnL check ---
        realized_pnl = self.ledger.get_daily_pnl()

        # --- Unrealized PnL check (add open position mark-to-market loss) ---
        unrealized_pnl = 0.0
        try:
            open_positions = self.exchange_binance.get_open_positions()
            for pos in open_positions:
                unrealized_pnl += float(pos.get("unrealizedProfit", 0) or 0)
        except Exception as _e:
            logger.debug(f"check_safety_gate: unrealized PnL fetch skipped: {_e}")

        total_pnl = realized_pnl + unrealized_pnl
        if total_pnl <= self.daily_loss_limit:
            return False, (f"Daily loss limit hit: realized=${realized_pnl:.2f} "
                           f"unrealized=${unrealized_pnl:.2f} total=${total_pnl:.2f}")

        # --- Per-strategy position check ---
        pos_key = f"{exchange}:{symbol}:{strategy}" if strategy else f"{exchange}:{symbol}"
        current_pos = self.ledger.get_position(pos_key)
        if (side == "BUY" and current_pos.quantity > 0) or (side == "SELL" and current_pos.quantity < 0):
            return False, f"Already in {side} position for {symbol} ({strategy}) on {exchange}."

        # --- Max strategies per symbol check ---
        max_strats = int(os.getenv("MAX_STRATEGIES_PER_SYMBOL", "2"))
        active_strat_count = sum(
            1 for key, pos_obj in getattr(self.ledger, 'positions', {}).items()
            if f"{exchange}:{symbol}" in key and abs(float(getattr(pos_obj, 'quantity', 0))) > 0
        )
        if active_strat_count >= max_strats:
            return False, (f"Max strategies per symbol reached: {active_strat_count}/{max_strats} "
                           f"already active on {symbol}")

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
            strat_name = self._normalize_strategy(strat_name_raw)
            symbol_raw = str(payload_raw.get("symbol") or event.get("symbol") or "BTCUSDT").upper()

            # --- SYMBOL CLEANING ---
            symbol = symbol_raw.split('_')[0]
            if target_exchange in ("lighter",):
                pass  # lighter uses symbol as-is (no USDT suffix)
            elif target_exchange == "hyperliquid":
                symbol = symbol.replace("USDT", "").replace("USD", "")
            else:
                if "USDT" not in symbol:
                    symbol = f"{symbol.replace('USD', '')}USDT"

            # --- 1. BRAIN TIER CHECK ---
            is_allowed, reason, tier = self.check_tournament_alpha(symbol, strat_name)
            if not is_allowed:
                logger.warning(f"[{correlation_id}] AI Blocked: {reason}")
                try:
                    self.sheets_logger.log_blocked_trade(
                        symbol=symbol, side="N/A", strategy=strat_name,
                        reason=f"Tier Block: {reason}", signal_id=signal_id)
                except Exception as e:
                    logger.debug(f"Sheets log failed: {e}")
                metrics.inc("bot_signals_blocked_total", labels={"reason": "tier_block"})
                return True

            # --- 1.2. REVERSE SIGNAL FLIP (if backtest says reverse is ALPHA) ---
            _reverse_active = "REVERSE_ALPHA" in tier
            if _reverse_active:
                _orig_action = str(payload_raw.get("action") or event.get("action") or "BUY").upper()
                _flipped     = "SELL" if _orig_action in ("BUY", "LONG") else "BUY"
                payload_raw["action"] = _flipped
                if isinstance(event.get("payload"), dict):
                    event["payload"]["action"] = _flipped
                logger.info(f"[{correlation_id}] 🔄 REVERSE mode: {_orig_action} → {_flipped} for {strat_name}/{symbol}")

            # --- 1.5. SIGNAL DEDUP CHECK ---
            side_hint = str(payload_raw.get("action") or event.get("action") or "").upper()
            if self._is_duplicate_signal(strat_name, symbol, side_hint):
                return True

            # --- 1.6. SYMBOL COOLDOWN CHECK ---
            if self._is_symbol_in_cooldown(symbol, strat_name):
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
                if raw_price <= 0:
                    live_price = self.exchange_binance.get_mainnet_mark_price(symbol)
                    if live_price and live_price > 0:
                        raw_price = live_price
                        logger.info(f"[{correlation_id}] Resolved price for {symbol}: ${raw_price}")
                    else:
                        logger.warning(f"[{correlation_id}] Cannot resolve price for {symbol}. Skipping.")
                        return True
                signal_data["price"] = raw_price
                signal_data["action"] = str(payload_raw.get("action") or event.get("action") or "BUY").upper()

                valid_payload = SignalPayload(**signal_data)
                payload = valid_payload.model_dump()
            except Exception as e:
                logger.error(f"[{correlation_id}] Data Parsing Error: {e}")
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
                # Cancel any open SL/TP orders BEFORE placing the close order to avoid
                # double-fills: if SL hit first AND we then market-close, both execute.
                if target_exchange == "binance":
                    cancel_ok = self.exchange_binance.cancel_open_orders(symbol)
                    logger.info(f"[{correlation_id}] SL/TP cancel before exit: {'OK' if cancel_ok else 'WARN — cancel may have failed'}")

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
                        # Always use live market price for position sizing — signal price may be stale
                        _sizing_price = self.exchange_binance.get_mainnet_mark_price(symbol) or price_signal
                        if avail > 0 and _sizing_price > 0:
                            qty = (avail * equity_pct) / _sizing_price
                            logger.info(f"[{correlation_id}] Equity sizing: {equity_pct*100}% of ${avail:.2f} @ ${_sizing_price:.2f} = {qty:.6f} {symbol}")
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

                # --- TIMEOUT RECOVERY: order may have been submitted but response lost ---
                if execution_res.get("status") == "TIMEOUT":
                    _coid = execution_res.get("client_order_id", signal_id)
                    logger.warning(f"[{correlation_id}] Order timeout for {symbol} — querying order status (ID: {_coid})")
                    time.sleep(3)  # brief wait for exchange to process
                    _order_check = self.exchange_binance.get_order_status(symbol, _coid)
                    _order_state = _order_check.get("status", "UNKNOWN")
                    if _order_state == "FILLED":
                        _avg = _order_check.get("avgPrice", 0)
                        execution_res = {
                            "status": "SUCCESS",
                            "orderId": _order_check.get("orderId"),
                            "avgPrice": _avg,
                            "recovered_from_timeout": True
                        }
                        logger.info(f"[{correlation_id}] Timeout recovery: order FILLED @ ${_avg}")
                    elif _order_state in ("NEW", "PARTIALLY_FILLED"):
                        # Order exists but not fully filled — wait a bit more then re-check once
                        time.sleep(5)
                        _order_check2 = self.exchange_binance.get_order_status(symbol, _coid)
                        if _order_check2.get("status") == "FILLED":
                            execution_res = {
                                "status": "SUCCESS",
                                "orderId": _order_check2.get("orderId"),
                                "avgPrice": _order_check2.get("avgPrice", 0),
                                "recovered_from_timeout": True
                            }
                        else:
                            logger.warning(f"[{correlation_id}] Timeout recovery: order still {_order_check2.get('status')} — treating as FAILED")
                            execution_res = {"status": "FAILED", "reason": "timeout_unconfirmed", "msg": f"Order {_coid} state: {_order_check2.get('status')}"}
                    elif _order_state == "NOT_FOUND":
                        logger.warning(f"[{correlation_id}] Timeout recovery: order NOT_FOUND — trade did not execute")
                        execution_res = {"status": "FAILED", "reason": "timeout_not_executed", "msg": "Order not found after timeout"}
                    else:
                        logger.warning(f"[{correlation_id}] Timeout recovery: unknown state {_order_state} — treating as FAILED")
                        execution_res = {"status": "FAILED", "reason": "timeout_unknown", "msg": f"State: {_order_state}"}

                if execution_res.get("status") == "SUCCESS":
                    # Binance live response uses camelCase avgPrice; paper mode uses snake_case avg_price
                    _raw_fill = float(execution_res.get("avg_price") or execution_res.get("avgPrice") or 0)
                    fill_price = _raw_fill if _raw_fill > 0 else price_signal
                    # Sanity check: if fill_price still matches signal price and deviates >20% from live,
                    # use live price for SL/TP to avoid "would immediately trigger" errors.
                    if fill_price == price_signal:
                        try:
                            _live = self.exchange_binance.get_mainnet_mark_price(symbol)
                            if _live and _live > 0 and abs(fill_price - _live) / _live > 0.20:
                                logger.warning(f"[{correlation_id}] fill_price ${fill_price} deviates >20% from live ${_live} — using live price for SL/TP")
                                fill_price = _live
                        except Exception:
                            pass

            # --- 7. LOGGING & ALERTS ---
            if execution_res.get("status") == "SUCCESS":
                self.idempotency.mark_seen(signal_id)
                try:
                    pos_key = f"{target_exchange}:{symbol}:{strat_name}"
                    _pnl_before = self.ledger.get_position(pos_key).daily_realized_pnl
                    pos_snapshot = self.ledger.apply_fill(pos_key, side, qty, fill_price)
                    _this_trade_pnl = pos_snapshot.daily_realized_pnl - _pnl_before
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
                    # Use SL/TP from signal if Pine script provided them; fallback to env defaults
                    _sig_sl = float(payload_raw.get("sl_pct", 0) or 0)
                    _sig_tp = float(payload_raw.get("tp_pct", 0) or 0)
                    _env_sl = float(os.getenv("STOP_LOSS_PCT", "1.5"))
                    _env_tp = float(os.getenv("TAKE_PROFIT_PCT", "4.5"))
                    sl_pct = _sig_sl if 0 < _sig_sl < 20.0 else _env_sl
                    tp_pct = _sig_tp if 0 < _sig_tp < 50.0 else _env_tp
                    logger.info(f"[{correlation_id}] SL={sl_pct}% TP={tp_pct}% "
                                f"({'signal' if 0 < _sig_sl < 20.0 else 'default'} / "
                                f"{'signal' if 0 < _sig_tp < 50.0 else 'default'})")
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

                # Record win/loss for circuit breaker (use THIS trade's PnL, not cumulative day PnL)
                metrics.set_gauge("bot_daily_pnl_usd", pos_snapshot.daily_realized_pnl)
                if self.circuit_breaker:
                    self.circuit_breaker.record_trade_result(_this_trade_pnl >= 0)

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

                # Calculate SL/TP prices (for Telegram alert display)
                sl_info = ""
                tp_info = ""
                if not is_exit and target_exchange == "binance":
                    _sig_sl_tg = float(payload_raw.get("sl_pct", 0) or 0)
                    _sig_tp_tg = float(payload_raw.get("tp_pct", 0) or 0)
                    sl_pct_val = _sig_sl_tg if 0 < _sig_sl_tg < 20.0 else float(os.getenv("STOP_LOSS_PCT", "1.5"))
                    tp_pct_val = _sig_tp_tg if 0 < _sig_tp_tg < 50.0 else float(os.getenv("TAKE_PROFIT_PCT", "4.5"))
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
                        message=(f"{emoji} <b>Bot Alert: Trade Executed</b>\n\n"
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
                try:
                    self.sheets_logger.log_blocked_trade(
                        symbol=symbol, side=side, strategy=strat_name,
                        reason=f"Execution Failed: {exec_reason}", signal_id=signal_id)
                except Exception as e:
                    logger.debug(f"Sheets log failed: {e}")
                if exec_reason == "permanent":
                    self.idempotency.mark_seen(signal_id)
                    return True
                return False

        except Exception as e:
            logger.error(f"[{correlation_id}] Critical Error in handle_signal: {e}")
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
                                    ep = float(pos.get('entryPrice') or pos.get('entry_price') or 0)
                                    exchange_data[f"binance:{sym}"] = {
                                        'quantity': qty,
                                        'side': 'LONG' if qty > 0 else 'SHORT',
                                        'entry_price': ep if ep > 0 else None,
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
