from flask import Flask, request, jsonify
import json
import os
import time
import random
from utils.logger import setup_logger
from storage.jsonl_queue import AtomicJsonlQueue

logger = setup_logger('webhook_server')

class WebhookServer:
    def __init__(self, config, signals_queue_file):
        self.app = Flask(__name__)
        self.config = config
        self.webhook_secret = config['webhook']['secret']
        self.queue = AtomicJsonlQueue(signals_queue_file)
        self.setup_routes()

    def setup_routes(self):
        @self.app.route('/webhook/tradingview', methods=['POST'])
        def receive_signal():
            try:
                payload = request.get_json(force=True)
                
                # Check Secret
                if payload.get('secret') != self.webhook_secret:
                    return jsonify({'status': 'error', 'message': 'Invalid secret'}), 401
                
                # Auto-generate signal_id if missing (Fix for the error)
                if 'signal_id' not in payload:
                    payload['signal_id'] = f"sig_{int(time.time())}_{random.randint(1000,9999)}"
                
                # Verify required fields
                required = ['symbol', 'side', 'price', 'timeframe']
                if not all(k in payload for k in required):
                    return jsonify({'status': 'error', 'message': 'Missing fields'}), 400

                # Log and Enqueue
                logger.info(f"📥 Signal Received: {payload['symbol']} {payload['side']} (ID: {payload['signal_id']})")
                self.queue.enqueue(payload)
                
                return jsonify({'status': 'success', 'message': 'Signal enqueued', 'id': payload['signal_id']}), 200
            except Exception as e:
                logger.error(f"❌ Webhook Error: {str(e)}")
                return jsonify({'status': 'error', 'message': str(e)}), 500

    def run(self):
        host = self.config['webhook'].get('host', '0.0.0.0')
        port = self.config['webhook'].get('port', 5000)
        self.app.run(host=host, port=port)
