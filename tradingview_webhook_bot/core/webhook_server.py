import hmac as _hmac
import hashlib
import sys, os, json, time, re, csv, threading
from pathlib import Path
from flask import Flask
from flask import request, jsonify
from tradingview_webhook_bot.core.metrics import metrics
from datetime import datetime

# --- 1. DYNAMIC PATH RESOLUTION (Fixes ModuleNotFoundError) ---
CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2] # ~/tradingview_webhook_bot
PACKAGE_ROOT = CURRENT_FILE.parents[1] # ~/tradingview_webhook_bot/tradingview_webhook_bot

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

# Imports after path fix
from utils.logger import setup_logger
from storage.jsonl_queue import AtomicJsonlQueue
try:
    from storage.signal_queue import DurableSignalQueue
except ImportError:
    from tradingview_webhook_bot.storage.signal_queue import DurableSignalQueue
try:
    from alerts.telegram_alerts import TelegramAlert, AlertSeverity
except ImportError:
    from tradingview_webhook_bot.alerts.telegram_alerts import TelegramAlert, AlertSeverity
try:
    from utils.position_summary import build_position_snapshot, format_positions_for_telegram
except ImportError:
    from tradingview_webhook_bot.utils.position_summary import build_position_snapshot, format_positions_for_telegram

logger = setup_logger('webhook_server')

# --- PLAIN TEXT PARSER FOR TRADINGVIEW DEFAULT ALERTS ---
# Format: "Strategy Name | SYMBOL - Webhook (secret): order buy @ 0.003 filled on EXCHANGE:SYMBOL.P. New strategy position is 1"
PLAIN_TEXT_PATTERN = re.compile(
    r'^(?P<strategy>.+?)\s*\|\s*(?P<symbol_hint>\S+)\s*-\s*Webhook\s*\((?P<secret>[^)]+)\)\s*:\s*'
    r'order\s+(?P<action>\w+)\s*@\s*(?P<quantity>[\d.]+)\s*filled\s+on\s+(?P<ticker>\S+)\.\s*'
    r'New\s+strategy\s+position\s+is\s+(?P<position>[+-]?\d+)',
    re.IGNORECASE
)

# TradingView default order-fill alert (no secret in message):
# "StrategyName (params): order buy @ 12345 filled on SOLUSDT. New strategy position is 1"
# "VWAP_Break [Live Trading]: order buy @ 424 filled on AVAXUSDT. New strategy position is 424"
TV_ORDER_FILL_PATTERN = re.compile(
    r'^(?P<strategy>[^:(]+?)(?:\s*[\(\[].*?[\)\]])?\s*:\s*'
    r'order\s+(?P<action>buy|sell)\s+@\s+(?P<price>[\d.]+)\s+filled\s+on\s+(?P<ticker>\w+)\.'
    r'.*?position\s+is\s+(?P<position>[+-]?[\d.]+)',
    re.IGNORECASE | re.DOTALL
)


def _safe_float(value):
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_truthy(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _normalize_signal_token(value):
    return re.sub(r"[\s\-]+", "_", str(value or "").strip().upper())


def _resolve_trade_signal(signal_value, is_exit_hint=False, position_hint=None):
    token = _normalize_signal_token(signal_value)
    pos_text = str(position_hint or "").strip().lower()
    is_exit = (
        bool(is_exit_hint)
        or token in {"CLOSE", "EXIT", "CLOSE_LONG", "CLOSE_SHORT", "EXIT_LONG", "EXIT_SHORT", "BUY_TO_CLOSE", "SELL_TO_CLOSE"}
        or pos_text in {"0", "0.0", "flat"}
    )

    if token in {"CLOSE_LONG", "EXIT_LONG", "SELL_TO_CLOSE"}:
        action = "SELL"
        is_exit = True
    elif token in {"CLOSE_SHORT", "EXIT_SHORT", "BUY_TO_CLOSE"}:
        action = "BUY"
        is_exit = True
    elif token in {"SELL", "SHORT", "OPEN_SHORT"}:
        action = "SELL"
    else:
        action = "BUY"

    if is_exit:
        trade_label = "Close Long" if action == "SELL" else "Close Short"
    else:
        trade_label = "Open Long" if action == "BUY" else "Open Short"

    return {
        "action": action,
        "is_exit": is_exit,
        "trade_label": trade_label,
    }


def _derive_risk_levels(payload, entry_price, action):
    stop_loss = _safe_float(payload.get("stop_loss") or payload.get("sl") or payload.get("sl_price"))
    take_profit = _safe_float(payload.get("take_profit") or payload.get("tp") or payload.get("tp_price"))
    sl_pct = _safe_float(payload.get("sl_pct") or payload.get("stop_loss_pct"))
    tp_pct = _safe_float(payload.get("tp_pct") or payload.get("take_profit_pct"))

    if entry_price and entry_price > 0:
        if action == "BUY":
            if stop_loss and stop_loss > 0 and stop_loss < entry_price and not (sl_pct and sl_pct > 0):
                sl_pct = abs(entry_price - stop_loss) / entry_price * 100
            if take_profit and take_profit > 0 and take_profit > entry_price and not (tp_pct and tp_pct > 0):
                tp_pct = abs(take_profit - entry_price) / entry_price * 100
        else:
            if stop_loss and stop_loss > entry_price and not (sl_pct and sl_pct > 0):
                sl_pct = abs(stop_loss - entry_price) / entry_price * 100
            if take_profit and 0 < take_profit < entry_price and not (tp_pct and tp_pct > 0):
                tp_pct = abs(entry_price - take_profit) / entry_price * 100

    return {
        "stop_loss": stop_loss or 0.0,
        "take_profit": take_profit or 0.0,
        "sl_pct": sl_pct or 0.0,
        "tp_pct": tp_pct or 0.0,
    }


def parse_tv_order_fill_alert(text, webhook_secret):
    """Parse TradingView default strategy order-fill plain-text alert (no secret field)."""
    text = text.strip()
    m = TV_ORDER_FILL_PATTERN.match(text)
    if not m:
        return None

    strategy   = m.group('strategy').strip().replace(' ', '_')
    action_raw = m.group('action').strip().upper()
    price_str  = m.group('price').strip()
    ticker_raw = m.group('ticker').strip().upper()
    position   = float(m.group('position'))

    # Clean symbol
    symbol = ticker_raw.split(':')[-1].split('.')[0].split('_')[0]
    if 'USDT' not in symbol:
        symbol = f"{symbol.replace('USD', '')}USDT"

    # Determine side from action word
    is_exit = False
    if action_raw == 'BUY':
        side = 'BUY'
    elif action_raw == 'SELL':
        side = 'SELL'
    else:
        side = 'BUY'

    return {
        # Secret is intentionally NOT injected here: plain-text TradingView order-fill
        # alerts do not carry a secret, and strict auth modes must reject them.
        "secret":    None,
        "strategy":  strategy,
        "symbol":    symbol,
        "side":      side,
        "price":     float(price_str),
        "quantity":  0.003,            # Default qty; live price override corrects price
        "indicator": strategy,
        "is_exit":   is_exit,
    }


def parse_plain_text_alert(text):
    """Parse TradingView default plain text alert into structured data."""
    text = text.strip()
    match = PLAIN_TEXT_PATTERN.match(text)
    if not match:
        return None

    strategy = match.group('strategy').strip()
    action_raw = match.group('action').strip().upper()
    quantity = match.group('quantity').strip()
    ticker_raw = match.group('ticker').strip()
    secret = match.group('secret').strip()

    # Clean symbol: "BINANCE:SOLUSDT.P" -> "SOLUSDT", "SOLUSDT_PREMIUM" -> "SOLUSDT"
    symbol = ticker_raw.split(':')[-1]       # Remove exchange prefix
    symbol = symbol.split('.')[0]             # Remove .P suffix
    symbol = symbol.split('_')[0]             # Remove _PREMIUM etc
    symbol = symbol.upper()
    if symbol and "USDT" not in symbol:
        symbol = f"{symbol.replace('USD', '')}USDT"

    # Map position_size to action: positive = BUY/LONG, negative = SELL/SHORT, 0 = EXIT/CLOSE
    position = int(match.group('position'))
    is_exit = False
    if position > 0:
        side = "BUY"
    elif position < 0:
        side = "SELL"
    else:
        # position=0 means flat — this is a CLOSE/EXIT, not a new entry
        # Use the order action to determine which side to close
        is_exit = True
        side = "SELL" if action_raw in ("SELL", "SHORT") else "BUY"

    return {
        "secret": secret,
        "strategy": strategy,
        "symbol": symbol,
        "side": side,
        "quantity": float(quantity),
        "indicator": strategy.replace(' ', '_'),
        "is_exit": is_exit,
    }


class BacktestIngestor:
    def __init__(self, project_root, telegram):
        self.import_dir = Path(project_root).parent / "backtesting" / "A_Leaderboard" / "backtest_imports"
        self.import_dir.mkdir(parents=True, exist_ok=True)
        self.telegram = telegram
        logger.info(f"📁 Backtest Ingestor Active: {self.import_dir}")

    def save_report(self, strategy_name, symbol, data):
        filename = f"{strategy_name}_{symbol}_LIVE_STATS.csv"
        filepath = self.import_dir / filename
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        fieldnames = ["timestamp", "net_profit", "win_rate", "total_trades", "max_drawdown", "profit_factor"]

        row = {
            "timestamp": timestamp,
            "net_profit": str(data.get("net_profit", "0")),
            "win_rate": str(data.get("win_rate", "0")),
            "total_trades": str(data.get("total_trades", "0")),
            "max_drawdown": str(data.get("max_drawdown", "0")),
            "profit_factor": str(data.get("profit_factor", "0"))
        }

        file_exists = os.path.isfile(filepath)
        with open(filepath, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists: writer.writeheader()
            writer.writerow(row)

        self.telegram.send(
            severity=AlertSeverity.INFO,
            title="📊 Strategy Report Synced",
            message=(f"<b>Strategy:</b> <code>{strategy_name}</code>\n"
                     f"<b>Symbol:</b> <code>{symbol}</code>\n"
                     f"<b>Profit:</b> {row['net_profit']}\n"
                     f"<b>MaxDD:</b> {row['max_drawdown']}")
        )
        return str(filepath)

class WebhookServer:
    MAX_PAYLOAD_BYTES = 65536  # 64KB max payload
    RATE_LIMIT_PER_SECOND = 10
    RATE_LIMIT_WINDOW = 1.0  # seconds

    def __init__(self, config, signals_queue_file):
        self.app = Flask(__name__)
        self.config = config
        raw_secret = config['webhook']['secret'].strip()
        # Resolve ${ENV_VAR} references in secret
        import re as _re
        self.webhook_secret = _re.sub(r'\$\{(\w+)\}', lambda m: os.environ.get(m.group(1), m.group(0)), raw_secret)
        self.queue = AtomicJsonlQueue(signals_queue_file)
        # Durable SQLite queue (primary)
        db_path = signals_queue_file.replace('.jsonl', '_queue.db').replace('signals_queue', 'signal_queue')
        if 'signal_queue' not in db_path:
            db_path = os.path.join(os.path.dirname(signals_queue_file), 'signal_queue.db')
        self.durable_queue = DurableSignalQueue(db_path)
        self.telegram = TelegramAlert()
        self.ledger_path = os.path.join(os.path.dirname(signals_queue_file), "ledger_state.json")

        # Rate limiting state
        self._request_times = []

        current_file = Path(__file__).resolve()
        project_root = current_file.parents[1]
        self.ingestor = BacktestIngestor(project_root, self.telegram)

        self.app.config['MAX_CONTENT_LENGTH'] = self.MAX_PAYLOAD_BYTES

        self.setup_health_route()
        self.setup_metrics_route()
        self.setup_kill_switch()
        self.setup_routes()

    def _check_rate_limit(self):
        """Returns True if request should be rejected (rate limited)."""
        now = time.time()
        cutoff = now - self.RATE_LIMIT_WINDOW
        self._request_times = [t for t in self._request_times if t > cutoff]
        if len(self._request_times) >= self.RATE_LIMIT_PER_SECOND:
            return True
        self._request_times.append(now)
        return False

    def _fetch_live_price(self, symbol):
        """Fetch live price from Binance mainnet (fast, cached)."""
        try:
            from exchange.price_provider import get_price_provider
            provider = get_price_provider()
            price = provider.get_current_price(symbol)
            if price and price > 0:
                return price
        except Exception as e:
            logger.warning(f"Price provider failed: {e}")

        # Fallback: direct Binance public API (no auth needed)
        try:
            import requests as req
            resp = req.get(f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol}", timeout=3)
            if resp.status_code == 200:
                return float(resp.json()['price'])
        except Exception as e:
            logger.warning(f"Binance API fallback failed: {e}")

        return 0.0

    def _load_open_position_snapshot(self):
        positions = {}
        try:
            with open(self.ledger_path, encoding="utf-8") as handle:
                state = json.load(handle)
            if isinstance(state, dict):
                positions = state.get("positions", {}) or {}
        except Exception as exc:
            logger.debug(f"Ledger snapshot unavailable for Telegram summary: {exc}")

        price_cache = {}

        def _price_lookup(_exchange, asset):
            if asset not in price_cache:
                live_price = self._fetch_live_price(asset)
                price_cache[asset] = live_price if live_price and live_price > 0 else None
            return price_cache[asset]

        return build_position_snapshot(positions, price_lookup=_price_lookup)


    def setup_health_route(self):
        @self.app.route("/health", methods=["GET"])
        def health_check():
            return {"status": "ok", "service": "webhook", "uptime": "running"}, 200

    def setup_metrics_route(self):
        @self.app.route("/metrics", methods=["GET"])
        def metrics():
            """Prometheus-compatible metrics endpoint."""
            try:
                queue_stats = self.durable_queue.get_stats()
                lines = [
                    "# HELP trading_bot_signals_total Total signals by status",
                    "# TYPE trading_bot_signals_total gauge",
                    f'trading_bot_signals_total{{status="pending"}} {queue_stats.get("pending", 0)}',
                    f'trading_bot_signals_total{{status="completed"}} {queue_stats.get("completed", 0)}',
                    f'trading_bot_signals_total{{status="dlq"}} {queue_stats.get("dlq", 0)}',
                    "# HELP trading_bot_webhook_up Webhook server health",
                    "# TYPE trading_bot_webhook_up gauge",
                    "trading_bot_webhook_up 1",
                ]
                return "\n".join(lines) + "\n", 200, {"Content-Type": "text/plain"}
            except Exception as e:
                return f"# error: {e}\ntrading_bot_webhook_up 0\n", 200, {"Content-Type": "text/plain"}

    def setup_kill_switch(self):
        @self.app.route("/kill", methods=["POST"])
        def kill_switch():
            """Emergency: close all positions and cancel all orders."""
            try:
                data = request.get_json(silent=True) or {}
                secret = data.get("secret", "")
                if secret != self.webhook_secret:
                    return jsonify({"error": "Unauthorized"}), 401

                from tradingview_webhook_bot.exchange.binance_client import BinanceClient
                client = BinanceClient()
                closed = client.close_all_positions()
                lighter_key = os.getenv("LIGHTER_API_PRIVATE_KEY") or os.getenv("LIGHTER_PRIVATE_KEY")
                if lighter_key:
                    try:
                        from tradingview_webhook_bot.exchange.lighter_client import LighterClient
                        lighter = LighterClient()
                        closed.extend(lighter.close_all_positions())
                        lighter.close()
                    except Exception as lighter_error:
                        logger.error(f"Lighter kill switch error: {lighter_error}")
                        closed.append({"exchange": "lighter", "status": "FAILED", "msg": str(lighter_error)})

                msg = f"🚨 KILL SWITCH ACTIVATED\nClosed {len(closed)} positions"
                try:
                    self.telegram.send(severity=AlertSeverity.WARNING, title="KILL SWITCH", message=msg)
                except Exception:
                    pass

                logger.critical(f"🚨 KILL SWITCH: Closed {len(closed)} positions")
                return jsonify({"status": "killed", "closed": closed}), 200
            except Exception as e:
                logger.error(f"Kill switch error: {e}")
                return jsonify({"error": str(e)}), 500

    def _verify_hmac(self, payload_bytes, sig):
        if not sig: return True
        expected = _hmac.new(self.webhook_secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
        return _hmac.compare_digest(expected, sig)

    def setup_routes(self):
        @self.app.route('/webhook/tradingview', methods=['POST'])
        def receive_signal():
            try:
                # Rate limiting
                if self._check_rate_limit():
                    logger.warning("🚫 Rate limit exceeded")
                    return jsonify({'status': 'error', 'message': 'Rate limit exceeded'}), 429

                raw_body = request.get_data(as_text=True).strip()
                hmac_sig = request.headers.get('X-Signature', '')
                auth_mode = os.getenv('TRADINGVIEW_AUTH_MODE', 'secret').strip().lower()
                if auth_mode == 'secret_and_signature' and not hmac_sig:
                    logger.warning('Rejected request: signature required in secret_and_signature mode')
                    return jsonify({'status': 'error', 'message': 'Signature required'}), 401
                if hmac_sig and not self._verify_hmac(raw_body.encode(), hmac_sig):
                    return jsonify({'status': 'error', 'message': 'Invalid signature'}), 401
                metrics.inc("bot_webhook_requests_total")
                logger.info(f"📨 Webhook received: {raw_body[:200]}")

                # --- DETECT FORMAT: JSON or Plain Text ---
                parsed = None
                payload = {}
                is_json = False
                trade_label = "Open Long"
                risk_levels = {"stop_loss": 0.0, "take_profit": 0.0, "sl_pct": 0.0, "tp_pct": 0.0}
                is_exit_signal = False

                # Try JSON first
                try:
                    data = json.loads(raw_body)
                    if isinstance(data, dict):
                        is_json = True
                except (json.JSONDecodeError, ValueError):
                    pass

                if is_json:
                    # === JSON FORMAT (existing flow) ===
                    payload = data.get('payload', data)
                    received_secret = str(data.get('secret', payload.get('secret', ''))).strip()

                    if received_secret in ("your_secret_key", "test", "secret", ""):
                        logger.warning(f'Rejected placeholder secret from {request.remote_addr}')
                        return jsonify({'status': 'error', 'message': 'Placeholder secret rejected'}), 401
                    if received_secret != self.webhook_secret:
                        logger.warning(f"❌ Unauthorized JSON attempt")
                        return jsonify({'status': 'error', 'message': 'Invalid secret'}), 401

                    signal_meta = _resolve_trade_signal(
                        payload.get('side') or payload.get('action') or payload.get('signal'),
                        is_exit_hint=(
                            _is_truthy(payload.get("is_exit"))
                            or _is_truthy(payload.get("close"))
                            or _is_truthy(payload.get("reduce_only"))
                        ),
                        position_hint=payload.get("position_size") or payload.get("position"),
                    )
                    raw_symbol = str(payload.get('symbol') or payload.get('ticker', '')).upper().strip()
                    side = signal_meta["action"]
                    price = payload.get('price') or payload.get('entry_price')
                    is_exit_signal = signal_meta["is_exit"]
                    trade_label = signal_meta["trade_label"]

                    if not all([raw_symbol, price]):
                        return jsonify({'status': 'error', 'message': 'Missing symbol, action, or price'}), 400

                    # Clean symbol (remove _PREMIUM, _PERP, etc)
                    symbol = raw_symbol.replace("_PREMIUM", "").replace("_PERP", "").replace("_INDEX", "")
                    symbol = symbol.split('_')[0]
                    if symbol and "USDT" not in symbol:
                        symbol = f"{symbol.replace('USD', '')}USDT"

                    # Validate price
                    try:
                        price_val = float(price)
                    except (ValueError, TypeError):
                        return jsonify({'status': 'error', 'message': f'Invalid price: {price}'}), 400

                    if price_val <= 0:
                        logger.info(f"⚠️ Price={price_val} for {symbol}, orchestrator will resolve via mainnet")

                    strategy = payload.get("strategy", "SMC")
                    indicator = payload.get("indicator", "SMC_LuxAlgo")
                    quantity = float(payload.get("quantity") or 0.003)
                    exchange = payload.get("exchange", "binance")
                    risk_levels = _derive_risk_levels(payload, price_val, side)

                else:
                    # === PLAIN TEXT FORMAT (TradingView default alerts) ===
                    parsed = parse_plain_text_alert(raw_body)

                    # Fallback: try TradingView built-in order-fill format
                    # e.g. "10_Aggressive_Entry: order buy @ 12345 filled on SOLUSDT..."
                    _is_tv_order_fill = False
                    if not parsed:
                        parsed = parse_tv_order_fill_alert(raw_body, self.webhook_secret)
                        if parsed:
                            _is_tv_order_fill = True
                            logger.info(f"📋 Parsed as TV order-fill alert: {parsed['strategy']} / {parsed['symbol']}")

                    if not parsed:
                        logger.warning(f"❌ Could not parse alert: {raw_body[:200]}")
                        try:
                            self.telegram.send(
                                severity=AlertSeverity.WARNING,
                                title="TradingView Script Error",
                                message=(
                                    "Incoming plain-text alert did not match the bot parser.\n\n"
                                    f"<b>Preview:</b> <code>{raw_body[:180]}</code>"
                                ),
                            )
                        except Exception:
                            pass
                        logger.info(f'Ignoring unrecognized alert format')
                        return jsonify({'status': 'ignored', 'message': 'Unrecognized alert format'}), 200

                    # Verify secret — parsed['secret'] is None for secretless TV order-fill
                    # plain-text alerts; strict auth must reject them outright.
                    parsed_secret = parsed.get('secret')
                    if not parsed_secret or parsed_secret != self.webhook_secret:
                        logger.warning("❌ Unauthorized plain text attempt — secret missing or mismatch")
                        return jsonify({'status': 'error', 'message': 'Invalid secret'}), 401

                    symbol = parsed['symbol']
                    side = parsed['side']
                    strategy = parsed['strategy']
                    indicator = parsed['indicator']
                    quantity = parsed['quantity']
                    exchange = "binance"

                    # Plain text alerts may not include price — orchestrator resolves via mainnet.
                    # TV order-fill format sends TradingView's internal simulation price (not live market price),
                    # so we always discard it and let orchestrator fetch the real mainnet price.
                    if _is_tv_order_fill:
                        price_val = 0.0
                        logger.info(f"⚠️ TV order-fill price discarded for {symbol} — orchestrator will use mainnet price")
                    else:
                        price_val = parsed.get('price', 0)
                        try:
                            price_val = float(price_val) if price_val else 0.0
                        except (ValueError, TypeError):
                            price_val = 0.0
                        if price_val <= 0:
                            logger.info(f"⚠️ No price in plain text for {symbol}, orchestrator will resolve")

                    signal_meta = _resolve_trade_signal(
                        parsed.get("side"),
                        is_exit_hint=parsed.get("is_exit", False),
                        position_hint=parsed.get("position"),
                    )
                    side = signal_meta["action"]
                    is_exit_signal = signal_meta["is_exit"]
                    trade_label = signal_meta["trade_label"]
                    risk_levels = _derive_risk_levels(parsed, price_val, side)

                # --- COMMON: Build payload, queue, respond ---
                signal_id = f"TV-{int(time.time() * 1000)}"
                if is_json:
                    signal_id = data.get('signal_id') or signal_id

                # Extract trailing-stop % when explicitly provided
                sig_ts_pct = float(payload.get("ts_pct", 0) or 0) if is_json else 0.0

                clean_payload = {
                    "signal_id": signal_id,
                    "secret": self.webhook_secret,
                    "raw_body": raw_body,
                    "payload": {
                        "strategy": strategy,
                        "symbol": symbol,
                        "action": side,
                        "price": price_val,
                        "quantity": quantity,
                        "exchange": exchange,
                        "indicator": indicator,
                        "is_exit": is_exit_signal,
                        "sl_pct": risk_levels["sl_pct"],
                        "tp_pct": risk_levels["tp_pct"],
                        "ts_pct": sig_ts_pct,
                        "stop_loss": risk_levels["stop_loss"],
                        "take_profit": risk_levels["take_profit"],
                    }
                }

                                # Strategy alias map (empty — orphaned TV alerts deleted 2026-04-15)
                _STRATEGY_ALIASES = {}
                strategy = _STRATEGY_ALIASES.get(strategy, strategy)

                # --- Strategy allowlist check: skip unapproved/test strategies silently ---
                _manifest_path = Path(__file__).resolve().parents[2] / 'config' / 'approved_strategies.json'
                _approved_names = set()
                try:
                    with open(_manifest_path) as _mf:
                        _manifest_data = json.load(_mf)
                    _approved_names = {a['strategy'] for a in _manifest_data.get('approvals', [])}
                except Exception:
                    pass
                if _approved_names and strategy not in _approved_names:
                    logger.info(
                        f"Signal skipped (not in manifest): strategy={strategy} symbol={symbol} - returning 200 silently"
                    )
                    return jsonify({'status': 'success', 'message': 'Signal acknowledged'}), 200
                # --- End allowlist check ---

                # Queue signal to both JSONL (legacy) and SQLite (durable)
                self.queue.enqueue(clean_payload)
                self.durable_queue.enqueue(clean_payload)
                logger.info(f"✅ Signal Queued: {symbol} {side} @ ${price_val} | Strategy: {strategy} (ID: {signal_id})")

                # Return 200 IMMEDIATELY
                response = jsonify({'status': 'success', 'message': 'Signal received and processing'})

                # Fire-and-forget Telegram notification (daemon thread)
                _sym, _side, _price, _sig, _strat = symbol, side, price_val, signal_id, strategy
                _trade_label = trade_label
                _sl_price = risk_levels["stop_loss"]
                _tp_price = risk_levels["take_profit"]
                _sl_pct = risk_levels["sl_pct"]
                _tp_pct = risk_levels["tp_pct"]
                def _notify_telegram():
                    try:
                        live_p = self._fetch_live_price(_sym)
                        if live_p and live_p > 0:
                            price_display = "Live: ${:,.4f}".format(live_p)
                        elif _price and _price > 0:
                            price_display = "${:,.4f} (stale signal price)".format(_price)
                        else:
                            price_display = "Resolving..."
                        sl_line = ""
                        tp_line = ""
                        if _sl_price and _sl_price > 0:
                            sl_suffix = " ({:.2f}%)".format(_sl_pct) if _sl_pct and _sl_pct > 0 else ""
                            sl_line = f"🛡️ <b>Stop-Loss:</b> <code>${_sl_price:,.4f}</code>{sl_suffix}\n"
                        if _tp_price and _tp_price > 0:
                            tp_suffix = " ({:.2f}%)".format(_tp_pct) if _tp_pct and _tp_pct > 0 else ""
                            tp_line = f"🎯 <b>Take-Profit:</b> <code>${_tp_price:,.4f}</code>{tp_suffix}\n"
                        open_position_info = format_positions_for_telegram(
                            self._load_open_position_snapshot(),
                            limit=3,
                        )
                        self.telegram.send(
                            severity=AlertSeverity.INFO,
                            title=f"📥 Signal Received: {_sym}",
                            message=(f"🏹 <b>Action:</b> <code>{str(_side).upper()}</code>\n"
                                     f"📌 <b>Type:</b> <code>{_trade_label}</code>\n"
                                     f"💰 <b>Price:</b> <code>{price_display}</code>\n"
                                     f"📋 <b>Strategy:</b> <code>{_strat}</code>\n"
                                     f"{sl_line}"
                                     f"{tp_line}"
                                     f"{open_position_info}\n"
                                     f"🆔 <b>ID:</b> <code>{_sig}</code>\n\n"
                                     f"⏳ <i>Processing via Orchestrator...</i>")
                        )
                    except Exception as e:
                        logger.warning(f"Telegram notify failed (non-critical): {e}")

                t = threading.Thread(target=_notify_telegram, daemon=True)
                t.start()

                return response, 200

            except Exception as e:
                logger.error(f"🔥 Webhook Server Error: {str(e)}")
                return jsonify({'status': 'error', 'message': 'Internal Server Error'}), 500

        @self.app.route('/backtest-report', methods=['POST'])
        def handle_backtest_report():
            try:
                data = request.get_json(force=True)
                if str(data.get("secret", "")).strip() != self.webhook_secret:
                    return jsonify({"status": "error", "message": "Unauthorized"}), 401

                threading.Thread(target=lambda: self.ingestor.save_report(
                    data.get("strategy_name", "Unknown"),
                    data.get("symbol", "Unknown"),
                    data.get("data", {})
                )).start()

                return jsonify({"status": "success"}), 200
            except Exception as e:
                logger.error(f"🔥 Backtest Route Error: {str(e)}")
                return jsonify({"status": "error", "message": str(e)}), 500

    def run(self):
        host = self.config['webhook'].get('host', '0.0.0.0')
        port = self.config['webhook'].get('port', 5000)
        logger.info(f"🚀 Webhook Server starting on {host}:{port}")
        self.app.run(host=host, port=port, debug=False)

if __name__ == "__main__":
    # Mock config if run standalone
    conf = {"webhook": {"secret": os.getenv("WEBHOOK_SECRET", ""), "host": "0.0.0.0", "port": 5000}}
    queue_file = "/home/ubuntu/tradingview_webhook_bot/tradingview_webhook_bot/storage/signals.jsonl"
    server = WebhookServer(conf, queue_file)
    server.run()
