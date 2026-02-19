from flask import Flask, request, jsonify, Response
from datetime import datetime
import json
import os
from utils.logger import setup_logger
from storage.jsonl_queue import AtomicJsonlQueue
from utils.event_logger import get_event_logger
from utils.health_checker import get_health_checker

logger = setup_logger('webhook_server')

class WebhookServer:
    """Flask server to receive TradingView webhook signals"""
    
    def __init__(self, config, signals_queue_file):
        self.app = Flask(__name__)
        self.config = config
        self.signals_queue_file = signals_queue_file
        self.webhook_secret = config['webhook']['secret']
        
        # Initialize atomic queue writer
        self.queue = AtomicJsonlQueue(signals_queue_file)
        
        # Initialize event logger
        self.event_logger = get_event_logger()
        
        # Initialize health checker
        strategy_name = config.get('strategy', {}).get('name', 'unknown')
        self.health_checker = get_health_checker(strategy_name)
        
        # Update webhook_server component health
        self.health_checker.update_component_health(
            component='webhook_server',
            status='healthy',
            message=f'Webhook server initialized on port {config["webhook"]["port"]}',
            details={'port': config['webhook']['port'], 'queue_file': signals_queue_file}
        )
        
        # Setup routes
        self.setup_routes()
        
        logger.info(f"🌐 Webhook server initialized on port {config['webhook']['port']}")
        logger.info(f"📝 Using atomic queue writer for crash-safe appends")
    
    def setup_routes(self):
        """Setup Flask routes"""
        
        @self.app.route('/webhook/tradingview', methods=['POST'])
        def receive_signal():
            try:
                # Get JSON payload
                payload = request.get_json(force=True)
                
                # Validate secret
                if payload.get('secret') != self.webhook_secret:
                    logger.warning(f"⚠️ Invalid webhook secret from {request.remote_addr}")
                    return jsonify({'error': 'Invalid secret'}), 401
                
                # Validate required fields
                required = ['strategy', 'side', 'symbol', 'price', 'timeframe']
                missing = [f for f in required if f not in payload]
                if missing:
                    logger.warning(f"⚠️ Missing fields: {missing}")
                    return jsonify({'error': f'Missing fields: {missing}'}), 400
                
                # Generate signal ID
                signal_id = self.generate_signal_id(payload)
                
                # Create signal record
                signal = {
                    'signal_id': signal_id,
                    'strategy': payload['strategy'],
                    'side': payload['side'],
                    'symbol': payload['symbol'],
                    'price': str(payload['price']),
                    'timeframe': payload['timeframe'],
                    'stop_loss': str(payload.get('stop_loss', 0)),
                    'take_profit': str(payload.get('take_profit', 0)),
                    'timestamp': datetime.utcnow().isoformat() + 'Z',
                    'processed': False
                }
                
                # Write to queue
                self.write_to_queue(signal)
                
                # Increment signals received counter
                self.health_checker.increment_signals_received()
                
                # Log event
                self.event_logger.log_signal_received(
                    signal_id=signal_id,
                    strategy=payload['strategy'],
                    side=payload['side'],
                    symbol=payload['symbol'],
                    metadata={
                        'price': payload['price'],
                        'timeframe': payload['timeframe'],
                        'stop_loss': payload.get('stop_loss'),
                        'take_profit': payload.get('take_profit')
                    }
                )
                
                logger.info(f"✅ Signal received: {signal_id} | {payload['strategy']} | {payload['side']} | {payload['symbol']}")
                
                return jsonify({
                    'signal_id': signal_id,
                    'status': 'queued',
                    'timestamp': signal['timestamp']
                }), 200
                
            except Exception as e:
                logger.error(f"❌ Webhook error: {e}")
                return jsonify({'error': 'Internal server error'}), 500
        
        @self.app.route('/health', methods=['GET'])
        def health():
            """Enhanced health check with component status and trading metrics"""
            try:
                health_status = self.health_checker.get_health_status()
                
                # Add queue metrics
                queue_size = self.queue.size_bytes()
                queue_lines = self.queue.count_lines()
                
                # Read last signal timestamp if available
                last_signal_ts = None
                try:
                    records = self.queue.read_all()
                    if records:
                        last_signal_ts = records[-1].get('timestamp')
                except:
                    pass
                
                health_status['queue'] = {
                    'path': self.signals_queue_file,
                    'size_bytes': queue_size,
                    'total_signals': queue_lines,
                    'last_signal_ts': last_signal_ts
                }
                
                # Determine HTTP status based on overall health
                http_status = 200
                if health_status.get('status') == 'unhealthy':
                    http_status = 503
                elif health_status.get('status') == 'degraded':
                    http_status = 200  # Still return 200 for degraded (service is up)
                
                return jsonify(health_status), http_status
            except Exception as e:
                return jsonify({
                    'status': 'unhealthy',
                    'error': str(e),
                    'timestamp': datetime.utcnow().isoformat()
                }), 503
        
        @self.app.route('/metrics', methods=['GET'])
        def metrics():
            """Prometheus-compatible metrics endpoint"""
            try:
                metrics_text = self.health_checker.get_prometheus_metrics()
                return Response(metrics_text, mimetype='text/plain')
            except Exception as e:
                logger.error(f"❌ Error generating metrics: {e}")
                return Response(f"# Error generating metrics: {e}\n", mimetype='text/plain'), 500
        
        @self.app.route('/stats', methods=['GET'])
        def stats():
            try:
                total_signals = self.count_signals()
                return jsonify({
                    'total_signals': total_signals,
                    'queue_file': self.signals_queue_file,
                    'timestamp': datetime.utcnow().isoformat()
                }), 200
            except Exception as e:
                return jsonify({'error': str(e)}), 500
    
    def generate_signal_id(self, payload):
        """Generate unique signal ID"""
        timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
        strategy = payload['strategy'][:10]
        import random
        import string
        suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
        return f"TV-{timestamp}-{strategy}-{suffix}"
    
    def write_to_queue(self, signal):
        """Write signal to JSONL queue file using atomic writer"""
        try:
            success = self.queue.append(signal)
            if not success:
                raise Exception("Atomic append failed")
        except Exception as e:
            logger.error(f"Failed to write signal to queue: {e}")
            raise
    
    def count_signals(self):
        """Count total signals in queue"""
        try:
            if not os.path.exists(self.signals_queue_file):
                return 0
            with open(self.signals_queue_file, 'r') as f:
                return sum(1 for _ in f)
        except Exception:
            return 0
    
    def run(self):
        """Run Flask server"""
        host = self.config['webhook']['host']
        port = self.config['webhook']['port']
        logger.info(f"🚀 Starting webhook server on {host}:{port}")
        self.app.run(host=host, port=port, threaded=True)
