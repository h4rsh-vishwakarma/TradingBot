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

# TradingView simple key=value format (sent by some Pine script alert templates):
# "action=close symbol=UNIUSDT.P size=3579.3"
# "action=buy symbol=SOLUSDT size=10"
TV_KV_PATTERN = re.compile(
    r'^action=(?P<action>\w+)\s+symbol=(?P<symbol>[A-Z0-9]+)(?:\.P|\.PERP|\.\w+)?'
    r'(?:\s+size=(?P<size>[\d.]+))?',
    re.IGNORECASE
)

INVALID_SECRET_VALUES = {"your_secret_key", "test", "secret"}


def parse_tv_kv_alert(text):
    """Parse TradingView simple key=value alert, optionally with secret=..."""
    parts = dict((k.lower(), v.strip()) for k, v in re.findall(r'(\w+)=([^\s]+)', text.strip()))
    if "action" not in parts or "symbol" not in parts:
        return None
    action_raw = parts.get("action", "").strip().upper()
    symbol_raw = parts.get("symbol", "").strip().upper()
    symbol_raw = symbol_raw.split('.')[0]
    size_raw = parts.get("size") or parts.get("quantity") or '0'
    secret = parts.get("secret", "").strip()

    # Normalise symbol
    if 'USDT' not in symbol_raw:
        symbol_raw = symbol_raw + 'USDT'

    is_exit = action_raw in ('CLOSE', 'EXIT') or float(size_raw) == 0
    if action_raw == 'BUY':
        side = 'BUY'
    else:
        side = 'SELL'

    return {
        "secret": secret,
        "strategy":  action_raw,
        "symbol":    symbol_raw,
        "side":      side,
        "quantity":  0.003,
        "indicator": "TradingView_KV",
        "is_exit":   is_exit,
        "price":     0.0,
    }



def parse_tv_order_fill_alert(text):
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

    # position=0 means strategy is flat â€” this is a CLOSE signal
    is_exit = (position == 0)

    # Determine side from action word
    if action_raw == 'BUY':
        side = 'BUY'
    elif action_raw == 'SELL':
        side = 'SELL'
    else:
        side = 'BUY'

    # Discard price if it equals the position size (common TV bug: position value injected as price)
    parsed_price = float(price_str)
    if abs(parsed_price - position) < 1.0 or parsed_price > 100_000:
        parsed_price = 0.0  # orchestrator will resolve via mainnet

    return {
        "strategy":  strategy,
        "symbol":    symbol,
        "side":      side,
        "price":     parsed_price,
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
        # position=0 means flat â€” this is a CLOSE/EXIT, not a new entry
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
        logger.info(f"?? Backtest Ingestor Active: {self.import_dir}")

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
            title="?? Strategy Report Synced",
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
        self.auth_mode = str(
            config.get("webhook", {}).get("auth_mode") or os.getenv("TRADINGVIEW_AUTH_MODE", "secret")
        ).strip().lower()
        if self.auth_mode not in {"secret", "signature", "secret_and_signature"}:
            logger.warning(f"Invalid TRADINGVIEW auth mode '{self.auth_mode}', defaulting to 'secret'")
            self.auth_mode = "secret"
        self.queue = AtomicJsonlQueue(signals_queue_file)
        # Durable SQLite queue (primary)
        db_path = signals_queue_file.replace('.jsonl', '_queue.db').replace('signals_queue', 'signal_queue')
        if 'signal_queue' not in db_path:
            db_path = os.path.join(os.path.dirname(signals_queue_file), 'signal_queue.db')
        self.durable_queue = DurableSignalQueue(db_path)
        self.telegram = TelegramAlert()

        # Rate limiting state
        self._request_times = []

        current_file = Path(__file__).resolve()
        project_root = current_file.parents[1]
        self.ingestor = BacktestIngestor(project_root, self.telegram)

        self.app.config['MAX_CONTENT_LENGTH'] = self.MAX_PAYLOAD_BYTES

        self.setup_health_route()
        self.setup_metrics_route()
        self.setup_kill_switch()
        self.setup_bot_control()
        self.setup_routes()

    def _validate_tradingview_secret(self, secret, source):
        configured_secret = str(self.webhook_secret or "").strip()
        received_secret = str(secret or "").strip()

        if not configured_secret:
            logger.error(f"TradingView secret enforcement enabled but webhook secret is not configured for {source}")
            return jsonify({'status': 'error', 'message': 'Webhook secret not configured'}), 503
        if not received_secret:
            logger.warning(f"Unauthorized {source} attempt - missing secret")
            return jsonify({'status': 'error', 'message': 'Missing secret'}), 401
        if received_secret in INVALID_SECRET_VALUES:
            logger.warning(f"Unauthorized {source} attempt - placeholder secret provided")
            return jsonify({'status': 'error', 'message': 'Invalid secret'}), 401
        if received_secret != configured_secret:
            logger.warning(f"Unauthorized {source} attempt - wrong secret provided")
            return jsonify({'status': 'error', 'message': 'Invalid secret'}), 401

        return None

    def _authorize_tradingview_request(self, payload_bytes: bytes, secret, signature, source):
        if self.auth_mode in {"signature", "secret_and_signature"}:
            if not signature:
                logger.warning(f"Unauthorized {source} attempt - missing signature")
                return jsonify({'status': 'error', 'message': 'Missing signature'}), 401
            if not self._verify_hmac(payload_bytes, signature):
                logger.warning(f"Unauthorized {source} attempt - invalid signature")
                return jsonify({'status': 'error', 'message': 'Invalid signature'}), 401

        if self.auth_mode in {"secret", "secret_and_signature"}:
            return self._validate_tradingview_secret(secret, source)

        return None

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

                msg = f"?? KILL SWITCH ACTIVATED\nClosed {len(closed)} positions"
                try:
                    self.telegram.send(severity=AlertSeverity.WARNING, title="KILL SWITCH", message=msg)
                except Exception:
                    pass

                logger.critical(f"?? KILL SWITCH: Closed {len(closed)} positions")
                return jsonify({"status": "killed", "closed": closed}), 200
            except Exception as e:
                logger.error(f"Kill switch error: {e}")
                return jsonify({"error": str(e)}), 500

    def setup_bot_control(self):
        """Bot start/stop control endpoints for dashboard."""

        def _auth(data):
            secret = (data or {}).get("secret", "")
            return not secret or secret == self.webhook_secret

        @self.app.route("/bot/status", methods=["GET"])
        def bot_status():
            import subprocess
            try:
                r = subprocess.run(["/usr/bin/sudo", "systemctl", "is-active", "trading_orchestrator"],
                                   capture_output=True, text=True, timeout=5)
                active = r.stdout.strip() == "active"
                allow_trades = os.getenv("ALLOW_REAL_TRADES", "false").lower() == "true"
                return jsonify({"orchestrator": "running" if active else "stopped",
                                "allow_real_trades": allow_trades}), 200
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @self.app.route("/bot/stop", methods=["POST"])
        def bot_stop():
            data = request.get_json(silent=True) or {}
            if not _auth(data):
                return jsonify({"error": "Unauthorized"}), 401
            import subprocess
            try:
                subprocess.run(["/usr/bin/sudo", "systemctl", "stop", "trading_orchestrator"],
                               capture_output=True, text=True, timeout=10)
                msg = "?? Bot STOPPED via dashboard Kill Switch"
                try:
                    self.telegram.send(severity=AlertSeverity.WARNING, title="Bot Stopped", message=msg)
                except Exception:
                    pass
                logger.warning("Bot STOPPED via /bot/stop endpoint")
                return jsonify({"status": "stopped"}), 200
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @self.app.route("/bot/start", methods=["POST"])
        def bot_start():
            data = request.get_json(silent=True) or {}
            if not _auth(data):
                return jsonify({"error": "Unauthorized"}), 401
            import subprocess
            try:
                subprocess.run(["/usr/bin/sudo", "systemctl", "start", "trading_orchestrator"],
                               capture_output=True, text=True, timeout=10)
                msg = "? Bot STARTED via dashboard Kill Switch"
                try:
                    self.telegram.send(severity=AlertSeverity.INFO, title="Bot Started", message=msg)
                except Exception:
                    pass
                logger.info("Bot STARTED via /bot/start endpoint")
                return jsonify({"status": "started"}), 200
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @self.app.route("/bot/emergency", methods=["POST"])
        def bot_emergency():
            """Emergency: close ALL positions AND stop the bot."""
            data = request.get_json(silent=True) or {}
            if not _auth(data):
                return jsonify({"error": "Unauthorized"}), 401
            import subprocess
            closed_count = 0
            try:
                from tradingview_webhook_bot.exchange.binance_client import BinanceClient
                client = BinanceClient()
                closed = client.close_all_positions()
                closed_count = len(closed) if closed else 0
            except Exception as e:
                logger.error(f"Emergency close error: {e}")
            try:
                subprocess.run(["/usr/bin/sudo", "systemctl", "stop", "trading_orchestrator"],
                               capture_output=True, text=True, timeout=10)
            except Exception as e:
                logger.error(f"Emergency stop error: {e}")
            msg = f"?? EMERGENCY KILL: Closed {closed_count} positions + Bot STOPPED"
            try:
                self.telegram.send(severity=AlertSeverity.WARNING, title="EMERGENCY KILL", message=msg)
            except Exception:
                pass
            logger.critical(msg)
            return jsonify({"status": "emergency_killed", "positions_closed": closed_count}), 200

    def _verify_hmac(self, payload_bytes, sig):
        expected = _hmac.new(self.webhook_secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
        return _hmac.compare_digest(expected, sig)

    def setup_routes(self):
        @self.app.route('/webhook/tradingview', methods=['POST'])
        def receive_signal():
            try:
                # Rate limiting
                if self._check_rate_limit():
                    logger.warning("?? Rate limit exceeded")
                    return jsonify({'status': 'error', 'message': 'Rate limit exceeded'}), 429

                raw_body = request.get_data(as_text=True).strip()
                raw_body_bytes = raw_body.encode()
                hmac_sig = request.headers.get('X-Signature', '')
                metrics.inc("bot_webhook_requests_total")
                logger.info(f"?? Webhook received: {raw_body[:200]}")

                # --- DETECT FORMAT: JSON or Plain Text ---
                parsed = None
                is_json = False

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
                    auth_error = self._authorize_tradingview_request(raw_body_bytes, received_secret, hmac_sig, "JSON")
                    if auth_error:
                        return auth_error

                    raw_symbol = str(payload.get('symbol', '')).upper().strip()
                    side = payload.get('side') or payload.get('action') or payload.get('signal')
                    price = payload.get('price')

                    if not raw_symbol or not side or price is None:
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
                        logger.info(f"?? Price={price_val} for {symbol}, orchestrator will resolve via mainnet")

                    strategy = payload.get("strategy", "SMC")
                    indicator = payload.get("indicator", "SMC_LuxAlgo")
                    quantity = float(payload.get("quantity") or 0.003)
                    exchange = payload.get("exchange", "binance")

                else:
                    # === PLAIN TEXT FORMAT (TradingView default alerts) ===
                    parsed = parse_plain_text_alert(raw_body)

                    # Fallback: try TradingView built-in order-fill format
                    # e.g. "10_Aggressive_Entry: order buy @ 12345 filled on SOLUSDT..."
                    plain_text_source = "plain text"
                    _is_tv_order_fill = False
                    if not parsed:
                        parsed = parse_tv_order_fill_alert(raw_body)
                        if parsed:
                            plain_text_source = "TradingView order-fill plain text"
                            _is_tv_order_fill = True
                            logger.info(f"?? Parsed as TV order-fill alert: {parsed['strategy']} / {parsed['symbol']}")

                    # Fallback 2: simple key=value format (action=X symbol=Y size=Z)
                    if not parsed:
                        parsed = parse_tv_kv_alert(raw_body)
                        if parsed:
                            plain_text_source = "TradingView key-value plain text"
                            logger.info(f"?? Parsed as TV key-value alert: {parsed['strategy']} / {parsed['symbol']} is_exit={parsed['is_exit']}")

                    if not parsed:
                        logger.warning(f"? Could not parse alert: {raw_body[:200]}")
                        logger.info(f'Ignoring unrecognized alert format')
                        return jsonify({'status': 'ignored', 'message': 'Unrecognized alert format'}), 200

                    received_secret = str(parsed.get('secret', '')).strip()
                    auth_error = self._authorize_tradingview_request(raw_body_bytes, received_secret, hmac_sig, plain_text_source)
                    if auth_error:
                        return auth_error

                    symbol = parsed['symbol']
                    side = parsed['side']
                    strategy = parsed['strategy']
                    indicator = parsed['indicator']
                    quantity = parsed['quantity']
                    exchange = "binance"

                    # Plain text alerts may not include price â€” orchestrator resolves via mainnet.
                    # TV order-fill format sends TradingView's internal simulation price (not live market price),
                    # so we always discard it and let orchestrator fetch the real mainnet price.
                    if _is_tv_order_fill:
                        price_val = 0.0
                        logger.info(f"?? TV order-fill price discarded for {symbol} â€” orchestrator will use mainnet price")
                    else:
                        price_val = parsed.get('price', 0)
                        try:
                            price_val = float(price_val) if price_val else 0.0
                        except (ValueError, TypeError):
                            price_val = 0.0
                        if price_val <= 0:
                            logger.info(f"?? No price in plain text for {symbol}, orchestrator will resolve")

                # --- COMMON: Build payload, queue, respond ---
                signal_id = f"TV-{int(time.time() * 1000)}"
                if is_json:
                    signal_id = data.get('signal_id') or signal_id

                # Detect if this is an exit/close signal (position=0 in plain text)
                is_exit_signal = False
                if not is_json and parsed and parsed.get("is_exit", False):
                    is_exit_signal = True

                # Extract SL/TP/TS from signal if provided by Pine script
                sig_sl_pct = float(payload.get("sl_pct", 0) or 0) if is_json else 0.0
                sig_tp_pct = float(payload.get("tp_pct", 0) or 0) if is_json else 0.0
                sig_ts_pct = float(payload.get("ts_pct", 0) or 0) if is_json else 0.0

                clean_payload = {
                    "signal_id": signal_id,
                    "secret": received_secret,
                    "payload": {
                        "strategy": strategy,
                        "symbol": symbol,
                        "action": str(side).upper(),
                        "price": price_val,
                        "quantity": quantity,
                        "exchange": exchange,
                        "indicator": indicator,
                        "is_exit": is_exit_signal,
                        "sl_pct": sig_sl_pct,
                        "tp_pct": sig_tp_pct,
                        "ts_pct": sig_ts_pct,
                    }
                }

                # Queue signal to both JSONL (legacy) and SQLite (durable)
                self.queue.enqueue(clean_payload)
                self.durable_queue.enqueue(clean_payload)
                logger.info(f"? Signal Queued: {symbol} {side} @ ${price_val} | Strategy: {strategy} (ID: {signal_id})")

                # Return 200 IMMEDIATELY
                response = jsonify({'status': 'success', 'message': 'Signal received and processing'})

                # Fire-and-forget Telegram notification (daemon thread)
                _sym, _side, _price, _sig, _strat = symbol, side, price_val, signal_id, strategy
                def _notify_telegram():
                    try:
                        live_p = self._fetch_live_price(_sym)
                        if live_p and live_p > 0:
                            price_display = "Live: ${:,.4f}".format(live_p)
                        elif _price and _price > 0:
                            price_display = "${:,.4f} (stale signal price)".format(_price)
                        else:
                            price_display = "Resolving..."
                        self.telegram.send(
                            severity=AlertSeverity.INFO,
                            title=f"?? Signal Received: {_sym}",
                            message=(f"?? <b>Action:</b> <code>{str(_side).upper()}</code>\n"
                                     f"?? <b>Price:</b> <code>{price_display}</code>\n"
                                     f"?? <b>Strategy:</b> <code>{_strat}</code>\n"
                                     f"?? <b>ID:</b> <code>{_sig}</code>\n\n"
                                     f"? <i>Processing via Orchestrator...</i>")
                        )
                    except Exception as e:
                        logger.warning(f"Telegram notify failed (non-critical): {e}")

                t = threading.Thread(target=_notify_telegram, daemon=True)
                t.start()

                return response, 200

            except Exception as e:
                logger.error(f"?? Webhook Server Error: {str(e)}")
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
                logger.error(f"?? Backtest Route Error: {str(e)}")
                return jsonify({"status": "error", "message": str(e)}), 500

    def run(self):
        host = self.config['webhook'].get('host', '0.0.0.0')
        port = self.config['webhook'].get('port', 5000)
        logger.info(f"?? Webhook Server starting on {host}:{port}")
        self.app.run(host=host, port=port, debug=False)

if __name__ == "__main__":
    # Mock config if run standalone
    conf = {"webhook": {"secret": os.getenv("WEBHOOK_SECRET", ""), "host": "0.0.0.0", "port": 5000}}
    queue_file = "/home/ubuntu/tradingview_webhook_bot/tradingview_webhook_bot/storage/signals.jsonl"
    server = WebhookServer(conf, queue_file)
    server.run()
