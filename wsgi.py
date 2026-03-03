import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# 1. Project Root ki absolute path nikaalein
BASE_DIR = Path(__file__).resolve().parent
ROOT_STR = str(BASE_DIR)

# 2. Path Injection (Bulletproof Fix):
# Hum sys.path ko puri tarah reconstruct kar rahe hain taaki 
# Project Root (index 0) par rahe aur venv ke paths interfere na karein.
sys.path = [ROOT_STR, os.path.join(ROOT_STR, "tradingview_webhook_bot")] + [
    p for p in sys.path if p not in [ROOT_STR, os.path.join(ROOT_STR, "tradingview_webhook_bot")]
]

# 3. Environment variables load karein
load_dotenv(os.path.join(ROOT_STR, ".env"))

try:
    # Diagnostic Info: Senior-level logging for startup issues
    print(f"--- Gunicorn Startup Diagnostic ---")
    print(f"ROOT_DIR: {ROOT_STR}")
    print(f"SYS.PATH[0]: {sys.path[0]}")
    
    # Sabse pehle 'schemas' ko as a package verify karein
    import schemas.models
    print("✅ Schemas package verified.")

    # Phir main app load karein bina sub-folder prefix ke
    from tradingview_webhook_server import create_app
    app = create_app()
    print("✅ Webhook Server module loaded correctly.")

except ImportError as e:
    # Day 4 Requirement: Error logging for diagnostic purposes
    print(f"❌ Critical Import Error: {e}")
    print(f"Check if {ROOT_STR}/schemas/__init__.py exists!")
    sys.exit(1)
except Exception as e:
    print(f"❌ Unexpected Error during startup: {e}")
    sys.exit(1)

# Gunicorn entries ke liye 'app' object globally available hai
if __name__ == "__main__":
    # Manual testing mode (Day 5 Dry-run check)
    port = int(os.getenv("PORT", 5000))
    print(f"🚀 Manual Startup on http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port)
