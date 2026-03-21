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

    # Map position_size to action: positive = BUY/LONG, negative = SELL/SHORT, 0 = EXIT
    position = int(match.group('position'))
    if position > 0:
        side = "BUY"
    elif position < 0:
        side = "SELL"
    else:
        # Position closed - use the order action
        side = "SELL" if action_raw in ("SELL", "SHORT") else "BUY"

    return {
        "secret": secret,
        "strategy": strategy,
        "symbol": symbol,
        "side": side,
        "quantity": float(quantity),
        "indicator": strategy.replace(' ', '_'),
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
    def __init__(self, config, signals_queue_file):
        self.app = Flask(__name__)
        self.config = config
        self.webhook_secret = config['webhook']['secret'].strip()
        self.queue = AtomicJsonlQueue(signals_queue_file)
        self.telegram = TelegramAlert()

        current_file = Path(__file__).resolve()
        project_root = current_file.parents[1]
        self.ingestor = BacktestIngestor(project_root, self.telegram)

        self.setup_routes()

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

    def setup_routes(self):
        @self.app.route('/webhook/tradingview', methods=['POST'])
        def receive_signal():
            try:
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
                    # === JSON FORMAT (existing flow) ===
                    payload = data.get('payload', data)
                    received_secret = str(data.get('secret', payload.get('secret', ''))).strip()

                    if received_secret == "your_secret_key":
                        return jsonify({'status': 'ignored', 'message': 'Placeholder secret detected'}), 200
                    if received_secret != self.webhook_secret:
                        logger.warning(f"❌ Unauthorized JSON attempt")
                        return jsonify({'status': 'error', 'message': 'Invalid secret'}), 401

                    raw_symbol = str(payload.get('symbol', '')).upper().strip()
                    side = payload.get('side') or payload.get('action') or payload.get('signal')
                    price = payload.get('price')

                    if not all([raw_symbol, side, price]):
                        return jsonify({'status': 'error', 'message': 'Missing symbol, action, or price'}), 400

                    # Clean symbol
                    symbol = raw_symbol.split('_')[0]
                    if symbol and "USDT" not in symbol:
                        symbol = f"{symbol.replace('USD', '')}USDT"

                    # Validate price
                    try:
                        price_val = float(price)
                    except (ValueError, TypeError):
                        return jsonify({'status': 'error', 'message': f'Invalid price: {price}'}), 400

                    if price_val <= 0:
                        logger.warning(f"❌ Rejected: negative price {price_val} for {symbol}")
                        return jsonify({'status': 'rejected', 'message': f'Invalid price: {price_val}'}), 400

                    strategy = payload.get("strategy", "SMC")
                    indicator = payload.get("indicator", "SMC_LuxAlgo")
                    quantity = float(payload.get("quantity") or 0.003)
                    exchange = payload.get("exchange", "binance")

                else:
                    # === PLAIN TEXT FORMAT (TradingView default alerts) ===
                    parsed = parse_plain_text_alert(raw_body)
                    if not parsed:
                        logger.warning(f"❌ Could not parse alert: {raw_body[:200]}")
                        return jsonify({'status': 'error', 'message': 'Unrecognized alert format'}), 400

                    # Verify secret
                    if parsed['secret'] != self.webhook_secret:
                        logger.warning(f"❌ Unauthorized plain text attempt")
                        return jsonify({'status': 'error', 'message': 'Invalid secret'}), 401

                    symbol = parsed['symbol']
                    side = parsed['side']
                    strategy = parsed['strategy']
                    indicator = parsed['indicator']
                    quantity = parsed['quantity']
                    exchange = "binance"

                    # Fetch live price from Binance (plain text alerts don't include price)
                    price_val = self._fetch_live_price(symbol)
                    if price_val <= 0:
                        logger.error(f"❌ Could not fetch live price for {symbol}")
                        return jsonify({'status': 'error', 'message': f'Could not fetch price for {symbol}'}), 500

                    logger.info(f"📊 Live price fetched for {symbol}: ${price_val}")

                # --- COMMON: Build payload, queue, respond ---
                signal_id = f"TV-{int(time.time())}"
                if is_json:
                    signal_id = data.get('signal_id') or signal_id

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
                        "indicator": indicator
                    }
                }

                # Queue signal (fast file write, ~1ms)
                self.queue.enqueue(clean_payload)
                logger.info(f"✅ Signal Queued: {symbol} {side} @ ${price_val} | Strategy: {strategy} (ID: {signal_id})")

                # Return 200 IMMEDIATELY
                response = jsonify({'status': 'success', 'message': 'Signal received and processing'})

                # Fire-and-forget Telegram notification (daemon thread)
                _sym, _side, _price, _sig, _strat = symbol, side, price_val, signal_id, strategy
                def _notify_telegram():
                    try:
                        self.telegram.send(
                            severity=AlertSeverity.INFO,
                            title=f"📥 Signal Received: {_sym}",
                            message=(f"🏹 <b>Action:</b> <code>{str(_side).upper()}</code>\n"
                                     f"💰 <b>Price:</b> <code>${_price:,.2f}</code>\n"
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
    conf = {"webhook": {"secret": "squeeze_tradingview_cluster_2026_secure", "host": "0.0.0.0", "port": 5000}}
    queue_file = "/home/ubuntu/tradingview_webhook_bot/tradingview_webhook_bot/storage/signals.jsonl"
    server = WebhookServer(conf, queue_file)
    server.run()
