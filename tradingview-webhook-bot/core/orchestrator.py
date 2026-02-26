import time
import logging
import os
from pathlib import Path

# Google Sheets Logger import
from tradingview_webhook_bot.storage.sheets_logger import GoogleSheetsLogger
# Absolute imports
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

        # Debugging ke liye token check
        logger.info(f"DEBUG: Telegram Token present: {bool(self.alerts.telegram_token)}")

        # Service Account JSON key path verify karein
        self.sheets_logger = GoogleSheetsLogger(json_key="service_account.json")

        self.consumer = JsonlOffsetConsumer(
            queue_path=self.queue_path,
            offset_path=self.offset_path
        )

    def handle_signal(self, event: dict) -> bool:
        """
        TradingView signals ko process karta hai aur Ledger/Sheets update karta hai.
        """
        try:
            payload = event.get("payload", {})
            symbol = payload.get("symbol")
            side = payload.get("action")
            qty = float(payload.get("quantity", 0))
            price = float(payload.get("price", 0))
            strategy = payload.get("strategy", "N/A")

            if not symbol or not side:
                return True

            logger.info(f"⚡ Executing: {side} {qty} {symbol} @ {price}")

            # 1. Update Ledger
            self.ledger.apply_fill(
                symbol=symbol,
                side=side,
                qty=qty,
                price=price
            )

            # 2. Log to Google Sheets
            self.sheets_logger.log_trade(
                symbol=symbol,
                action=side,
                qty=qty,
                price=price,
                strategy=strategy
            )

            # 3. Send Telegram Alert
            self.alerts.send(f"Executed {side} {qty} {symbol} @ {price}", severity="INFO")
            return True

        except Exception as e:
            logger.error(f"❌ Handle Signal Error: {e}")
            self.alerts.send(f"CRITICAL: Orchestrator error: {str(e)}", severity="CRITICAL")
            return False

    def process_commands(self):
        """
        Telegram se aaye commands (/status, /help) ko process karta hai.
        """
        try:
            commands = self.alerts.get_updates()
            for cmd in commands:
                cmd = cmd.lower().strip()
                if cmd == "/status":
                    # FIX: get_state() ki jagah direct self.ledger.positions check karein
                    pos_data = getattr(self.ledger, 'positions', {})
                    
                    if not pos_data:
                        self.alerts.reply("📂 *Ledger is empty.* No active positions.")
                        continue

                    status_msg = "📊 *Current Positions:*\n"
                    for sym, data in pos_data.items():
                        # Handle both dict and Pydantic object if necessary
                        if hasattr(data, 'dict'):
                            data = data.dict()
                        
                        qty = data.get('quantity', 0)
                        # Multiple price field keys handle karein
                        price = data.get('weighted_avg_entry_price') or data.get('avg_price', 0)
                        status_msg += f"- `{sym}`: {qty} @ ${price}\n"

                    self.alerts.reply(status_msg)

                elif cmd == "/help":
                    help_text = (
                        "🤖 *Available Commands:*\n"
                        "/status - Show active positions\n"
                        "/help - Show this menu"
                    )
                    self.alerts.reply(help_text)
        except Exception as e:
            logger.error(f"❌ Command Processing Error: {e}")

    def run(self):
        """Main Engine Loop"""
        logger.info("🚀 Orchestrator Loop Active with Telegram Polling...")
        while True:
            try:
                # 1. TradingView Signals process karein
                stats = self.consumer.poll(handler=self.handle_signal, batch_size=10)

                if stats.get("processed", 0) > 0:
                    logger.info(f"📊 Engine Stats: {stats}")

                # 2. Telegram Commands check karein
                self.process_commands()

                time.sleep(1)
            except Exception as e:
                logger.error(f"🔄 Loop Error: {e}")
                time.sleep(5)
