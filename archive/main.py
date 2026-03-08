#!/usr/bin/env python3
"""
from datetime import datetime
TradingView-Only Trading Bot
Simplified bot that ONLY processes TradingView webhook signals
"""

import json
import time
import os
import sys
import signal as sig
import argparse
from threading import Thread
from dotenv import load_dotenv

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from exchange.binance_client import BinanceClient
from core.webhook_server import WebhookServer
from core.signal_processor import SignalProcessor
from core.position_manager import PositionManager
from core.order_manager import OrderManager
from core.balance_manager import BalanceManager
from utils.logger import setup_logger

# Load environment variables
load_dotenv()

# Global logger (will be reinitialized with strategy name)
logger = None

# Global flag for graceful shutdown
running = True

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    global running
    logger.info("🛑 Shutdown signal received, stopping bot...")
    running = False

class TradingBot:
    """Main trading bot orchestrator"""
    
    def __init__(self, config_file='config/settings.json'):
        global logger
        
        # Load configuration
        logger.info(f"📂 Loading configuration from: {config_file}")
        with open(config_file, 'r') as f:
            self.config = json.load(f)
        
        # Get strategy name (if specified in config)
        self.strategy_name = self.config.get('strategy_name', 'multi_strategy')
        
        # Reinitialize logger with strategy name
        log_file = self.config.get('logging', {}).get('file', f'logs/bot_{self.strategy_name}.log')
        logger = setup_logger(f'main_{self.strategy_name}', log_file=log_file)
        
        logger.info(f"🤖 Initializing TradingView-Only Trading Bot [{self.strategy_name}]...")
        
        # Storage files (strategy-specific if configured)
        storage_config = self.config.get('storage', {})
        self.signals_queue = storage_config.get('signals_queue', f'storage/signals_{self.strategy_name}.jsonl')
        self.positions_file = storage_config.get('positions', f'storage/positions_{self.strategy_name}.jsonl')
        balance_file = storage_config.get('balance', f'storage/balance_{self.strategy_name}.json')
        
        # Virtual balance manager
        initial_balance = self.config.get('virtual_balance', 100.0)
        self.balance_manager = BalanceManager(balance_file, initial_balance)
        
        # Binance client
        self.client = BinanceClient()
        
        # Position manager (with strategy filter)
        self.position_manager = PositionManager(self.config, self.positions_file, self.strategy_name)
        
        # Signal processor (with strategy filter)
        self.signal_processor = SignalProcessor(self.config, self.client, self.strategy_name)
        
        # Order manager (with balance manager and strategy name)
        self.order_manager = OrderManager(self.config, self.client, self.position_manager, 
                                         self.balance_manager, self.strategy_name)
        
        # Webhook server
        self.webhook_server = WebhookServer(self.config, self.signals_queue)
        
        logger.info("✅ Bot initialization complete")
        
        # Display status
        self.display_status()
    
    def display_status(self):
        """Display bot configuration and status"""
        # Use virtual balance instead of real balance
        virtual_balance = self.balance_manager.get_balance()
        balance_stats = self.balance_manager.get_performance_summary()
        open_positions = self.position_manager.count_open_positions()
        
        # Get enabled strategies (single strategy if specified)
        enabled_strategies = self.config.get('strategies', {}).get('enabled', [self.strategy_name])
        if isinstance(enabled_strategies, str):
            enabled_strategies = [enabled_strategies]
        
        logger.info("=" * 60)
        logger.info(f"📊 BOT STATUS - {self.strategy_name.upper()}")
        logger.info("=" * 60)
        logger.info(f"💰 Virtual Balance: ${virtual_balance:.2f} USDT")
        logger.info(f"📈 Initial Balance: ${balance_stats['initial_balance']:.2f} USDT")
        logger.info(f"💵 Realized PnL: ${balance_stats['realized_pnl']:+.2f} USDT ({balance_stats['roi_percent']:+.2f}%)")
        logger.info(f"📊 Total Trades: {balance_stats['total_trades']} (W: {balance_stats['winning_trades']} | L: {balance_stats['losing_trades']} | WR: {balance_stats['win_rate_percent']:.1f}%)")
        logger.info(f"📈 Open Positions: {open_positions}/{self.config['risk']['max_positions']}")
        logger.info(f"🎯 Strategy: {', '.join(enabled_strategies)}")
        logger.info(f"📱 Allowed Symbols: {', '.join(self.config['trading']['symbols_allowed'])}")
        logger.info(f"⚡ Leverage: {self.config['trading']['leverage']}x")
        logger.info(f"📊 Position Size: {self.config['risk']['position_size_value']}% of balance")
        logger.info(f"🌐 Webhook Port: {self.config['webhook']['port']}")
        logger.info("=" * 60)
    
    def start_webhook_server(self):
        """Start webhook server in separate thread"""
        def run_server():
            try:
                self.webhook_server.run()
            except Exception as e:
                logger.error(f"Webhook server error: {e}")
        
        server_thread = Thread(target=run_server, daemon=True)
        server_thread.start()
        logger.info("🌐 Webhook server started in background")
        
        # Give server time to start
        time.sleep(2)
    

    def monitor_positions(self):
        """Monitor open positions and update status when SL/TP fills with improved validation"""
        try:
            # Get all open tracked positions
            positions = self.position_manager.get_open_positions()
            open_positions = [p for p in positions if p.get('status') == 'open']
            
            if not open_positions:
                return
            
            for position in open_positions:
                symbol = position['symbol']
                
                # Check if position still exists on Binance
                binance_pos = self.client.get_position(symbol)
                position_amt = float(binance_pos.get('positionAmt', 0)) if binance_pos else 0
                
                # If no position on Binance, it was closed
                if position_amt == 0:
                    # Check which order filled (SL or TP) with better validation
                    sl_order_id = position.get('sl_order_id')
                    tp_order_id = position.get('tp_order_id')
                    
                    exit_type = 'UNKNOWN'
                    exit_price = 0
                    pnl = 0
                    
                    try:
                        # Check SL order first
                        if sl_order_id:
                            try:
                                sl_order = self.client.client.futures_get_order(symbol=symbol, orderId=sl_order_id)
                                if sl_order['status'] == 'FILLED':
                                    exit_type = 'STOP_LOSS'
                                    exit_price = float(sl_order.get('avgPrice', sl_order.get('price', position['stop_loss'])))
                                    logger.info(f"🛑 SL triggered: {symbol} @ ${exit_price:.2f}")
                                elif sl_order['status'] in ['CANCELED', 'REJECTED', 'EXPIRED']:
                                    logger.warning(f"⚠️ SL order {sl_order['status']}: {symbol}")
                            except Exception as sl_error:
                                logger.warning(f"⚠️ Could not check SL order {sl_order_id}: {sl_error}")
                        
                        # Check TP order if SL didn't fill
                        if exit_type == 'UNKNOWN' and tp_order_id:
                            try:
                                tp_order = self.client.client.futures_get_order(symbol=symbol, orderId=tp_order_id)
                                if tp_order['status'] == 'FILLED':
                                    exit_type = 'TAKE_PROFIT'
                                    exit_price = float(tp_order.get('avgPrice', tp_order.get('price', position['take_profit'])))
                                    logger.info(f"🎯 TP hit: {symbol} @ ${exit_price:.2f}")
                                elif tp_order['status'] in ['CANCELED', 'REJECTED', 'EXPIRED']:
                                    logger.warning(f"⚠️ TP order {tp_order['status']}: {symbol}")
                            except Exception as tp_error:
                                logger.warning(f"⚠️ Could not check TP order {tp_order_id}: {tp_error}")
                        
                        # If still unknown, check recent trades to determine exit
                        if exit_type == 'UNKNOWN':
                            try:
                                recent_trades = self.client.client.futures_account_trades(symbol=symbol, limit=10)
                                for trade in recent_trades:
                                    if trade.get('orderId') in [sl_order_id, tp_order_id]:
                                        exit_price = float(trade['price'])
                                        exit_type = 'STOP_LOSS' if trade['orderId'] == sl_order_id else 'TAKE_PROFIT'
                                        break
                            except Exception as trade_error:
                                logger.warning(f"⚠️ Could not check recent trades: {trade_error}")
                        
                        # Final fallback - use current market price
                        if exit_price == 0:
                            exit_price = self.client.get_current_price(symbol)
                            exit_type = 'MARKET_CLOSE'
                            logger.warning(f"⚠️ Using market price for exit: {symbol} @ ${exit_price:.2f}")
                            
                    except Exception as order_check_error:
                        logger.error(f"❌ Error checking orders for {symbol}: {order_check_error}")
                        # Use current market price as fallback
                        exit_price = self.client.get_current_price(symbol)
                        exit_type = 'ERROR_FALLBACK'
                    
                    # Calculate P&L
                    entry_price = float(position['entry_price'])
                    position_size = float(position['position_size'])
                    side = position['side']
                    
                    # Calculate position value in USDT
                    position_value_usdt = entry_price * position_size

                    if exit_price > 0:
                        if side == 'LONG':
                            pnl = (exit_price - entry_price) * position_size
                        else:
                            pnl = (entry_price - exit_price) * position_size

                    # Update position status
                    import datetime as dt
                    self.position_manager.update_position(position['position_id'], {
                        'status': 'closed',
                        'exit_type': exit_type,
                        'exit_price': str(exit_price),
                        'exit_time': dt.datetime.now().isoformat(),
                        'pnl': pnl,
                        'closed_at': dt.datetime.now().isoformat()
                    })

                    # Update balance - pass USDT value not BTC amount
                    self.balance_manager.update_on_close(position_value_usdt, pnl)
                    
                    logger.info(f"📍 Position closed: {symbol} | {exit_type} @ ${exit_price:.2f} | P&L: ${pnl:.2f}")
                    
        except Exception as e:
            logger.error(f"Error monitoring positions: {e}")

    def trading_loop(self):
        """Main trading loop - process signals"""
        logger.info("🔄 Starting trading loop...")
        
        loop_count = 0
        last_dashboard_update = 0
        
        while running:
            try:
                loop_count += 1
                current_time = time.time()
                
                # Process signals every 5 seconds
                validated_signals = self.signal_processor.process_signals(self.signals_queue)
                
                if validated_signals:
                    logger.info(f"🎯 Found {len(validated_signals)} valid signals to execute")
                    self.order_manager.process_signals(validated_signals)

                # Monitor open positions for SL/TP fills
                self.monitor_positions()
                
                # Update Google Sheets dashboard every 60 seconds
                if current_time - last_dashboard_update >= 60:
                    try:
                        # Import correct dashboard script based on strategy
                        if self.strategy_name == 'institutional_matrix':
                            # Dashboard updates handled by clean_dashboard_4tabs.py via cron
                            pass  # Using centralized dashboard

                            # from update_institutional_matrix_dashboard import update_sheet
                        else:
                            # Dashboard updates handled by clean_dashboard_4tabs.py via cron
                            pass  # Using centralized dashboard

                            # from update_live_dashboard import update_sheet
                        # Dashboard updates disabled - using clean_dashboard_4tabs.py
                        pass
                        last_dashboard_update = current_time
                        logger.info("📊 Dashboard update triggered")
                    except Exception as e:
                        logger.warning(f"⚠️ Dashboard update failed: {e}")
                
                # Heartbeat every 10 loops (50 seconds)
                if loop_count % 10 == 0:
                    virtual_balance = self.balance_manager.get_balance()
                    open_pos = self.position_manager.count_open_positions()
                    logger.info(f"💓 HEARTBEAT | Strategy: {self.strategy_name} | Balance: ${virtual_balance:.2f} | Open: {open_pos} | Loop: {loop_count}")
                
                # Sleep
                time.sleep(5)
                
            except KeyboardInterrupt:
                logger.info("⌨️ Keyboard interrupt received")
                break
            except Exception as e:
                logger.error(f"❌ Error in trading loop: {e}")
                time.sleep(10)
        
        logger.info("🛑 Trading loop stopped")
    
    def run(self):
        """Run the bot"""
        try:
            # Start webhook server
            self.start_webhook_server()
            
            # Run trading loop
            self.trading_loop()
            
        except KeyboardInterrupt:
            logger.info("⌨️ Interrupted by user")
        except Exception as e:
            logger.error(f"❌ Fatal error: {e}")
            raise
        finally:
            logger.info("👋 Bot shutdown complete")

def main():
    """Main entry point"""
    global logger
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='TradingView-Only Trading Bot')
    parser.add_argument('--config', type=str, default='config/settings.json',
                       help='Path to configuration file (default: config/settings.json)')
    args = parser.parse_args()
    
    # Initialize logger with default name first
    logger = setup_logger('main', log_file='logs/bot.log')
    
    # Register signal handlers
    sig.signal(sig.SIGINT, signal_handler)
    sig.signal(sig.SIGTERM, signal_handler)
    
    logger.info("=" * 60)
    logger.info("🚀 TradingView-Only Trading Bot")
    logger.info(f"📂 Config: {args.config}")
    logger.info("=" * 60)
    
    try:
        bot = TradingBot(config_file=args.config)
        bot.run()
    except Exception as e:
        logger.error(f"❌ Bot crashed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
