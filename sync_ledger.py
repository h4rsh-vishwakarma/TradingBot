import os
import json
import logging
from pathlib import Path
from dotenv import load_dotenv
from binance.client import Client

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load credentials
load_dotenv()
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
LEDGER_PATH = Path("storage/ledger_state.json")

def fetch_live_positions():
    """Fetch all open futures positions from Binance Testnet/Mainnet."""
    try:
        # Use testnet=True for your current setup
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
                    "realized_pnl": float(pos.get('unrealizedProfit', 0)) # Using current floating PnL
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

    # Backup old ledger just in case
    if LEDGER_PATH.exists():
        os.rename(LEDGER_PATH, f"{LEDGER_PATH}.bak")

    # Write fresh data
    with open(LEDGER_PATH, 'w') as f:
        json.dump(live_data, f, indent=4)
    
    logger.info(f"✅ Sync Complete. {len(live_data)} positions recorded.")
    for sym, data in live_data.items():
        logger.info(f"📍 {sym}: {data['quantity']} @ {data['avg_price']}")

if __name__ == "__main__":
    sync()
