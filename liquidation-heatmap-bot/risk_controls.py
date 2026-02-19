"""
Risk Controls Module
PRD Section 16: Risk Controls

Implements:
- Max notional per symbol/venue
- Max leverage limits
- Daily loss auto-pause
- Reject spike monitoring
- Safe mode toggle
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RiskLimits:
    """Risk control configuration"""
    max_notional_per_symbol: float = 10000.0  # $10k per symbol
    max_notional_per_venue: float = 25000.0  # $25k per venue
    max_leverage: float = 10.0
    daily_loss_cap_pct: float = 0.02  # 2% of start-of-day equity
    reject_rate_threshold: float = 0.5  # 50%
    api_error_threshold: int = 10
    safe_mode: bool = False


class RiskController:
    """
    Enforces risk limits and controls trading behavior.
    
    Features:
    - Position size limits by symbol and venue
    - Leverage limits
    - Daily loss monitoring and auto-pause
    - Reject spike detection
    - Safe mode (manual pause)
    """
    
    def __init__(self, limits: Optional[RiskLimits] = None, alert_router=None):
        self.limits = limits or RiskLimits()
        self.alert_router = alert_router
        
        # Daily tracking
        self.start_of_day_equity: Optional[float] = None
        self.daily_pnl: float = 0.0
        self.day_start: Optional[datetime] = None
        
        # Metrics tracking
        self.total_orders_today: int = 0
        self.rejected_orders_today: int = 0
        self.api_errors_today: int = 0
        
        # Position tracking
        self.notional_by_symbol: Dict[str, float] = {}
        self.notional_by_venue: Dict[str, float] = {}
    
    def check_can_trade(self, reason: str = "") -> tuple[bool, Optional[str]]:
        """
        Check if trading is allowed.
        
        Returns:
            (can_trade, reason_if_blocked)
        """
        if self.limits.safe_mode:
            return False, "SAFE_MODE_ACTIVE"
        
        # Check daily loss cap
        if self.start_of_day_equity and self.daily_pnl < 0:
            loss_pct = abs(self.daily_pnl) / self.start_of_day_equity
            if loss_pct >= self.limits.daily_loss_cap_pct:
                self._activate_safe_mode(f"Daily loss cap hit: {loss_pct:.2%}")
                return False, f"DAILY_LOSS_CAP ({loss_pct:.2%})"
        
        # Check reject rate
        if self.total_orders_today >= 5:
            reject_rate = self.rejected_orders_today / self.total_orders_today
            if reject_rate > self.limits.reject_rate_threshold:
                self._activate_safe_mode(f"High reject rate: {reject_rate:.1%}")
                return False, f"REJECT_SPIKE ({reject_rate:.1%})"
        
        # Check API errors
        if self.api_errors_today >= self.limits.api_error_threshold:
            self._activate_safe_mode(f"API error threshold: {self.api_errors_today}")
            return False, f"API_ERRORS ({self.api_errors_today})"
        
        return True, None
    
    def check_position_size(self, symbol: str, venue: str, notional: float) -> tuple[bool, Optional[str]]:
        """
        Check if position size is within limits.
        
        Args:
            symbol: Trading symbol
            venue: Exchange venue
            notional: Position notional value in USD
        
        Returns:
            (allowed, reason_if_blocked)
        """
        # Check symbol limit
        current_symbol_notional = self.notional_by_symbol.get(symbol, 0.0)
        if current_symbol_notional + notional > self.limits.max_notional_per_symbol:
            logger.warning(f"Symbol notional limit exceeded: {symbol} ${current_symbol_notional + notional:.2f} > ${self.limits.max_notional_per_symbol:.2f}")
            return False, f"SYMBOL_LIMIT ({symbol})"
        
        # Check venue limit
        current_venue_notional = self.notional_by_venue.get(venue, 0.0)
        if current_venue_notional + notional > self.limits.max_notional_per_venue:
            logger.warning(f"Venue notional limit exceeded: {venue} ${current_venue_notional + notional:.2f} > ${self.limits.max_notional_per_venue:.2f}")
            return False, f"VENUE_LIMIT ({venue})"
        
        return True, None
    
    def check_leverage(self, leverage: float) -> tuple[bool, Optional[str]]:
        """
        Check if leverage is within limits.
        
        Args:
            leverage: Requested leverage
        
        Returns:
            (allowed, reason_if_blocked)
        """
        if leverage > self.limits.max_leverage:
            logger.warning(f"Leverage limit exceeded: {leverage}x > {self.limits.max_leverage}x")
            return False, f"LEVERAGE_LIMIT ({leverage}x > {self.limits.max_leverage}x)"
        
        return True, None
    
    def update_position(self, symbol: str, venue: str, notional_delta: float) -> None:
        """Update position tracking after trade"""
        self.notional_by_symbol[symbol] = self.notional_by_symbol.get(symbol, 0.0) + notional_delta
        self.notional_by_venue[venue] = self.notional_by_venue.get(venue, 0.0) + notional_delta
        
        # Clean up closed positions
        if abs(self.notional_by_symbol[symbol]) < 1.0:
            self.notional_by_symbol.pop(symbol, None)
        if abs(self.notional_by_venue[venue]) < 1.0:
            self.notional_by_venue.pop(venue, None)
    
    def record_order_placed(self) -> None:
        """Record order placement"""
        self.total_orders_today += 1
    
    def record_order_rejected(self, reason: str) -> None:
        """Record order rejection"""
        self.rejected_orders_today += 1
        logger.warning(f"Order rejected: {reason} (Total: {self.rejected_orders_today}/{self.total_orders_today})")
    
    def record_api_error(self, error: str) -> None:
        """Record API error"""
        self.api_errors_today += 1
        logger.error(f"API error: {error} (Total: {self.api_errors_today})")
    
    def update_daily_pnl(self, realized_pnl: float) -> None:
        """Update daily PnL"""
        self.daily_pnl += realized_pnl
        
        # Check if we need to pause
        if self.start_of_day_equity:
            loss_pct = abs(min(0, self.daily_pnl)) / self.start_of_day_equity
            if loss_pct >= self.limits.daily_loss_cap_pct:
                self._activate_safe_mode(f"Daily loss cap: {loss_pct:.2%}")
                
                if self.alert_router:
                    self.alert_router.send(
                        severity="CRITICAL",
                        title="🛑 Daily Loss Cap Hit",
                        body=f"Daily PnL: ${self.daily_pnl:.2f} ({loss_pct:.2%})",
                        daily_pnl=self.daily_pnl,
                        loss_pct=loss_pct,
                        start_of_day_equity=self.start_of_day_equity
                    )
    
    def reset_daily_counters(self, current_equity: float) -> None:
        """Reset daily counters (call at start of trading day)"""
        self.start_of_day_equity = current_equity
        self.daily_pnl = 0.0
        self.day_start = datetime.utcnow()
        self.total_orders_today = 0
        self.rejected_orders_today = 0
        self.api_errors_today = 0
        logger.info(f"Daily counters reset. Start-of-day equity: ${current_equity:.2f}")
    
    def activate_safe_mode(self, reason: str) -> None:
        """Manually activate safe mode"""
        self._activate_safe_mode(reason)
    
    def _activate_safe_mode(self, reason: str) -> None:
        """Internal: Activate safe mode and alert"""
        if not self.limits.safe_mode:
            self.limits.safe_mode = True
            logger.critical(f"🛑 SAFE MODE ACTIVATED: {reason}")
            
            if self.alert_router:
                self.alert_router.send(
                    severity="CRITICAL",
                    title="🛑 SAFE MODE ACTIVATED",
                    body=f"Trading paused: {reason}",
                    reason=reason,
                    timestamp=datetime.utcnow().isoformat()
                )
    
    def deactivate_safe_mode(self, authorized_by: str) -> None:
        """Manually deactivate safe mode (requires authorization)"""
        if self.limits.safe_mode:
            self.limits.safe_mode = False
            logger.warning(f"✅ SAFE MODE DEACTIVATED by {authorized_by}")
            
            if self.alert_router:
                self.alert_router.send(
                    severity="WARNING",
                    title="✅ Safe Mode Deactivated",
                    body=f"Trading resumed by {authorized_by}",
                    authorized_by=authorized_by,
                    timestamp=datetime.utcnow().isoformat()
                )
    
    def get_status(self) -> Dict:
        """Get current risk control status"""
        can_trade, block_reason = self.check_can_trade()
        
        loss_pct = 0.0
        if self.start_of_day_equity and self.daily_pnl < 0:
            loss_pct = abs(self.daily_pnl) / self.start_of_day_equity
        
        reject_rate = 0.0
        if self.total_orders_today > 0:
            reject_rate = self.rejected_orders_today / self.total_orders_today
        
        return {
            "can_trade": can_trade,
            "block_reason": block_reason,
            "safe_mode": self.limits.safe_mode,
            "daily_pnl": self.daily_pnl,
            "daily_loss_pct": loss_pct,
            "daily_loss_cap": self.limits.daily_loss_cap_pct,
            "orders_today": self.total_orders_today,
            "rejected_today": self.rejected_orders_today,
            "reject_rate": reject_rate,
            "api_errors_today": self.api_errors_today,
            "notional_by_symbol": self.notional_by_symbol.copy(),
            "notional_by_venue": self.notional_by_venue.copy()
        }
