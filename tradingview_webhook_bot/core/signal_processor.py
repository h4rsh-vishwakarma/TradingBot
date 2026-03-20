import os
import json
from utils.logger import setup_logger

class SignalProcessor:
    def __init__(self, config, client, strategy_name, price_provider=None):
        self.config = config
        self.client = client
        self.strategy_name = strategy_name
        self.price_provider = price_provider
        self.logger = setup_logger(f"signal_processor_{strategy_name}")

    def process_signals(self, queue_file):
        """Process signals from the JSONL queue safely"""
        if not os.path.exists(queue_file):
            return []

        signals = []
        try:
            with open(queue_file, 'r') as f:
                lines = f.readlines()
            
            # Clear the queue after reading (Atomic approach)
            open(queue_file, 'w').close()

            for line in lines:
                if line.strip():
                    signals.append(json.loads(line))
            
            if signals:
                self.logger.info(f"📥 Picked up {len(signals)} signals from queue")
                
        except Exception as e:
            self.logger.error(f"❌ Error processing signals: {e}")
            
        return signals
