import sys
import os
import json
from pathlib import Path
from dotenv import load_dotenv

# 1. Project Root Setup
BASE_DIR = Path(__file__).resolve().parent
# Subfolder jahan main logic (core, storage) hai
SUB_APP_DIR = BASE_DIR / "tradingview_webhook_bot"

# Path injection - Dono paths zaroori hain
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(SUB_APP_DIR))

# 2. Load Environment (Production path)
load_dotenv("/etc/tradingbot/env_vars")

try:
    print(f"--- 🚀 Gunicorn Startup (Integrated Mode) ---")
    
    # 3. Precise Path Resolution based on your 'find' output
    config_path = BASE_DIR / "config" / "settings.json"
    signals_file = SUB_APP_DIR / "storage" / "signals.jsonl"

    print(f"✅ Root: {BASE_DIR}")
    print(f"✅ Config: {config_path}")
    print(f"✅ Queue: {signals_file}")

    if not config_path.exists():
        raise FileNotFoundError(f"Missing settings.json at {config_path}")

    with open(config_path, 'r') as f:
        config = json.load(f)

    # 4. Import WebhookServer (Ab SUB_APP_DIR path mein hai toh core mil jayega)
    from core.webhook_server import WebhookServer
    
    server_instance = WebhookServer(config, str(signals_file))
    app = server_instance.app 
    
    print("✅ Integrated Webhook Server loaded successfully!")

except Exception as e:
    print(f"❌ Startup Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
