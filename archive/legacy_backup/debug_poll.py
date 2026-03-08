import sys
import os
from pathlib import Path
import importlib.util

# --- 1. HYPHEN FOLDER PATH FIX ---
ROOT_DIR = Path(__file__).resolve().parent
folder_path = ROOT_DIR / "tradingview_webhook_bot"

if folder_path.exists():
    spec = importlib.util.spec_from_file_location(
        "tradingview_webhook_bot", 
        str(folder_path / "__init__.py")
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["tradingview_webhook_bot"] = module
    spec.loader.exec_module(module)
    print("✅ Module 'tradingview_webhook_bot' loaded successfully.")
else:
    print(f"❌ Folder not found: {folder_path}")
    sys.exit(1)

# Now we can import from the virtual module name
from tradingview_webhook_bot.core.orchestrator import Orchestrator
from dotenv import load_dotenv

load_dotenv()
bot = Orchestrator()

print(f"🔍 Checking file: {bot.consumer.queue_path}")
print(f"📍 Current Offset: {bot.consumer._read_offset()}")

def dummy_handler(data):
    print(f"🎯 SUCCESS! Signal Found: {data.get('signal_id')}")
    return True

stats = bot.consumer.poll(handler=dummy_handler, batch_size=1)
print(f"📊 Poll Result: {stats}")
