import sys
import os
import time
import logging
from pathlib import Path
from dotenv import load_dotenv

# --- PATH FIX START ---
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    import tradingview_webhook_bot
except ImportError:
    import importlib.util
    folder_path = ROOT_DIR / "tradingview-webhook-bot"
    if folder_path.exists():
        spec = importlib.util.spec_from_file_location(
            "tradingview_webhook_bot",
            str(folder_path / "__init__.py")
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["tradingview_webhook_bot"] = module
        spec.loader.exec_module(module)
# --- PATH FIX END ---

# Modules Import
from tradingview_webhook_bot.storage.jsonl_consumer import JsonlOffsetConsumer
from tradingview_webhook_bot.storage.idempotency_store import IdempotencyStore
from tradingview_webhook_bot.ledger.positions import PositionLedger
from tradingview_webhook_bot.recon.reconciler import Reconciler
from tradingview_webhook_bot.alerts.router import AlertRouter
from exchange.binance_client import BinanceClient

load_dotenv()
logger = logging.getLogger(__name__)

class TradingBotOrchestrator:
    def __init__(self, config: dict):
        self.config = config
        
        # 1. Initialize Storage & Audit Components
        self.consumer = JsonlOffsetConsumer(
            queue_path=config['QUEUE_PATH'],
            offset_path=config['OFFSET_PATH'],
            dlq_path=config['DLQ_PATH']
        )
        self.idempotency = IdempotencyStore(config['IDEMPOTENCY_DB_PATH'])
        self.ledger = PositionLedger()
        self.recon = Reconciler(tolerance=config.get('RECON_TOLERANCE', 0.0001))
        self.alerts = AlertRouter(config['ALERTS_LOG_PATH'])
        
        # 2. Initialize Exchange Client
        self.exchange = BinanceClient(testnet=config.get('USE_TESTNET', True))
        
        # 3. State Management
        self.running = True
        self.last_recon_time = 0
        self.recon_interval = config.get('RECON_INTERVAL_SEC', 900)  # Default 15 mins

    def handle_telegram_commands(self):
        """Polls Telegram for new commands and executes them."""
        commands = self.alerts.get_updates()
        
        for cmd in commands:
            cmd_clean = cmd.strip().lower()
            logger.info(f"📥 Received Telegram Command: {cmd_clean}")

            if cmd_clean == "/status":
                try:
                    balance = self.exchange.get_balance()
                    positions = self.exchange.get_positions()
                    response = (
                        f"📊 *Bot Status Report*\n"
                        f"💰 Balance: `{balance} USDT`\n"
                        f"📂 Active Positions: `{len(positions)}`\n"
                        f"🕒 Time: {time.ctime()}"
                    )
                    self.alerts.reply(response)
                except Exception as e:
                    self.alerts.reply(f"❌ Error fetching status: {str(e)}")

            elif cmd_clean == "/balance":
                try:
                    balance = self.exchange.get_balance()
                    self.alerts.reply(f"💰 Current Balance: *{balance} USDT*")
                except Exception as e:
                    self.alerts.reply(f"❌ Error fetching balance: {str(e)}")

            elif cmd_clean == "/stop":
                self.alerts.reply("🛑 *Emergency Stop Triggered!* Shutting down engine...")
                self.running = False

    def run_recon_cycle(self):
        """
        Audits the local ledger against actual Binance positions to detect drift.
        """
        current_time = time.time()
        if current_time - self.last_recon_time < self.recon_interval:
            return

        logger.info("🔍 Running Scheduled Reconciliation Audit...")
        try:
            # Fetch data from both sources
            ledger_positions = self.ledger.get_all_positions()
            exchange_positions = self.exchange.get_positions()
            
            # Identify discrepancies
            incidents = self.recon.reconcile_portfolio(ledger_positions, exchange_positions)
            
            if incidents:
                for report in incidents:
                    symbol = report.get("symbol", "UNKNOWN")
                    alert_msg = self.recon.format_incident(symbol, report)
                    self.alerts.send(alert_msg, severity="CRITICAL")
            else:
                logger.info("✅ Reconciliation Check: All systems synced.")
            
            self.last_recon_time = current_time
            
        except Exception as e:
            logger.error(f"Reconciliation Error: {e}")

    def process_signal(self, signal_record: dict) -> bool:
        """Processes signals with automatic Risk Management (SL/TP)."""
        signal_id = signal_record.get('signal_id')
        payload = signal_record.get('payload', {})
        symbol = payload.get('symbol')
        side = payload.get('action', '').upper()
        qty = payload.get('quantity')

        sl_percent = payload.get('sl_percent', self.config.get('DEFAULT_SL_PERCENT', 2.0))
        tp_percent = payload.get('tp_percent', self.config.get('DEFAULT_TP_PERCENT', 4.0))

        if self.idempotency.seen(signal_id, symbol=symbol):
            logger.info(f"⏭️ Skipping duplicate: {signal_id}")
            return True 

        if not all([symbol, side, qty]):
            self.alerts.send(f"Malformed signal for {signal_id}", severity="WARNING")
            return False 

        try:
            logger.info(f"🚀 Opening {side} Position for {symbol}...")
            order = self.exchange.futures_create_order(
                symbol=symbol, side=side, type='MARKET', quantity=qty
            )

            if order and order.get('status') == 'FILLED':
                entry_price = float(order.get('avgPrice', 0.0))
                # Log to internal ledger
                self.ledger.apply_fill(symbol, side.lower(), qty, entry_price)

                exit_side = 'SELL' if side == 'BUY' else 'BUY'
                if side == 'BUY':
                    sl_price = round(entry_price * (1 - sl_percent / 100), 2)
                    tp_price = round(entry_price * (1 + tp_percent / 100), 2)
                else:
                    sl_price = round(entry_price * (1 + sl_percent / 100), 2)
                    tp_price = round(entry_price * (1 - tp_percent / 100), 2)

                # Set Protective Orders (SL/TP)
                self.exchange.futures_create_order(
                    symbol=symbol, side=exit_side, type='STOP_MARKET',
                    stopPrice=sl_price, closePosition=True
                )
                self.exchange.futures_create_order(
                    symbol=symbol, side=exit_side, type='TAKE_PROFIT_MARKET',
                    stopPrice=tp_price, closePosition=True
                )

                self.alerts.send(
                    f"✅ TRADE OPENED: {side} {symbol} @ {entry_price}\n"
                    f"🛑 SL: {sl_price} ({sl_percent}%)\n"
                    f"🎯 TP: {tp_price} ({tp_percent}%)",
                    strategy_id=signal_id
                )
                return True
            else:
                self.alerts.send(f"⚠️ Order Failed: {order.get('status') if order else 'Timeout'}", severity="WARNING")
                return False

        except Exception as e:
            logger.error(f"❌ Execution Error: {str(e)}")
            self.alerts.send(f"❌ Binance Error: {str(e)}", severity="CRITICAL")
            return False

    def start(self):
        logger.info("🚀 Risk-Managed Bot Orchestrator Started")
        self.alerts.send("Bot Engine Online (Audit & SL/TP Active)", severity="INFO")
        
        while self.running:
            # 1. Poll for Trading Signals from Queue
            self.consumer.poll(self.process_signal, batch_size=5)
            
            # 2. Poll for Interactive Telegram Commands
            self.handle_telegram_commands()
            
            # 3. Run Periodic Reconciliation Audit
            self.run_recon_cycle()
            
            # 4. Prevent API spam and high CPU usage
            time.sleep(self.config.get('POLL_INTERVAL', 2))

if __name__ == "__main__":
    cfg = {
        'QUEUE_PATH': 'storage/signals.jsonl',
        'OFFSET_PATH': 'storage/signals.offset',
        'DLQ_PATH': 'storage/dlq.jsonl',
        'IDEMPOTENCY_DB_PATH': 'storage/idempotency.db',
        'ALERTS_LOG_PATH': 'storage/alerts.jsonl',
        'POLL_INTERVAL': 1,
        'USE_TESTNET': True,
        'RECON_INTERVAL_SEC': 900,  # 15 minutes
        'RECON_TOLERANCE': 0.0001,
        'DEFAULT_SL_PERCENT': 1.5,
        'DEFAULT_TP_PERCENT': 3.0
    }
    bot = TradingBotOrchestrator(cfg)
    bot.start()
