import sys, os, json, time, random, csv, threading
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

    def setup_routes(self):
        @self.app.route('/webhook/tradingview', methods=['POST'])
        def receive_signal():
            try:
                # 1. Parse JSON Data
                data = request.get_json(force=True)
                payload = data.get('payload', data)
                
                # 2. Smart Secret Check (Bypass TradingView placeholders)
                received_secret = str(data.get('secret', payload.get('secret', ''))).strip()
                if received_secret == "your_secret_key":
                    return jsonify({'status': 'ignored', 'message': 'Placeholder secret detected'}), 200

                if received_secret != self.webhook_secret:
                    logger.warning(f"❌ Unauthorized attempt with secret: {received_secret}")
                    return jsonify({'status': 'error', 'message': 'Invalid secret'}), 401

                # 3. Extract Data (Smart Mapping for Orchestrator)
                symbol = payload.get('symbol')
                side = payload.get('side') or payload.get('action') or payload.get('signal')
                price = payload.get('price')

                if not all([symbol, side, price]):
                    return jsonify({'status': 'error', 'message': 'Missing symbol, action, or price'}), 400

                # 4. Background Execution Task
                def process_trade_task():
                    signal_id = data.get('signal_id') or f"TV-{int(time.time())}"
                    
                    # Construct clean payload for Orchestrator
                    clean_payload = {
                        "signal_id": signal_id,
                        "secret": self.webhook_secret,
                        "payload": {
                            "strategy": payload.get("strategy", "SMC"),
                            "symbol": symbol,
                            "action": str(side).upper(),
                            "price": float(price),
                            "quantity": float(payload.get("quantity") or 0.003),
                            "exchange": payload.get("exchange", "binance"),
                            "indicator": payload.get("indicator", "SMC_LuxAlgo")
                        }
                    }
                    
                    # Push to signals.jsonl
                    self.queue.enqueue(clean_payload)
                    logger.info(f"✅ Signal Queued: {symbol} {side} (ID: {signal_id})")

                    # Immediate Receipt Notification via Telegram
                    self.telegram.send(
                        severity=AlertSeverity.INFO,
                        title=f"📥 Signal Received: {symbol}",
                        message=(f"🏹 <b>Action:</b> <code>{str(side).upper()}</code>\n"
                                 f"💰 <b>Price:</b> <code>{price}</code>\n"
                                 f"🆔 <b>ID:</b> <code>{signal_id}</code>\n\n"
                                 f"⏳ <i>Processing via Orchestrator...</i>")
                    )

                # Start the background thread (No Timeout for TV)
                threading.Thread(target=process_trade_task).start()

                return jsonify({'status': 'success', 'message': 'Signal received and processing'}), 200

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
