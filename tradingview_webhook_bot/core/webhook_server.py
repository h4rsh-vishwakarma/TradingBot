import sys, os, json, time, re, csv, threading
from pathlib import Path
from flask import Flask, request, jsonify
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

# ---------------------------------------------------------------------------
# UNIVERSAL TRADINGVIEW PLAIN-TEXT ALERT PARSER
# Handles every format TradingView can generate:
#
# Format A — custom with secret in body:
#   "Strategy | SYMBOL - Webhook (secret): order buy @ 0.003 filled on TICKER. New strategy position is 1"
#
# Format B — TradingView built-in fill alert (all variations):
#   "Strategy (params): order buy @ price filled on TICKER. New strategy position is X"
#   "Strategy [tag]: order sell @ price filled on TICKER. New strategy position is 0"
#   "Strategy: order buy @ price filled on TICKER. New strategy position is X"
#
# Format C — minimal custom alert text:
#   "BUY SOLUSDT"  /  "SELL ETHUSDT @ 1999"
# ---------------------------------------------------------------------------

# Format A — legacy format with secret embedded in alert body
_PAT_A = re.compile(
    r'^(?P<strategy>.+?)\s*\|\s*\S+\s*-\s*Webhook\s*\((?P<secret>[^)]+)\)\s*:\s*'
    r'order\s+(?P<action>\w+)\s*@\s*(?P<price>[\d.]+)\s*filled\s+on\s+(?P<ticker>\S+)\.'
    r'.*?New\s+strategy\s+position\s+is\s+(?P<position>[+-]?[\d.]+)',
    re.IGNORECASE | re.DOTALL
)

# Format B — TradingView built-in order fill (strategy name may have (params) or [tags])
_PAT_B = re.compile(
    r'^(?P<strategy>[^:]+?)\s*:\s*'
    r'order\s+(?P<action>\w+)\s*@\s*(?P<price>[\d.]+)\s*filled\s+on\s+(?P<ticker>\S+)\.'
    r'.*?New\s+strategy\s+position\s+is\s+(?P<position>[+-]?[\d.]+)',
    re.IGNORECASE | re.DOTALL
)

# Format C — bare "BUY SYMBOL" or "SELL SYMBOL @ price"
_PAT_C = re.compile(
    r'^(?P<action>BUY|SELL|LONG|SHORT)\s+(?P<ticker>[A-Z]{3,10}(?:USDT|USD|BTC|ETH)?)'
    r'(?:\s*@\s*(?P<price>[\d.]+))?',
    re.IGNORECASE
)


def _clean_symbol(ticker_raw):
    """Normalize TradingView ticker to USDT pair."""
    symbol = str(ticker_raw).split(':')[-1].split('.')[0].split('_')[0].upper()
    if symbol and 'USDT' not in symbol:
        symbol = symbol.replace('USD', '') + 'USDT'
    return symbol


def _clean_strategy(raw):
    """Strip trailing (params) / [tags] from strategy name."""
    return re.sub(r'\s*[\(\[][^\)\]]+[\)\]]\s*$', '', raw).strip()


def _position_to_side(position_str, action_raw):
    """Convert TradingView position size to trading side + is_exit flag."""
    try:
        pos = float(position_str)
    except (ValueError, TypeError):
        pos = 0
    if pos > 0:
        return "BUY", False
    elif pos < 0:
        return "SELL", False
    # position == 0 → closing trade; use order action to know which side closes
    return ("SELL" if str(action_raw).upper() in ("SELL", "SHORT") else "BUY"), True


def parse_plain_text_alert(text, url_secret=None):
    """Universal TradingView plain-text alert parser.

    Secret is no longer required for validation — accepted from body or URL param
    but never blocked on. Returns a dict on success, None if completely unparseable.
    """
    text = text.strip()
    secret = url_secret or ""

    # ── Format A: has embedded secret ──────────────────────────────────────
    m = _PAT_A.match(text)
    if m:
        action = m.group('action').upper()
        side, is_exit = _position_to_side(m.group('position'), action)
        return {
            "secret": m.group('secret').strip() or secret,
            "strategy": m.group('strategy').strip(),
            "symbol": _clean_symbol(m.group('ticker')),
            "side": side, "price": float(m.group('price')),
            "quantity": 0.003, "is_exit": is_exit,
            "indicator": m.group('strategy').strip().replace(' ', '_'),
        }

    # ── Format B: built-in TradingView fill alert ───────────────────────────
    m = _PAT_B.match(text)
    if m:
        action = m.group('action').upper()
        side, is_exit = _position_to_side(m.group('position'), action)
        strat = _clean_strategy(m.group('strategy'))
        return {
            "secret": secret,
            "strategy": strat,
            "symbol": _clean_symbol(m.group('ticker')),
            "side": side, "price": float(m.group('price')),
            "quantity": 0.003, "is_exit": is_exit,
            "indicator": strat.replace(' ', '_'),
        }

    # ── Format C: bare "BUY SOLUSDT" or "SELL ETHUSDT @ 1999" ──────────────
    m = _PAT_C.match(text)
    if m:
        action = m.group('action').upper()
        side = "BUY" if action in ("BUY", "LONG") else "SELL"
        price = float(m.group('price')) if m.group('price') else 0.0
        symbol = _clean_symbol(m.group('ticker'))
        return {
            "secret": secret,
            "strategy": "Manual_Alert",
            "symbol": symbol,
            "side": side, "price": price,
            "quantity": 0.003, "is_exit": False,
            "indicator": "Manual_Alert",
        }

    return None  # completely unrecognised format


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
        self.webhook_secret = config['webhook']['secret'].strip()
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

    def setup_routes(self):
        @self.app.route('/webhook/tradingview', methods=['POST'])
        def receive_signal():
            try:
                # Rate limiting
                if self._check_rate_limit():
                    logger.warning("🚫 Rate limit exceeded")
                    return jsonify({'status': 'error', 'message': 'Rate limit exceeded'}), 429

                raw_body = request.get_data(as_text=True).strip()
                logger.info(f"📨 Webhook received: {raw_body[:200]}")

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
                    # === JSON FORMAT ===
                    payload = data.get('payload', data)
                    # Secret field is accepted but NOT validated — any USDT signal is allowed
                    raw_symbol = str(payload.get('symbol', '')).upper().strip()
                    side = payload.get('side') or payload.get('action') or payload.get('signal')
                    price = payload.get('price')

                    if not all([raw_symbol, side]):
                        return jsonify({'status': 'error', 'message': 'Missing symbol or action'}), 400

                    # Clean symbol (remove _PREMIUM, _PERP, etc)
                    symbol = raw_symbol.replace("_PREMIUM", "").replace("_PERP", "").replace("_INDEX", "")
                    symbol = symbol.split('_')[0]
                    if symbol and "USDT" not in symbol:
                        symbol = f"{symbol.replace('USD', '')}USDT"

                    # Price is optional — orchestrator resolves via Binance API if missing/zero
                    try:
                        price_val = float(price) if price is not None else 0.0
                    except (ValueError, TypeError):
                        price_val = 0.0
                    if price_val <= 0:
                        logger.info(f"⚠️ Price missing/zero for {symbol}, orchestrator will resolve via mainnet")

                    strategy = payload.get("strategy", "SMC")
                    indicator = payload.get("indicator", "SMC_LuxAlgo")
                    quantity = float(payload.get("quantity") or 0.003)
                    exchange = payload.get("exchange", "binance")

                else:
                    # === PLAIN TEXT FORMAT (TradingView default alerts) ===
                    # URL secret passed only for logging context — not validated
                    url_secret = request.args.get('secret', '').strip() or None
                    parsed = parse_plain_text_alert(raw_body, url_secret=url_secret)
                    if not parsed:
                        logger.warning(f"❌ Could not parse alert: {raw_body[:200]}")
                        return jsonify({'status': 'ignored', 'message': 'Unrecognized alert format'}), 200
                    # Secret field accepted but NOT validated

                    symbol = parsed['symbol']
                    side = parsed['side']
                    strategy = parsed['strategy']
                    indicator = parsed['indicator']
                    quantity = float(parsed.get('quantity', 0.003))
                    exchange = "binance"

                    # Plain text alerts carry the fill price directly
                    price_val = float(parsed.get('price', 0) or 0)
                    if price_val <= 0:
                        logger.info(f"⚠️ No price in plain text for {symbol}, orchestrator will resolve")

                # --- COMMON: Build payload, queue, respond ---
                signal_id = f"TV-{int(time.time() * 1000)}"
                if is_json:
                    signal_id = data.get('signal_id') or signal_id

                # Detect if this is an exit/close signal (position=0 in plain text)
                is_exit_signal = False
                if not is_json and parsed and parsed.get("is_exit", False):
                    is_exit_signal = True

                clean_payload = {
                    "signal_id": signal_id,
                    "secret": self.webhook_secret,
                    "payload": {
                        "strategy": strategy,
                        "symbol": symbol,
                        "action": str(side).upper(),
                        "price": price_val,
                        "quantity": quantity,
                        "exchange": exchange,
                        "indicator": indicator,
                        "is_exit": is_exit_signal,
                    }
                }

                # Queue signal to both JSONL (legacy) and SQLite (durable)
                self.queue.enqueue(clean_payload)
                self.durable_queue.enqueue(clean_payload)
                logger.info(f"✅ Signal Queued: {symbol} {side} @ ${price_val} | Strategy: {strategy} (ID: {signal_id})")

                # Return 200 IMMEDIATELY
                response = jsonify({'status': 'success', 'message': 'Signal received and processing'})

                # Fire-and-forget Telegram notification (daemon thread)
                _sym, _side, _price, _sig, _strat = symbol, side, price_val, signal_id, strategy
                def _notify_telegram():
                    try:
                        price_display = f"${_price:,.2f}" if _price and _price > 0 else "Resolving..."
                        self.telegram.send(
                            severity=AlertSeverity.INFO,
                            title=f"📥 Signal Received: {_sym}",
                            message=(f"🏹 <b>Action:</b> <code>{str(_side).upper()}</code>\n"
                                     f"💰 <b>Price:</b> <code>{price_display}</code>\n"
                                     f"📋 <b>Strategy:</b> <code>{_strat}</code>\n"
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
