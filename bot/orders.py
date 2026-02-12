from binance.exceptions import BinanceAPIException
from .logging_config import logger


def validate_order(symbol, quantity, price, order_type):
    """Bonus: Pre-execution validation"""
    if quantity <= 0:
        return False, "Quantity must be greater than 0"
    
    # Simple check for BTCUSDT notional limit (~100 USDT)
    if symbol.upper() == "BTCUSDT":
        estimated_price = price if price else 95000 # Fallback for Market
        if (quantity * estimated_price) < 100:
            return False, f"Notional value too low! (Current: ${quantity * estimated_price:.2f}, Min: ~$100)"
            
    return True, ""



def place_futures_order(client, symbol, side, order_type, quantity, price=None):
    try:
        params = {
            'symbol': symbol.upper(),
            'side': side.upper(),
            'type': order_type.upper(),
            'quantity': quantity,
        }

        # Limit orders require a price
        if order_type.upper() == 'LIMIT':
            if not price:
                raise ValueError("Price is required for LIMIT orders")
            params['price'] = price
            params['timeInForce'] = 'GTC'  # Good Till Cancelled (Standard)

        logger.info(f"Sending Order: {params}")
        
        # Calling Binance Futures API
        response = client.futures_create_order(**params)
        
        logger.info(f"Order Successful! ID: {response.get('orderId')}")
        return response

    except BinanceAPIException as e:
        logger.error(f"Binance API Error: {e.message}")
        return None
    except Exception as e:
        logger.error(f"Unexpected Error: {e}")
        return None