import sys
import os
import logging
from pathlib import Path

# --- PATH FIX START (Exactly as used in your server file) ---
ROOT_DIR = Path(__file__).resolve().parent
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

# AB YAHAN DHYAN DEIN: 
# Kyunki 'core' folder 'tradingview-webhook-bot' ke andar hai, 
# hum use hamare inject kiye hue module ke through import karenge.
try:
    from tradingview_webhook_bot.core.orchestrator import Orchestrator
    print("✅ Orchestrator loaded successfully.")
except ImportError as e:
    print(f"❌ Import failed: {e}")
    # Fallback: Agar upar waala fail ho toh direct import try karein (folder path add karke)
    sys.path.append(str(ROOT_DIR / "tradingview-webhook-bot"))
    from core.orchestrator import Orchestrator

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    print("🎬 Starting Trading Engine (Orchestrator)...")
    try:
        bot = Orchestrator()
        bot.run()
    except KeyboardInterrupt:
        print("\n🛑 Engine stopped by user.")
    except Exception as e:
        print(f"❌ Engine Crash: {e}")
