import time
import logging
import json
import os
from storage.jsonl_consumer import consume_queue
from bot.orders import place_order  
from bot.client import get_client    
from core.event_logger import log_event

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SignalProcessor")

# Path for Task 7.2 Heartbeat
HEARTBEAT_PATH = "state/bot_heartbeat.json"

# 1. Initialize the connection once at the start
binance_client = get_client()

def write_heartbeat(status="running"):
    """
    Subtask 7.2: Bot writes heartbeat file state/bot_heartbeat.json every 30s.
    """
    try:
        os.makedirs("state", exist_ok=True)
        heartbeat_data = {
            "last_heartbeat": time.time(),
            "status": status,
            "service": "signal_processor",
            "pid": os.getpid()
        }
        with open(HEARTBEAT_PATH, "w") as f:
            json.dump(heartbeat_data, f)
    except Exception as e:
        logger.error(f"Failed to write heartbeat: {e}")

def execute_trade_from_signal(signal):
    sig_id = signal.get("signal_id")
    try:
        # --- [T5.1] Event: Signal Received ---
        log_event("signal_received", sig_id, signal.get("payload"))
        
        payload = signal.get("payload", {})
        symbol = payload.get("symbol", "BTCUSDT")
        side = payload.get("side", "BUY").upper()
        order_type = payload.get("type", "MARKET").upper()
        quantity = payload.get("quantity", 0.002)
        price = payload.get("price")

        logger.info(f"Processing Signal {sig_id}: {side} {quantity} {symbol}")

        # --- [T5.1] Event: Order Submitted ---
        log_event("order_submitted", sig_id, {"symbol": symbol, "side": side, "qty": quantity})

        # 2. Execute trade with Deterministic ID support
        result = place_order(
            client=binance_client, 
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            signal_id=sig_id 
        )
        
        if result:
            # --- [T5.1] Event: Order Acknowledged ---
            log_event("order_ack", sig_id, {"orderId": result.get("orderId")})
            logger.info(f"Trade Executed Successfully: {result.get('orderId')}")
        else:
            raise Exception("Trade failed - check bot.log for API errors")

    except Exception as e:
        # --- [T5.1] Event: Trade Failed ---
        log_event("trade_fail", sig_id, {"error": str(e)})
        logger.error(f"Trade Execution Failed: {e}")
        raise e

def run_processor():
    logger.info("Bot is active and listening for signals...")
    
    last_heartbeat_time = 0
    heartbeat_interval = 30  # Requirement 7.2: every 30s
    
    while True:
        # Check if it's time to write the heartbeat
        current_time = time.time()
        if current_time - last_heartbeat_time > heartbeat_interval:
            write_heartbeat()
            last_heartbeat_time = current_time
            logger.debug("Heartbeat updated.")

        consume_queue(execute_trade_from_signal)
        time.sleep(1)

if __name__ == "__main__":
    run_processor()