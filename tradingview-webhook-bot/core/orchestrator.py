import time
import logging
import os
from pathlib import Path

# Absolute imports using the injected module name
from tradingview_webhook_bot.storage.jsonl_consumer import JsonlOffsetConsumer
from tradingview_webhook_bot.ledger.positions import PositionLedger
from tradingview_webhook_bot.alerts.router import AlertRouter

logger = logging.getLogger(__name__)

class Orchestrator:
    def __init__(self):
        self.queue_path = os.getenv("QUEUE_PATH", "storage/signals.jsonl")
        self.offset_path = os.getenv("OFFSET_PATH", "storage/signals.offset")
        self.ledger_path = os.getenv("LEDGER_PATH", "storage/ledger_state.json")
        self.alerts_path = os.getenv("ALERTS_LOG", "storage/alerts.jsonl")

        self.ledger = PositionLedger(self.ledger_path)
        self.alerts = AlertRouter(self.alerts_path)
        
        self.consumer = JsonlOffsetConsumer(
            queue_path=self.queue_path,
            offset_path=self.offset_path
        )

    def handle_signal(self, event: dict) -> bool:
        """
        Process logic for a single signal.
        """
        try:
            payload = event.get("payload", {})
            symbol = payload.get("symbol")
            side = payload.get("action") # 'action' (BUY/SELL) side ban jayega
            qty = float(payload.get("quantity", 0))
            price = float(payload.get("price", 0))

            if not symbol or not side:
                return True

            logger.info(f"⚡ Executing: {side} {qty} {symbol} @ {price}")
            
            # --- FIX START ---
            # Grep ke mutabik sahi method 'apply_fill' hai
            self.ledger.apply_fill(
                symbol=symbol, 
                side=side, 
                qty=qty, 
                price=price
            )
            # --- FIX END ---
            
            self.alerts.send(f"✅ Ledger Updated: {side} {symbol}", severity="INFO")
            return True
            
        except Exception as e:
            logger.error(f"❌ Handle Signal Error: {e}")
            self.alerts.send(f"CRITICAL: Orchestrator error: {str(e)}", severity="CRITICAL")
            return False

    def run(self):
        """Main Engine Loop"""
        logger.info("🚀 Orchestrator Loop Active (using poll)...")
        while True:
            try:
                # Consumer's poll method calls handle_signal
                stats = self.consumer.poll(handler=self.handle_signal, batch_size=10)
                
                if stats.get("processed", 0) > 0:
                    logger.info(f"📊 Engine Stats: {stats}")
                
                time.sleep(1)
            except Exception as e:
                logger.error(f"🔄 Loop Error: {e}")
                time.sleep(5)
