import re
from datetime import datetime, timedelta

def validate_symbol(symbol):
    """Validate symbol format (e.g., BTCUSDT, SOLUSDT)"""
    pattern = r'^[A-Z]{2,10}USDT?$'
    return bool(re.match(pattern, symbol))

def validate_timeframe(timeframe):
    """Validate timeframe format (e.g., 15m, 1h, 4h, 1W, 1M)"""
    pattern = r'^\d+[smhdWM]$'
    return bool(re.match(pattern, timeframe))

def validate_price(price, current_price, max_deviation_pct=5.0):
    """Validate if signal price is within reasonable range of current price"""
    try:
        price = float(price)
        current_price = float(current_price)
        
        if price <= 0 or current_price <= 0:
            return False
        
        deviation = abs(price - current_price) / current_price * 100
        return deviation <= max_deviation_pct
    except (ValueError, TypeError):
        return False

def format_price(price, decimals=2):
    """Format price to specified decimals"""
    try:
        return round(float(price), decimals)
    except (ValueError, TypeError):
        return 0.0

def is_signal_expired(timestamp, expiry_seconds=300):
    """Check if signal is expired"""
    try:
        if isinstance(timestamp, str):
            signal_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        else:
            signal_time = timestamp
        
        age = (datetime.utcnow() - signal_time.replace(tzinfo=None)).total_seconds()
        return age > expiry_seconds
    except Exception:
        return True

def calculate_position_size(balance, size_type, size_value, leverage=1):
    """Calculate position size based on configuration"""
    try:
        balance = float(balance)
        size_value = float(size_value)
        leverage = float(leverage)
        
        if size_type == 'percentage':
            position_size = (balance * size_value / 100) * leverage
        elif size_type == 'fixed_usd':
            position_size = size_value
        else:
            position_size = balance * 0.02 * leverage  # Default 2%
        
        return position_size
    except Exception:
        return 0.0

def generate_signal_id(strategy, symbol):
    """Generate unique signal ID"""
    timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    return f"{strategy}_{symbol}_{timestamp}"
