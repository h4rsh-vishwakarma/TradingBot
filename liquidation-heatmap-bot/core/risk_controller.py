"""
Advanced risk controls for trading bot.
Monitors API errors, enforces leverage limits, and tracks notional exposure.
"""

import time
from collections import deque
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)


class RiskController:
    """Advanced risk controls beyond basic circuit breaker."""
    
    def __init__(self, config: dict):
        """
        Initialize risk controller.
        
        Args:
            config: Risk control configuration
        """
        # Leverage limits
        self.max_leverage = config.get('max_leverage', 1)
        self.current_leverage = 1  # Start at 1x
        
        # Notional limits per symbol
        self.max_notional_per_symbol = config.get('max_notional_per_symbol', 1000.0)
        self.symbol_notional = {}  # Track current notional by symbol
        
        # API error tracking
        self.api_error_window_seconds = config.get('api_error_window_seconds', 300)  # 5 min
        self.api_error_threshold = config.get('api_error_threshold', 10)
        self.api_errors = deque(maxlen=100)  # Keep last 100 errors
        
        # Safe mode flag
        self.safe_mode_active = False
        self.safe_mode_reason = None
        
        logger.info(f"🛡️ Advanced risk controls initialized:")
        logger.info(f"   Max leverage: {self.max_leverage}x")
        logger.info(f"   Max notional per symbol: ${self.max_notional_per_symbol:.2f}")
        logger.info(f"   API error threshold: {self.api_error_threshold} in {self.api_error_window_seconds}s")
    
    def validate_leverage(self, requested_leverage: int) -> bool:
        """
        Validate if requested leverage is allowed.
        
        Args:
            requested_leverage: Leverage level to validate
        
        Returns:
            True if allowed, False if exceeds limit
        """
        if requested_leverage > self.max_leverage:
            logger.warning(
                f"⚠️ Leverage rejected: {requested_leverage}x exceeds max {self.max_leverage}x"
            )
            return False
        return True
    
    def check_symbol_notional(self, symbol: str, additional_notional: float, 
                             balance: float) -> bool:
        """
        Check if adding position would exceed symbol notional limit.
        
        Args:
            symbol: Trading symbol (e.g., 'BTCUSDT')
            additional_notional: USD value of new position
            balance: Current account balance
        
        Returns:
            True if within limits, False if would exceed
        """
        current_notional = self.symbol_notional.get(symbol, 0.0)
        new_total = current_notional + additional_notional
        
        # Calculate as percentage of balance
        notional_pct = (new_total / balance) * 100 if balance > 0 else 0
        
        if new_total > self.max_notional_per_symbol:
            logger.warning(
                f"⚠️ Symbol notional limit exceeded: {symbol} "
                f"${new_total:.2f} > ${self.max_notional_per_symbol:.2f} "
                f"({notional_pct:.1f}% of balance)"
            )
            return False
        
        logger.debug(
            f"✅ Notional OK: {symbol} ${new_total:.2f} "
            f"({notional_pct:.1f}% of balance)"
        )
        return True
    
    def update_symbol_notional(self, symbol: str, notional_change: float):
        """
        Update tracked notional for a symbol.
        
        Args:
            symbol: Trading symbol
            notional_change: Change in notional (+ for open, - for close)
        """
        current = self.symbol_notional.get(symbol, 0.0)
        new_value = max(0, current + notional_change)  # Never negative
        self.symbol_notional[symbol] = new_value
        
        logger.debug(f"📊 {symbol} notional: ${current:.2f} → ${new_value:.2f}")
    
    def record_api_error(self, error_type: str, details: str = ""):
        """
        Record an API error for monitoring.
        
        Args:
            error_type: Type of error (e.g., 'timeout', 'rate_limit', 'server_error')
            details: Additional error details
        """
        error_record = {
            'timestamp': time.time(),
            'type': error_type,
            'details': details
        }
        self.api_errors.append(error_record)
        
        logger.warning(f"⚠️ API Error: {error_type} - {details}")
        
        # Check if error rate is too high
        self._check_api_error_rate()
    
    def _check_api_error_rate(self):
        """Check if API error rate exceeds threshold and trigger safe mode."""
        if not self.api_errors:
            return
        
        current_time = time.time()
        cutoff_time = current_time - self.api_error_window_seconds
        
        # Count recent errors
        recent_errors = sum(1 for err in self.api_errors if err['timestamp'] > cutoff_time)
        
        if recent_errors >= self.api_error_threshold:
            if not self.safe_mode_active:
                self.activate_safe_mode(
                    f"API error rate too high: {recent_errors} errors in "
                    f"{self.api_error_window_seconds}s"
                )
            return True
        
        return False
    
    def get_api_error_stats(self) -> Dict:
        """Get API error statistics."""
        if not self.api_errors:
            return {
                'total_errors': 0,
                'recent_errors': 0,
                'error_types': {}
            }
        
        current_time = time.time()
        cutoff_time = current_time - self.api_error_window_seconds
        
        recent_errors = [err for err in self.api_errors if err['timestamp'] > cutoff_time]
        
        # Count by type
        error_types = {}
        for err in recent_errors:
            err_type = err['type']
            error_types[err_type] = error_types.get(err_type, 0) + 1
        
        return {
            'total_errors': len(self.api_errors),
            'recent_errors': len(recent_errors),
            'error_types': error_types,
            'window_seconds': self.api_error_window_seconds
        }
    
    def activate_safe_mode(self, reason: str):
        """
        Activate safe mode - only allow position closures, no new entries.
        
        Args:
            reason: Reason for activating safe mode
        """
        self.safe_mode_active = True
        self.safe_mode_reason = reason
        logger.critical(f"🚨 SAFE MODE ACTIVATED: {reason}")
    
    def deactivate_safe_mode(self):
        """Deactivate safe mode and resume normal trading."""
        if self.safe_mode_active:
            logger.info(f"✅ Safe mode deactivated")
            self.safe_mode_active = False
            self.safe_mode_reason = None
    
    def can_open_new_position(self) -> tuple[bool, Optional[str]]:
        """
        Check if new positions can be opened.
        
        Returns:
            (allowed: bool, reason: str if not allowed)
        """
        if self.safe_mode_active:
            return False, f"Safe mode: {self.safe_mode_reason}"
        
        return True, None
    
    def get_status(self) -> Dict:
        """Get risk controller status."""
        api_stats = self.get_api_error_stats()
        
        return {
            'safe_mode': self.safe_mode_active,
            'safe_mode_reason': self.safe_mode_reason,
            'current_leverage': self.current_leverage,
            'max_leverage': self.max_leverage,
            'symbol_notional': dict(self.symbol_notional),
            'max_notional_per_symbol': self.max_notional_per_symbol,
            'api_errors': api_stats
        }
    
    def reset_api_errors(self):
        """Reset API error counter (use after resolving issues)."""
        self.api_errors.clear()
        logger.info("🔄 API error counter reset")


# Test function
def test_risk_controller():
    """Test the risk controller."""
    config = {
        'max_leverage': 1,
        'max_notional_per_symbol': 500.0,
        'api_error_window_seconds': 60,
        'api_error_threshold': 5
    }
    
    rc = RiskController(config)
    
    # Test 1: Leverage validation
    assert rc.validate_leverage(1), "1x leverage should be allowed"
    assert not rc.validate_leverage(2), "2x leverage should be rejected"
    
    # Test 2: Notional limits
    assert rc.check_symbol_notional('BTCUSDT', 300, 1000), "300 notional should be OK"
    rc.update_symbol_notional('BTCUSDT', 300)
    assert not rc.check_symbol_notional('BTCUSDT', 300, 1000), "600 notional should exceed limit"
    
    # Test 3: API errors
    for i in range(4):
        rc.record_api_error('timeout', f'Error {i}')
    assert not rc.safe_mode_active, "Safe mode should not trigger yet"
    
    rc.record_api_error('timeout', 'Error 5')
    assert rc.safe_mode_active, "Safe mode should activate after 5 errors"
    
    # Test 4: Safe mode blocks new positions
    allowed, reason = rc.can_open_new_position()
    assert not allowed, "New positions should be blocked in safe mode"
    assert 'API error' in reason, "Reason should mention API errors"
    
    # Test 5: Deactivate safe mode
    rc.deactivate_safe_mode()
    allowed, reason = rc.can_open_new_position()
    assert allowed, "New positions should be allowed after deactivating safe mode"
    
    print("✅ All risk controller tests passed!")


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    test_risk_controller()
