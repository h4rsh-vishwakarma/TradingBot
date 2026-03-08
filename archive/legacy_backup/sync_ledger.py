import os
import json
import logging
from pathlib import Path
from dotenv import load_dotenv
from binance.client import Client

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- PATH CONFIGURATION ---
# We use absolute paths so systemd can find files regardless of current directory
BASE_DIR = Path("/home/ubuntu/Multi-Strategy-Crypto-Trading-Systems")
ENV_PATH = BASE_DIR / "tradingview_webhook_bot" / ".env"
LEDGER_PATH = BASE_DIR / "storage/ledger_state.json"

# Explicitly load .env from the absolute path
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)
    logger.info(f"🔐 .env loaded successfully from {ENV_PATH}")
else:
    logger.error(f"❌ .env file NOT FOUND at {ENV_PATH}")

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

def fetch_live_positions():
    """Fetch all open futures positions from Binance Testnet."""
    try:
        if not API_KEY or not API_SECRET:
            raise ValueError("API_KEY or API_SECRET is missing in environment variables.")

        # Initialize client for Testnet
        client = Client(API_KEY, API_SECRET, testnet=True)
        account_info = client.futures_account()

        new_ledger = {}
        for pos in account_info.get('positions', []):
            qty = float(pos.get('positionAmt', 0))
            symbol = pos.get('symbol')

            # Only record active positions (non-zero)
            if qty != 0:
                new_ledger[symbol] = {
                    "symbol": symbol,
                    "quantity": qty,
                    "avg_price": float(pos.get('entryPrice', 0)),
                    "realized_pnl": float(pos.get('unrealizedProfit', 0))
                }
        return new_ledger
    except Exception as e:
        logger.error(f"❌ Failed to fetch Binance positions: {e}")
        return None

def sync():
    logger.info("🔄 Starting Ledger Sync with Binance...")
    live_data = fetch_live_positions()

    if live_data is None:
        logger.error("🛑 Sync aborted to prevent data loss.")
        return

    # Ensure storage directory exists
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Backup old ledger just in case
    if LEDGER_PATH.exists():
        backup_path = LEDGER_PATH.with_suffix(".json.bak")
        os.replace(LEDGER_PATH, backup_path)
        logger.info(f"📁 Backup created at {backup_path}")

    # Write fresh data
    with open(LEDGER_PATH, 'w') as f:
        json.dump(live_data, f, indent=4)

    logger.info(f"✅ Sync Complete. {len(live_data)} positions recorded.")
    for sym, data in live_data.items():
        logger.info(f"📍 {sym}: {data['quantity']} @ {data['avg_price']}")

if __name__ == "__main__":
    sync()

