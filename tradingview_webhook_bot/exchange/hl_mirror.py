import json, logging, os, time, requests, sys
from datetime import datetime, timezone
from pathlib import Path

# --- DYNAMIC PATH FIX ---
# Isse Python ko pata chalega ki storage/utils folders kahan hain
current_file = Path(__file__).resolve()
project_root = current_file.parents[2] # Ye 'tradingview_webhook_bot' root tak jayega
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from tradingview_webhook_bot.storage.jsonl_queue import AtomicJsonlQueue

# Paths setup
QUEUE_PATH = project_root / "tradingview_webhook_bot" / "storage" / "signals.jsonl"

logger = logging.getLogger("hl_mirror")
logging.basicConfig(level=logging.INFO)
queue = AtomicJsonlQueue(str(QUEUE_PATH))

# Config from Env
LEAD_INFO_URL = "https://api.hyperliquid.xyz/info"
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL_SECONDS", "5"))
# Env se traders list uthana
TRADER_RAW = os.getenv("TRADER_ADDRESSES", "")
TRADERS = [t.strip() for t in TRADER_RAW.split(",") if t.strip()]

last_fetch_time = {}

def fetch_fills(address):
    # Default lookback: last 1 minute if first time
    start_time = last_fetch_time.get(address, int(time.time() * 1000) - 60000)
    payload = {"type": "userFillsByTime", "user": address, "startTime": start_time}
    
    try:
        resp = requests.post(LEAD_INFO_URL, json=payload, timeout=10)
        if resp.status_code == 200:
            fills = resp.json()
            if isinstance(fills, list) and fills:
                max_t = max(int(f.get('time', 0)) for f in fills)
                last_fetch_time[address] = max_t + 1
                return fills
    except Exception as e:
        logger.error(f"Error fetching {address}: {e}")
    return []

def run_mirror():
    if not TRADERS:
        logger.error("❌ No TRADER_ADDRESSES found in environment variables!")
        return

    logger.info(f"🛰️ Mirror Bot Started | Monitoring {len(TRADERS)} traders")
    secret = os.getenv("WEBHOOK_SECRET")

    while True:
        for addr in TRADERS:
            fills = fetch_fills(addr)
            for fill in fills:
                # Convert Fill to Signal Format for Orchestrator
                signal = {
                    "signal_id": f"mirror_{fill.get('hash', time.time())}",
                    "exchange": "hyperliquid",
                    "secret": secret,
                    "payload": {
                        "strategy": "MIRROR_TRADE",
                        "symbol": fill['coin'],
                        "action": "BUY" if fill['side'] == 'B' else "SELL",
                        "price": float(fill['px']),
                        "quantity": float(fill['sz']),
                        "timeframe": "LIVE"
                    }
                }
                queue.enqueue(signal)
                logger.info(f"⚡ Mirror Signal Queued: {fill['coin']} {fill['side']} from {addr}")
        
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    run_mirror()
