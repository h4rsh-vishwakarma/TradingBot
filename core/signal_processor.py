import time
import logging
from storage.jsonl_consumer import consume_queue
from bot.orders import place_order  
from bot.client import get_client    
from core.event_logger import log_event # Added for T5.1

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SignalProcessor")

# 1. Initialize the connection once at the start
binance_client = get_client()

def execute_trade_from_signal(signal):
    sig_id = signal.get("signal_id")
    try:
        # --- [T5.1] Event: Signal Received ---
        log_event("signal_received", sig_id, signal.get("payload")) #
        
        payload = signal.get("payload", {})
        symbol = payload.get("symbol", "BTCUSDT")
        side = payload.get("side", "BUY").upper()
        order_type = payload.get("type", "MARKET").upper()
        quantity = payload.get("quantity", 0.002)
        price = payload.get("price")

        logger.info(f"Processing Signal {sig_id}: {side} {quantity} {symbol}")

        # --- [T5.1] Event: Order Submitted ---
        log_event("order_submitted", sig_id, {"symbol": symbol, "side": side, "qty": quantity}) #

        # 2. Execute trade with Deterministic ID support
        result = place_order(
            client=binance_client, 
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            signal_id=sig_id # Passes the ID for T4 idempotency
        )
        
        if result:
            # --- [T5.1] Event: Order Acknowledged ---
            log_event("order_ack", sig_id, {"orderId": result.get("orderId")}) #
            logger.info(f"Trade Executed Successfully: {result.get('orderId')}")
        else:
            raise Exception("Trade failed - check bot.log for API errors")

    except Exception as e:
        # --- [T5.1] Event: Trade Failed ---
        log_event("trade_fail", sig_id, {"error": str(e)}) #
        logger.error(f"Trade Execution Failed: {e}")
        raise e

def run_processor():
    logger.info("Bot is active and listening for signals...")
    while True:
        consume_queue(execute_trade_from_signal)
        time.sleep(1)

if __name__ == "__main__":
    run_processor()