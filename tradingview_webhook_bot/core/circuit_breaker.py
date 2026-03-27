"""
Circuit breaker for daily loss limits and trading safety controls.
Automatically pauses trading when loss thresholds are exceeded.
"""

import time
import json
from pathlib import Path
from typing import Optional, Dict
import logging

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Trading circuit breaker with daily loss limits and manual controls."""
    
    def __init__(self, state_file: str, config: dict):
        """
        Initialize circuit breaker.
        
        Args:
            state_file: Path to persistent state file
            config: Configuration dict with circuit breaker settings
        """
        self.state_file = Path(state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Configuration
        self.daily_loss_limit_pct = config.get('daily_loss_limit_pct', 2.0)
        self.max_consecutive_losses = config.get('max_consecutive_losses', 5)
        self.cooldown_minutes = config.get('cooldown_minutes', 60)
        self.cumulative_dd_limit_pct = config.get('cumulative_dd_limit_pct', 15.0)

        # Load or initialize state
        self._load_state()
    
    def _load_state(self):
        """Load circuit breaker state from file."""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                    
                self.is_tripped = state.get('is_tripped', False)
                self.trip_reason = state.get('trip_reason', None)
                self.trip_time = state.get('trip_time', None)
                self.manual_pause = state.get('manual_pause', False)
                self.daily_start_balance = state.get('daily_start_balance', None)
                self.daily_start_time = state.get('daily_start_time', None)
                self.consecutive_losses = state.get('consecutive_losses', 0)
                self.peak_equity = state.get('peak_equity', None)

                logger.info(f"📊 Loaded circuit breaker state: tripped={self.is_tripped}, peak_equity={self.peak_equity}")
                
            except Exception as e:
                logger.error(f"Failed to load circuit breaker state: {e}")
                self._init_state()
        else:
            self._init_state()
    
    def _init_state(self):
        """Initialize fresh state."""
        self.is_tripped = False
        self.trip_reason = None
        self.trip_time = None
        self.manual_pause = False
        self.daily_start_balance = None
        self.daily_start_time = None
        self.consecutive_losses = 0
        self.peak_equity = None
        self._save_state()
    
    def _save_state(self):
        """Save circuit breaker state to file."""
        try:
            state = {
                'is_tripped': self.is_tripped,
                'trip_reason': self.trip_reason,
                'trip_time': self.trip_time,
                'manual_pause': self.manual_pause,
                'daily_start_balance': self.daily_start_balance,
                'daily_start_time': self.daily_start_time,
                'consecutive_losses': self.consecutive_losses,
                'peak_equity': self.peak_equity,
                'last_updated': time.time()
            }
            
            # Atomic write
            temp_file = self.state_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(state, f, indent=2)
            temp_file.replace(self.state_file)
            
        except Exception as e:
            logger.error(f"Failed to save circuit breaker state: {e}")
    
    def check_daily_loss(self, current_balance: float) -> bool:
        """
        Check if daily loss limit is exceeded.
        
        Args:
            current_balance: Current account balance
        
        Returns:
            True if trading should be paused
        """
        current_time = time.time()
        
        # Reset daily tracking if it's a new day (24h passed)
        if (self.daily_start_time is None or 
            current_time - self.daily_start_time > 86400):
            self.daily_start_balance = current_balance
            self.daily_start_time = current_time
            self._save_state()
            logger.info(f"📅 New trading day started | Balance: ${current_balance:.2f}")
            return False
        
        # Calculate daily loss
        if self.daily_start_balance:
            daily_loss = self.daily_start_balance - current_balance
            daily_loss_pct = (daily_loss / self.daily_start_balance) * 100
            
            if daily_loss_pct >= self.daily_loss_limit_pct:
                self._trip(
                    f"Daily loss limit exceeded: {daily_loss_pct:.2f}% "
                    f"(${daily_loss:.2f})"
                )
                return True
        
        return False

    def check_cumulative_drawdown(self, current_balance: float) -> bool:
        """
        Check if cumulative drawdown from peak equity exceeds limit.
        Catches slow bleeds over days/weeks that daily reset misses.
        Persisted across restarts via peak_equity in state file.

        Returns:
            True if trading should be paused (DD limit exceeded)
        """
        if current_balance <= 0:
            return False

        # Track peak equity (high-water mark)
        if self.peak_equity is None or current_balance > self.peak_equity:
            self.peak_equity = current_balance
            self._save_state()

        # Calculate drawdown from peak
        dd_pct = ((self.peak_equity - current_balance) / self.peak_equity) * 100

        if dd_pct >= self.cumulative_dd_limit_pct:
            self._trip(
                f"Cumulative drawdown limit exceeded: {dd_pct:.2f}% from peak "
                f"(Peak: ${self.peak_equity:.2f}, Current: ${current_balance:.2f})"
            )
            return True

        return False

    def record_trade_result(self, is_win: bool):
        """
        Record trade result and check consecutive loss limit.
        
        Args:
            is_win: True if trade was profitable, False if loss
        """
        if is_win:
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
            
            if self.consecutive_losses >= self.max_consecutive_losses:
                self._trip(
                    f"Consecutive loss limit exceeded: {self.consecutive_losses} losses"
                )
        
        self._save_state()
    
    def should_allow_trade(self, current_balance: Optional[float] = None) -> bool:
        """
        Check if trading should be allowed.
        
        Args:
            current_balance: Current balance for daily loss check
        
        Returns:
            True if trading is allowed, False if paused
        """
        # Check manual pause
        if self.manual_pause:
            logger.debug("🛑 Trading paused manually")
            return False
        
        # Check if tripped
        if self.is_tripped:
            # Check if cooldown period has passed
            if self.trip_time and time.time() - self.trip_time > (self.cooldown_minutes * 60):
                logger.info(f"✅ Cooldown period ended, resetting circuit breaker")
                self.reset()
                return True
            else:
                logger.debug(f"🛑 Circuit breaker tripped: {self.trip_reason}")
                return False
        
        # Check daily loss if balance provided
        if current_balance is not None:
            if self.check_daily_loss(current_balance):
                return False
            if self.check_cumulative_drawdown(current_balance):
                return False

        return True
    
    def _trip(self, reason: str):
        """
        Trip the circuit breaker.
        
        Args:
            reason: Reason for tripping
        """
        if not self.is_tripped:
            self.is_tripped = True
            self.trip_reason = reason
            self.trip_time = time.time()
            self._save_state()
            logger.critical(f"🚨 CIRCUIT BREAKER TRIPPED: {reason}")
    
    def reset(self):
        """Manually reset the circuit breaker."""
        self.is_tripped = False
        self.trip_reason = None
        self.trip_time = None
        self.consecutive_losses = 0
        self._save_state()
        logger.info("✅ Circuit breaker reset")
    
    def pause(self, reason: str = "Manual pause"):
        """Manually pause trading."""
        self.manual_pause = True
        self._trip(reason)
        logger.warning(f"⏸️  Trading paused: {reason}")
    
    def resume(self):
        """Resume trading after manual pause."""
        self.manual_pause = False
        self.reset()
        logger.info("▶️  Trading resumed")
    
    def get_status(self) -> Dict:
        """Get circuit breaker status."""
        status = {
            'is_active': not self.should_allow_trade(),
            'is_tripped': self.is_tripped,
            'manual_pause': self.manual_pause,
            'trip_reason': self.trip_reason,
            'consecutive_losses': self.consecutive_losses,
            'daily_loss_limit_pct': self.daily_loss_limit_pct,
            'cumulative_dd_limit_pct': self.cumulative_dd_limit_pct,
            'peak_equity': self.peak_equity,
        }
        
        if self.daily_start_balance:
            status['daily_start_balance'] = self.daily_start_balance
            status['daily_start_time'] = self.daily_start_time
        
        if self.trip_time:
            elapsed = time.time() - self.trip_time
            remaining = max(0, (self.cooldown_minutes * 60) - elapsed)
            status['trip_time'] = self.trip_time
            status['cooldown_remaining_seconds'] = remaining
        
        return status


# Test function
def test_circuit_breaker():
    """Test the circuit breaker."""
    import tempfile
    import os
    
    with tempfile.NamedTemporaryFile(delete=False, suffix='.json', mode='w') as f:
        state_file = f.name
    
    try:
        config = {
            'daily_loss_limit_pct': 2.0,
            'max_consecutive_losses': 3,
            'cooldown_minutes': 1
        }
        
        cb = CircuitBreaker(state_file, config)
        
        # Test 1: Should allow trading initially
        assert cb.should_allow_trade(500.0), "Should allow trading initially"
        
        # Test 2: Small loss should be OK
        assert cb.should_allow_trade(495.0), "Small loss should be allowed"
        
        # Test 3: Large loss should trip
        assert not cb.should_allow_trade(489.0), "2.2% loss should trip breaker"
        
        # Test 4: Reset should allow trading
        cb.reset()
        assert cb.should_allow_trade(), "Should allow after reset"
        
        # Test 5: Consecutive losses
        cb.record_trade_result(False)  # Loss 1
        cb.record_trade_result(False)  # Loss 2
        assert cb.should_allow_trade(), "Should allow after 2 losses"
        
        cb.record_trade_result(False)  # Loss 3 - should trip
        assert not cb.should_allow_trade(), "Should trip after 3 consecutive losses"
        
        # Test 6: Win resets consecutive losses
        cb.reset()
        cb.record_trade_result(False)  # Loss
        cb.record_trade_result(True)   # Win - resets counter
        cb.record_trade_result(False)  # Loss
        assert cb.should_allow_trade(), "Win should reset consecutive loss counter"
        
        # Test 7: Manual pause
        cb.pause("Testing pause")
        assert not cb.should_allow_trade(), "Manual pause should block trading"
        
        cb.resume()
        assert cb.should_allow_trade(), "Resume should allow trading"
        
        print("✅ All circuit breaker tests passed!")
        
    finally:
        if os.path.exists(state_file):
            try:
                os.unlink(state_file)
            except (OSError, PermissionError) as e:
                logger.debug(f"Could not remove test file: {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    test_circuit_breaker()
