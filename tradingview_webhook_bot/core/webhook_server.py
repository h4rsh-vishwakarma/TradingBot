from flask import Flask, request, jsonify
import json, os, time, random, csv
from pathlib import Path
from datetime import datetime
from utils.logger import setup_logger
from storage.jsonl_queue import AtomicJsonlQueue

logger = setup_logger('webhook_server')

class BacktestIngestor:
    def __init__(self, project_root):
        # Yahan hum root tak ja rahe hain taaki 'backtesting' folder mil sake
        self.import_dir = Path(project_root).parent / "backtesting" / "A_Leaderboard" / "backtest_imports"
        self.import_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"📁 Backtest Ingestor Active: {self.import_dir}")

    def save_report(self, strategy_name, symbol, data):
        filename = f"{strategy_name}_{symbol}_LIVE_STATS.csv"
        filepath = self.import_dir / filename
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        fieldnames = ["timestamp", "net_profit", "win_rate", "total_trades", "max_drawdown", "profit_factor"]
        
        row = {
            "timestamp": timestamp,
            "net_profit": data.get("net_profit", "0"),
            "win_rate": data.get("win_rate", "0"),
            "total_trades": data.get("total_trades", "0"),
            "max_drawdown": data.get("max_drawdown", "0"),
            "profit_factor": data.get("profit_factor", "0")
        }

        file_exists = os.path.isfile(filepath)
        with open(filepath, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists: writer.writeheader()
            writer.writerow(row)
        return str(filepath)

class WebhookServer:
    def __init__(self, config, signals_queue_file):
        self.app = Flask(__name__)
        self.config = config
        self.webhook_secret = config['webhook']['secret']
        self.queue = AtomicJsonlQueue(signals_queue_file)
        
        # Smart Root Detection
        current_file = Path(__file__).resolve()
        project_root = current_file.parents[1] # tradingview_webhook_bot/tradingview_webhook_bot/
        self.ingestor = BacktestIngestor(project_root)
        
        self.setup_routes()

    def setup_routes(self):
        @self.app.route('/webhook/tradingview', methods=['POST'])
        def receive_signal():
            try:
                payload = request.get_json(force=True)
                if payload.get('secret') != self.webhook_secret:
                    return jsonify({'status': 'error', 'message': 'Invalid secret'}), 401
                
                if 'signal_id' not in payload:
                    payload['signal_id'] = f"sig_{int(time.time())}_{random.randint(1000,9999)}"

                # Field validation for trading
                required = ['symbol', 'side', 'price', 'timeframe']
                if not all(k in payload for k in required):
                    return jsonify({'status': 'error', 'message': 'Missing fields'}), 400

                logger.info(f"📥 Signal Received: {payload['symbol']} {payload['side']}")
                self.queue.enqueue(payload)
                return jsonify({'status': 'success', 'id': payload['signal_id']}), 200
            except Exception as e:
                return jsonify({'status': 'error', 'message': str(e)}), 500

        @self.app.route('/backtest-report', methods=['POST'])
        def handle_backtest_report():
            try:
                data = request.get_json(force=True)
                if data.get("secret") != self.webhook_secret:
                    return jsonify({"status": "error"}), 401

                saved_path = self.ingestor.save_report(
                    data.get("strategy_name", "Unknown"),
                    data.get("symbol", "Unknown"),
                    data.get("data", {})
                )
                logger.info(f"📊 Report Synced: {saved_path}")
                return jsonify({"status": "success", "path": saved_path}), 200
            except Exception as e:
                return jsonify({"status": "error", "message": str(e)}), 500

    def run(self):
        host = self.config['webhook'].get('host', '0.0.0.0')
        port = self.config['webhook'].get('port', 5000)
        self.app.run(host=host, port=port)
