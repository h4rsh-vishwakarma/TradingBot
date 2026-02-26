import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# 1. BASE_DIR determine karein (Project Root)
BASE_DIR = Path(__file__).resolve().parent

# 2. Sabse Pehle Root ko path mein sabse upar (index 0) rakhein
# Isse 'schemas' folder hamesha mil jayega
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# 3. Hyphenated folder ko path mein add karein
SUB_FOLDER = BASE_DIR / "tradingview-webhook-bot"
if str(SUB_FOLDER) not in sys.path:
    sys.path.insert(1, str(SUB_FOLDER))

load_dotenv()

try:
    # Yahan hum direct module import karenge bina 'tradingview-webhook-bot' prefix ke
    # Kyunki humne SUB_FOLDER ko path mein daal diya hai
    from tradingview_webhook_server import create_app
    print("✅ Webhook Server module loaded correctly.")
    
    import schemas.models
    print("✅ Schemas package verified.")
except ImportError as e:
    print(f"❌ Import Error: {e}")
    print("\n--- Diagnostic Info ---")
    print(f"ROOT: {BASE_DIR}")
    print(f"SYS.PATH TOP 3: {sys.path[:3]}")
    sys.exit(1)

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"🚀 Server starting on http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port)
