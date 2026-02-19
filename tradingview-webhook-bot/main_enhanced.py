#!/usr/bin/env python3
"""
Enhanced TradingView Trading Bot with Mainnet Price Authority
STRICT RULES:
- ALL prices come from Binance MAINNET
- ALL orders are LIMIT orders on TESTNET
- P&L calculated using MAINNET prices only
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
# Add parent directory to path (for scripts/ module imports)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from exchange.binance_client import BinanceClient
from exchange.price_provider import get_price_provider
from exchange.execution_engine import get_execution_engine
from core.enhanced_order_manager import EnhancedOrderManager
from core.strategy_engine import StrategyEngine
from core.webhook_server import WebhookServer
from core.signal_processor import SignalProcessor
from core.position_manager import PositionManager
from core.balance_manager import BalanceManager
from core.order_monitor import get_order_monitor
from utils.logger import setup_logger
from utils.instance_lock import InstanceLock, InstanceLockError
from utils.health_checker import get_health_checker
from utils.dashboard_updater import trigger_dashboard_update
from utils.signal_archiver import SignalArchiver

# Load environment variables
load_dotenv()

# Global logger
logger = None

# Global flag for graceful shutdown
running = True

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    global running
    logger.info("🛑 Shutdown signal received, stopping enhanced bot...")
    running = False

class EnhancedTradingBot:
    """Enhanced trading bot with mainnet price authority"""
    
    def __init__(self, config_file='config/settings.json'):
        global logger
        
        # Load configuration
        logger.info(f"📂 Loading configuration from: {config_file}")
        with open(config_file, 'r') as f:
            self.config = json.load(f)
        
        # Get strategy name
        self.strategy_name = self.config.get('strategy_name', 'multi_strategy')
        
        # Reinitialize logger with strategy name
        log_file = self.config.get('logging', {}).get('file', f'logs/enhanced_bot_{self.strategy_name}.log')
        logger = setup_logger(f'enhanced_main_{self.strategy_name}', log_file=log_file)
        
        logger.info(f"🚀 Initializing Enhanced TradingView Bot with Mainnet Price Authority [{self.strategy_name}]...")
        
        # Storage files
        storage_config = self.config.get('storage', {})
        self.signals_queue = storage_config.get('signals_queue', f'storage/signals_{self.strategy_name}.jsonl')
        self.positions_file = storage_config.get('positions', f'storage/positions_{self.strategy_name}.jsonl')
        balance_file = storage_config.get('balance', f'storage/balance_{self.strategy_name}.json')
        
        # Initialize new architecture components
        logger.info("🌐 Initializing mainnet price provider...")
        self.price_provider = get_price_provider()
        
        logger.info("🧪 Initializing testnet execution engine...")
        self.execution_engine = get_execution_engine()
        
        logger.info("🧠 Initializing strategy engine...")
        self.strategy_engine = StrategyEngine(self.config)
        
        # Virtual balance manager
        initial_balance = self.config.get('virtual_balance', 100.0)
        self.balance_manager = BalanceManager(balance_file, initial_balance)
        
        # Legacy client for compatibility
        self.client = BinanceClient()
        
        # Position manager
        self.position_manager = PositionManager(self.config, self.positions_file, self.strategy_name)
        
        # Signal processor with MAINNET price validation
        self.signal_processor = SignalProcessor(
            self.config, 
            self.client, 
            self.strategy_name,
            price_provider=self.price_provider  # Use mainnet for price validation
        )
        
        # Enhanced order manager
        self.order_manager = EnhancedOrderManager(
            self.config, self.client, self.position_manager, 
            self.balance_manager, self.strategy_name
        )
        
        # Order monitor for tracking fills
        logger.info("📊 Initializing order monitor...")
        self.order_monitor = get_order_monitor(self.strategy_name)
        
        # Webhook server
        self.webhook_server = WebhookServer(self.config, self.signals_queue)
        
        # Signal archiver for queue management
        logger.info("📦 Initializing signal archiver...")
        self.signal_archiver = SignalArchiver(retention_days=7)
        
        logger.info("✅ Enhanced bot initialization complete")
        
        # Display status
        self.display_status()
    
    def display_status(self):
        """Display enhanced bot configuration and status"""
        # Get balances from both sources
        virtual_balance = self.balance_manager.get_balance()
        testnet_balance = self.execution_engine.get_balance()
        balance_stats = self.balance_manager.get_performance_summary()
        open_positions = self.position_manager.count_open_positions()
        
        # Get current market info
        btc_info = self.price_provider.get_price_info('BTCUSDT')
        
        # Get enabled strategies
        enabled_strategies = self.config.get('strategies', {}).get('enabled', [self.strategy_name])
        if isinstance(enabled_strategies, str):
            enabled_strategies = [enabled_strategies]
        
        logger.info("=" * 80)
        logger.info(f"🚀 ENHANCED BOT STATUS - {self.strategy_name.upper()} - MAINNET PRICE AUTHORITY")
        logger.info("=" * 80)
        logger.info(f"🌐 MAINNET Price Source: LIVE Binance (${btc_info['price']:.2f} BTCUSDT)" if btc_info else "🌐 MAINNET Price Source: LIVE Binance")
        logger.info(f"🧪 TESTNET Execution: Balance ${testnet_balance:.2f}")
        logger.info(f"💰 Virtual Balance: ${virtual_balance:.2f} USDT")
        logger.info(f"📈 Initial Balance: ${balance_stats['initial_balance']:.2f} USDT")
        logger.info(f"💵 Realized P&L: ${balance_stats['realized_pnl']:+.2f} USDT ({balance_stats['roi_percent']:+.2f}%)")
        logger.info(f"📊 Total Trades: {balance_stats['total_trades']} (W: {balance_stats['winning_trades']} | L: {balance_stats['losing_trades']} | WR: {balance_stats['win_rate_percent']:.1f}%)")
        logger.info(f"📈 Open Positions: {open_positions}/{self.config['risk']['max_positions']}")
        logger.info(f"🎯 Strategy: {', '.join(enabled_strategies)}")
        logger.info(f"📱 Allowed Symbols: {', '.join(self.config['trading']['symbols_allowed'])}")
        logger.info(f"⚡ Leverage: {self.config['trading']['leverage']}x")
        logger.info(f"📊 Position Size: {self.config['risk']['position_size_value']}% of balance")
        logger.info(f"🌐 Webhook Port: {self.config['webhook']['port']}")
        logger.info(f"🛡️ Order Type: LIMIT ONLY (No Market Orders)")
        logger.info(f"💰 P&L Calculation: MAINNET PRICES ONLY")
        logger.info("=" * 80)
    
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
    
    def enhanced_monitor_positions(self):
        """Enhanced position monitoring using MAINNET prices and order fill detection"""
        try:
            # 1. Check for order fills and sync virtual state
            open_positions = self.position_manager.get_open_positions()
            for position in open_positions:
                sync_result = self.order_monitor.sync_position(position, self.positions_file)
                
                if sync_result.get('closed'):
                    # Position was closed via SL/TP, update virtual balance
                    pnl = sync_result.get('pnl', 0)
                    if pnl != 0:
                        self.balance_manager.update_balance(pnl)
                        logger.info(f"💰 Virtual balance updated: ${self.balance_manager.get_balance():.2f} (PnL: ${pnl:+.2f})")
            
            # 2. Use enhanced order manager's monitoring with mainnet prices
            self.order_manager.monitor_positions_with_mainnet_prices()
            
        except Exception as e:
            logger.error(f"❌ Error in enhanced position monitoring: {e}")
    
    def trading_loop(self):
        """Enhanced trading loop with mainnet price authority"""
        logger.info("🔄 Starting enhanced trading loop with mainnet price authority...")
        
        loop_count = 0
        last_dashboard_update = 0
        last_archive_run = 0
        last_price_log = 0
        
        while running:
            try:
                loop_count += 1
                current_time = time.time()
                
                # Process signals every 5 seconds
                validated_signals = self.signal_processor.process_signals(self.signals_queue)
                
                if validated_signals:
                    logger.info(f"🎯 Found {len(validated_signals)} valid signals to execute")
                    self.order_manager.process_signals(validated_signals)
                
                # Enhanced position monitoring using MAINNET prices
                self.enhanced_monitor_positions()
                
                # Log current MAINNET prices every 5 minutes
                if current_time - last_price_log >= 300:
                    try:
                        btc_info = self.price_provider.get_price_info('BTCUSDT')
                        if btc_info:
                            logger.info(f"📊 MAINNET: BTCUSDT ${btc_info['price']:.2f}, spread: {btc_info['spread_pct']:.3f}%")
                        last_price_log = current_time
                    except Exception as e:
                        logger.warning(f"⚠️ Could not log price info: {e}")
                
                # Update dashboard every 60 seconds
                if current_time - last_dashboard_update >= 60:
                    try:
                        updated, msg = trigger_dashboard_update(
                            strategy_name=self.strategy_name,
                            min_interval_seconds=60
                        )

                        if updated:
                            logger.info(f"📊 Dashboard update triggered: {msg}")
                        else:
                            logger.debug(f"📊 Dashboard update skipped: {msg}")

                        last_dashboard_update = current_time
                    except Exception as e:
                        logger.warning(f"⚠️ Dashboard update failed: {e}")
                
                # Archive old signals every 24 hours (prevents unbounded queue growth)
                if current_time - last_archive_run >= 86400:  # 24 hours
                    try:
                        logger.info(f"📦 Running signal queue archival...")
                        active_count, archived_count = self.signal_archiver.archive_old_signals(self.signals_queue)
                        
                        if archived_count > 0:
                            logger.info(f"✅ Signal archival complete: {active_count} active, {archived_count} archived")
                        else:
                            logger.info(f"✓ No signals to archive (all recent)")
                        
                        # Get archive stats
                        stats = self.signal_archiver.get_archive_stats()
                        logger.info(f"📦 Archive stats: {stats['total_archives']} files, {stats['total_size_mb']:.2f} MB")
                        
                        # Cleanup archives older than 30 days
                        cleanup_count = self.signal_archiver.cleanup_old_archives(max_age_days=30)
                        if cleanup_count > 0:
                            logger.info(f"🗑️ Cleaned up {cleanup_count} old archive(s)")
                        
                        last_archive_run = current_time
                        
                    except Exception as e:
                        logger.error(f"❌ Signal archival error: {e}")
                
                # Enhanced heartbeat every 10 loops
                if loop_count % 10 == 0:
                    virtual_balance = self.balance_manager.get_balance()
                    testnet_balance = self.execution_engine.get_balance()
                    open_pos = self.position_manager.count_open_positions()
                    
                    logger.info(f"💓 ENHANCED HEARTBEAT | Strategy: {self.strategy_name} | Virtual: ${virtual_balance:.2f} | Testnet: ${testnet_balance:.2f} | Open: {open_pos} | Loop: {loop_count}")
                
                # Sleep
                time.sleep(5)
                
            except KeyboardInterrupt:
                logger.info("⌨️ Keyboard interrupt received")
                break
            except Exception as e:
                logger.error(f"❌ Error in enhanced trading loop: {e}")
                time.sleep(10)
        
        logger.info("🛑 Enhanced trading loop stopped")
    
    def run(self):
        """Run the enhanced bot"""
        try:
            # Start webhook server
            self.start_webhook_server()
            
            # Run enhanced trading loop
            self.trading_loop()
            
        except KeyboardInterrupt:
            logger.info("⌨️ Interrupted by user")
        except Exception as e:
            logger.error(f"❌ Fatal error in enhanced bot: {e}")
            raise
        finally:
            logger.info("👋 Enhanced bot shutdown complete")

def main():
    """Main entry point for enhanced bot"""
    global logger
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Enhanced TradingView Bot with Mainnet Price Authority')
    parser.add_argument('--config', type=str, default='config/settings.json',
                       help='Path to configuration file (default: config/settings.json)')
    args = parser.parse_args()
    
    # Initialize logger
    logger = setup_logger('enhanced_main', log_file='logs/enhanced_bot.log')
    
    # Register signal handlers
    sig.signal(sig.SIGINT, signal_handler)
    sig.signal(sig.SIGTERM, signal_handler)
    
    # Load config to get strategy name for lock
    try:
        with open(args.config, 'r') as f:
            config = json.load(f)
        strategy_name = config.get('strategy_name', 'multi_strategy')
    except Exception as e:
        logger.error(f"❌ Failed to load config: {e}")
        sys.exit(1)
    
    # Acquire instance lock to prevent duplicate instances
    try:
        instance_lock = InstanceLock(strategy_name)
        instance_lock.acquire()
    except InstanceLockError as e:
        logger.error(f"❌ {e}")
        logger.error("💡 Another instance is already running. If this is incorrect, remove the lock file and try again.")
        sys.exit(1)
    
    logger.info("=" * 80)
    logger.info("🚀 Enhanced TradingView Bot - Mainnet Price Authority")
    logger.info("🌐 Price Source: Binance MAINNET (Live)")
    logger.info("🧪 Execution: Binance TESTNET")
    logger.info("🛡️ Orders: LIMIT ONLY")
    logger.info("💰 P&L: MAINNET PRICES")
    logger.info(f"📂 Config: {args.config}")
    logger.info(f"🔒 Instance Lock: {strategy_name}")
    logger.info("=" * 80)
    
    try:
        bot = EnhancedTradingBot(config_file=args.config)
        bot.run()
    except Exception as e:
        logger.error(f"❌ Enhanced bot crashed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        # Release instance lock
        instance_lock.release()
        logger.info("🔓 Instance lock released")

if __name__ == '__main__':
    main()