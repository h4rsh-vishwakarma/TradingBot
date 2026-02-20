from binance.exceptions import BinanceAPIException
from .logging_config import logger

def generate_deterministic_id(signal_id, venue="binance", leg="main", attempt=1):
    """
    Subtask 4.1: Implementation of the naming convention.
    Format: "{signal_id}:{venue}:{leg}:{attempt}"
    Note: Binance has a 36-character limit for client IDs.
    """
    # Using a shorter format to stay within Binance limits if signal_id is long
    short_id = signal_id.split('-')[0] if '-' in signal_id else signal_id[:10]
    return f"{short_id}_{venue}_{leg}_{attempt}"

def validate_order(symbol, quantity, price, order_type):
    """Pre-execution validation"""
    if quantity <= 0:
        return False, "Quantity must be greater than 0"
    
    if symbol.upper() == "BTCUSDT":
        estimated_price = price if price else 95000 
        if (quantity * estimated_price) < 100:
            return False, f"Notional value too low! (Current: ${quantity * estimated_price:.2f}, Min: ~$100)"
            
    return True, ""

def place_order(client, symbol, side, order_type, quantity, price=None, signal_id=None):
    """
    Subtask 4.2: Support idempotent handling of client_order_id.
    """
    try:
        params = {
            'symbol': symbol.upper(),
            'side': side.upper(),
            'type': order_type.upper(),
            'quantity': quantity,
        }

        # Inject Deterministic ID if provided
        if signal_id:
            params['newClientOrderId'] = generate_deterministic_id(signal_id)

        if order_type.upper() == 'LIMIT':
            if not price:
                raise ValueError("Price is required for LIMIT orders")
            params['price'] = price
            params['timeInForce'] = 'GTC'

        logger.info(f"Sending Order: {params}")
        
        response = client.futures_create_order(**params)
        
        logger.info(f"Order Successful! ID: {response.get('orderId')}")
        return response

    except BinanceAPIException as e:
        # Idempotency Check: If Binance says the ID was already used, it means 
        # the order actually went through during a previous failed network attempt.
        if "Duplicate orderSent" in str(e) or e.code == -2010:
            logger.warning(f"Idempotency Triggered: Order with signal_id {signal_id} already exists on Binance.")
            # Fetch the existing order to return success instead of failure
            return client.futures_get_order(symbol=symbol, origClientOrderId=params['newClientOrderId'])
        
        logger.error(f"Binance API Error: {e.message}")
        return None
    except Exception as e:
        logger.error(f"Unexpected Error: {e}")
        return None