import sys
import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# --- PATH FIX START ---
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Explicitly load .env from the root directory
env_path = ROOT_DIR / ".env"
load_success = load_dotenv(dotenv_path=env_path)
# --- PATH FIX END ---

try:
    import tradingview_webhook_bot
except ImportError:
    import importlib.util
    folder_path = ROOT_DIR / "tradingview_webhook_bot"
    if folder_path.exists():
        spec = importlib.util.spec_from_file_location(
            "tradingview_webhook_bot",
            str(folder_path / "__init__.py")
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["tradingview_webhook_bot"] = module
        spec.loader.exec_module(module)

try:
    from tradingview_webhook_bot.core.orchestrator import Orchestrator
    # print hata kar logging use karein consistent rehne ke liye
except ImportError as e:
    sys.path.append(str(ROOT_DIR / "tradingview_webhook_bot"))
    from core.orchestrator import Orchestrator

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    logger.info(f"📁 Root Directory: {ROOT_DIR}")
    logger.info(f"🔐 .env Load Status: {load_success}")
    logger.info("🎬 Starting Trading Engine (Orchestrator)...")
    
    try:
        bot = Orchestrator()
        bot.run()
    except KeyboardInterrupt:
        logger.info("🛑 Engine stopped by user.")
    except Exception as e:
        logger.error(f"❌ Engine Crash: {e}")
