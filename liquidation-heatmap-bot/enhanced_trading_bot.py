"""
Enhanced Trading Bot Entry Point
Refactored to use modular components with backtest artifact export.
"""
import os
import sys
import time
import json
import logging
import random
import asyncio
import threading
import signal as signal_module
import fcntl
from datetime import datetime, timezone

# Add project root to path if needed
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import config_manager
from signal_generator import EnhancedRLSignalGenerator
from data_sources import EnhancedBinanceWebSocketClient, EnhancedGoogleSheetsClient
import metrics

# Global reference for signal handlers
rl_generator_global = None

# Configure logging (only if not already configured to avoid duplicate handlers)
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("bot.log"),
            logging.StreamHandler()
        ]
    )
logger = logging.getLogger("EnhancedTradingBot")

def shutdown_handler(signum, frame):
    """Handle SIGTERM/SIGINT to emit session summary before shutdown"""
    global rl_generator_global
    logger.info(f"Received signal {signum}, emitting session summary and shutting down...")
    try:
        if rl_generator_global and hasattr(rl_generator_global, 'emitters'):
            if rl_generator_global.emitters:
                logger.info("Closing observability hub to emit session summary...")
                # Flush LLM summaries first
                if hasattr(rl_generator_global.emitters, 'llm_emitter'):
                    try:
                        logger.info("Flushing LLM trade and session summaries...")
                        rl_generator_global.emitters.llm_emitter.flush_all()
                        logger.info("LLM summaries flushed successfully")
                    except Exception as llm_err:
                        logger.error(f"Error flushing LLM summaries: {llm_err}")
                # Then close emitters (which also tries to emit session summary)
                rl_generator_global.emitters.close()
        if rl_generator_global:
            rl_generator_global.stop()
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")
    finally:
        sys.exit(0)

def main():
    """Main function with enhanced configuration"""
    global rl_generator_global
    run_id = f"r_{int(datetime.now(timezone.utc).timestamp())}"
    
    # PID file locking to prevent duplicate processes
    pid_file_path = '/tmp/trading-bot.pid'
    pid_file = None
    try:
        pid_file = open(pid_file_path, 'w')
        fcntl.flock(pid_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        pid_file.write(str(os.getpid()))
        pid_file.flush()
        logger.info(f"Acquired PID lock: {pid_file_path} (PID: {os.getpid()})")
    except IOError:
        logger.error(f"Another instance of the bot is already running (PID file locked: {pid_file_path})")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to create PID file {pid_file_path}: {e}")
        sys.exit(1)
    
    # Register signal handlers for graceful shutdown
    signal_module.signal(signal_module.SIGTERM, shutdown_handler)
    signal_module.signal(signal_module.SIGINT, shutdown_handler)
    logger.info("Registered SIGTERM/SIGINT handlers for session summary emission")
    
    try:
        # Load configuration
        config = config_manager
        trading_config = config.get_trading_config()
        api_config = config.get_api_config()

        # Load credentials files (try multiple files and paths)
        credentials_files = []
        possible_paths = [
            'credentials.json',
            'credentials1.json',
            'credentials2.json',
            'trading_bot/credentials.json',
            'trading_bot/credentials1.json',
            'trading_bot/credentials2.json',
            os.path.join(os.path.dirname(__file__), 'credentials.json'),
            os.path.join(os.path.dirname(__file__), 'credentials1.json'),
            os.path.join(os.path.dirname(__file__), 'credentials2.json')
        ]
        
        for filename in possible_paths:
            if os.path.exists(filename):
                try:
                    with open(filename, 'r') as f:
                        credentials_data = json.load(f)
                    # Avoid duplicates
                    if credentials_data not in credentials_files:
                        credentials_files.append(credentials_data)
                        logger.info(f"Loaded credentials: {filename}")
                except Exception as e:
                    logger.warning(f"Failed to load {filename}: {e}")

        if not credentials_files:
            logger.error("No credentials files found!")
            logger.error(f"Searched paths: {possible_paths}")
            logger.error(f"Current directory: {os.getcwd()}")
            return

        # Initialize enhanced signal generator with rotating credentials
        rl_generator = EnhancedRLSignalGenerator(
            credentials_files,  # Use all credentials files for rotation
            api_config.liquidation_spreadsheet_key,
            api_config.oi_fr_spreadsheet_key,
            api_config.output_sheet_key,
            api_config.sheet_names_config
        )
        rl_generator_global = rl_generator  # Store for signal handler

        # Add startup delay to avoid quota issues
        startup_delay = random.uniform(30, 60)  # 30-60 seconds
        logger.info(f"Waiting {startup_delay/60:.1f} minutes before starting to avoid quota issues...")    
        time.sleep(startup_delay)

        # Start the bot
        rl_generator.start()

        # Keep running - signal generator runs its own internal thread
        logger.info("Bot started successfully! Monitoring for signals...")
        logger.info("Using extended delays to prevent API rate limiting")
        logger.info("Press Ctrl+C to stop")
        
        while True:
            try:
                # Use much longer random delay to avoid API quota issues
                try: rl_generator.emitters.emit_health(price_age_s=0, signal_gen_ok=True, uptime_s=int(time.time()), session_id=run_id); pass
                except: pass
                delay = random.uniform(120, 240)  # 2-4 minutes between cycles
                logger.info(f"Bot running. Sleeping for {delay/60:.1f} minutes...")
                time.sleep(delay)
            except Exception as loop_error:
                logger.error(f"Error in main loop: {loop_error}")
                import traceback
                traceback.print_exc()
                time.sleep(60)  # Wait a minute before retrying

    except KeyboardInterrupt:
        logger.info("Shutting down Enhanced RL Trading Bot...")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            if 'rl_generator' in locals() and rl_generator is not None:
                # Close observability hub to flush session summary
                if hasattr(rl_generator, 'emitters') and rl_generator.emitters:
                    try:
                        logger.info("Closing observability hub and emitting session summary...")
                        rl_generator.emitters.close()
                    except Exception as e:
                        logger.error(f"Error closing observability hub: {e}")
                
                rl_generator.stop()  # type: ignore
        except Exception:
            pass
        
        # Export backtest artifacts if enabled
        if os.getenv('EXPORT_BACKTEST_ARTIFACTS', '0') == '1':
            logger.info("="*80)
            logger.info("EXPORTING BACKTEST ARTIFACTS")
            logger.info("="*80)
            
            try:
                from backtest_artifacts_exporter import export_all
                artifacts = export_all(
                    run_id=run_id,
                    events_dir='./logs/events',
                    out_dir='./backtest_artifacts',
                    initial_equity=100000.0
                )
                logger.info(f"Successfully exported {len(artifacts)} artifacts")
                for name, path in artifacts.items():
                    logger.info(f"  {name}: {path}")
            except Exception as export_error:
                logger.error(f"Failed to export backtest artifacts: {export_error}")
                import traceback
                traceback.print_exc()
        
        # Cleanup PID lock
        try:
            if pid_file:
                fcntl.flock(pid_file.fileno(), fcntl.LOCK_UN)
                pid_file.close()
                os.remove(pid_file_path)
                logger.info(f"Released PID lock: {pid_file_path}")
        except Exception as e:
            logger.error(f"Error releasing PID lock: {e}")

if __name__ == "__main__":
    main()
