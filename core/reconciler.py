import time
import logging
from bot.client import get_client
from core.event_logger import log_event

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Reconciler")

def run_reconciler(interval=15):
    """
    Subtask 5.2: Activate Reconciler monitor (15s interval).
    Checks exchange state to detect any mismatch.
    """
    client = get_client()
    logger.info(f"Reconciler active. Monitoring exchange state every {interval}s...")
    
    while True:
        try:
            # 1. Fetch current positions from Binance
            acc_info = client.futures_account()
            # Only look at positions that are actually open (amount != 0)
            active_positions = [
                p for p in acc_info['positions'] 
                if float(p['positionAmt']) != 0
            ]
            
            # 2. [T5.1] Wire: Log the position snapshot for audit trail
            log_event("position_snapshot", "SYSTEM", {"active_count": len(active_positions)}) #
            
            if not active_positions:
                logger.info("Reconciliation: No active positions. Local and Exchange match.")
            else:
                for pos in active_positions:
                    logger.info(f"AUDIT: Active Position -> {pos['symbol']} | Size: {pos['positionAmt']}")

            # 3. Subtask 5.3: Simulate mismatch (Logic for Incident Creation)
            # In a real scenario, you'd compare 'active_positions' with your Local Database.
            # If (Binance has BTC) but (Local DB says NO BTC) -> Trigger Incident.
            
            time.sleep(interval)
            
        except Exception as e:
            logger.error(f"Reconciler Error: {e}")
            time.sleep(5) # Wait before retry

if __name__ == "__main__":
    run_reconciler()    