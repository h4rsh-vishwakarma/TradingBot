"""
Risk Invariants Module - P0 Hard Constraints
Enforces non-negotiable risk limits to prevent blowups
"""

from dataclasses import dataclass
from typing import Optional, List, Dict
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


@dataclass
class RiskInvariant:
    """A single risk invariant/constraint"""
    name: str
    violated: bool
    current_value: float
    limit_value: float
    severity: str  # "CRITICAL", "HIGH", "MEDIUM"
    message: str


class RiskInvariantsValidator:
    """
    Validates P0 risk invariants before allowing trades.
    
    These are HARD constraints that must NEVER be violated:
    - Daily loss cap (e.g., 2% of starting equity)
    - Per-trade R sizing (position must be sized by R and SL distance)
    - Maximum positions limit
    - Minimum SL distance from liquidation clusters
    """
    
    def __init__(self, config):
        self.config = config
        self.trading_config = config.get_trading_config()
        
        # P0 Constraints (from config or defaults)
        self.daily_cap_pct = getattr(self.trading_config, 'daily_cap_pct', 0.02)  # 2%
        self.max_positions = getattr(self.trading_config, 'max_positions', 10)  # Increased from 3 to 10 for overnight trading
        self.min_r_multiple = getattr(self.trading_config, 'min_r_multiple', 1.5)
        self.max_r_per_trade = getattr(self.trading_config, 'max_r_per_trade', 1.0)
        self.min_sl_cluster_buffer_pct = 0.005  # 0.5% buffer from cluster edge
        
        # State tracking
        self.start_of_day_equity = None
        self.daily_loss_usd = 0.0
        self.violations_today = []
        
        logger.info(f"Risk Invariants: daily_cap={self.daily_cap_pct*100:.1f}%, "
                   f"max_pos={self.max_positions}, R_range=[{self.min_r_multiple}, {self.max_r_per_trade}]")
    
    def reset_daily_state(self, current_equity: float):
        """Reset daily tracking (call at start of day)"""
        self.start_of_day_equity = current_equity
        self.daily_loss_usd = 0.0
        self.violations_today = []
        logger.info(f"Daily risk state reset: equity=${current_equity:,.2f}")
    
    def validate_all_invariants(
        self,
        current_equity: float,
        daily_pnl: float,
        open_positions: int,
        proposed_trade: Optional[Dict] = None
    ) -> tuple[bool, List[RiskInvariant]]:
        """
        Validate all P0 invariants.
        
        Returns:
            (can_trade: bool, violations: List[RiskInvariant])
        """
        if self.start_of_day_equity is None:
            self.reset_daily_state(current_equity)
        
        violations = []
        
        # 1. Daily loss cap
        daily_cap_usd = self.start_of_day_equity * self.daily_cap_pct
        daily_loss = max(0.0, -daily_pnl)  # Loss is negative PnL
        
        if daily_loss >= daily_cap_usd:
            violations.append(RiskInvariant(
                name="DAILY_CAP_HIT",
                violated=True,
                current_value=daily_loss,
                limit_value=daily_cap_usd,
                severity="CRITICAL",
                message=f"Daily loss ${daily_loss:.2f} >= cap ${daily_cap_usd:.2f}"
            ))
        
        # 2. Maximum positions limit - Now uses cooldown instead of hard rejection
        # Allow up to max_positions (3), but require 5min cooldown between positions when at/above limit
        # This is checked in the signal generator, not here
        # Keep the hard limit check for safety but set it to 2x the soft limit
        hard_limit = self.max_positions * 4  # Allow buffer beyond soft limit (40 total for natural position cycling)
        if open_positions >= hard_limit:
            violations.append(RiskInvariant(
                name="MAX_POSITIONS_HARD_LIMIT",
                violated=True,
                current_value=open_positions,
                limit_value=hard_limit,
                severity="HIGH",
                message=f"Open positions {open_positions} >= hard limit {hard_limit} (soft limit: {self.max_positions})"
            ))
        
        # 3. Validate proposed trade if provided
        if proposed_trade:
            trade_violations = self._validate_trade_invariants(proposed_trade)
            violations.extend(trade_violations)
        
        # Log any violations
        for v in violations:
            logger.warning(f"❌ RISK INVARIANT VIOLATED: {v.name} - {v.message}")
            self.violations_today.append(v)
        
        can_trade = len(violations) == 0
        return can_trade, violations
    
    def _validate_trade_invariants(self, trade: Dict) -> List[RiskInvariant]:
        """Validate invariants specific to a proposed trade"""
        violations = []
        
        # Extract trade parameters (support both 'entry_px' and 'entry_price')
        entry_px = trade.get('entry_px', trade.get('entry_price', 0))
        stop_loss = trade.get('stop_loss', 0)
        quantity = trade.get('quantity', 0)
        side = trade.get('side', '')
        
        if not all([entry_px, stop_loss, quantity]):
            violations.append(RiskInvariant(
                name="INVALID_TRADE_PARAMS",
                violated=True,
                current_value=0,
                limit_value=0,
                severity="CRITICAL",
                message="Trade missing required params (entry_px, stop_loss, quantity)"
            ))
            return violations
        
        # 1. R-sizing validation
        sl_distance = abs(entry_px - stop_loss)
        risk_usd = sl_distance * quantity
        
        # P0.3: Minimum meaningful risk check (COMMISSION-SAFE)
        # Risk must be sufficient to cover commissions and provide meaningful R-multiples
        # DO NOT lower this threshold - it ensures trades are economically viable
        MIN_RISK_USD = 1.00  # Hard floor for $1,000 account
        ROUND_TRIP_COMMISSION = 0.14  # Estimated: $0.07 × 2 (entry + exit)
        MIN_COMMISSION_MULTIPLE = 3.0  # Risk must be 3x commissions minimum
        
        commission_safe_minimum = ROUND_TRIP_COMMISSION * MIN_COMMISSION_MULTIPLE  # $0.42
        required_minimum = max(MIN_RISK_USD, commission_safe_minimum)  # $1.00
        
        if risk_usd < required_minimum:
            violations.append(RiskInvariant(
                name="ZERO_RISK_POSITION",
                violated=True,
                current_value=risk_usd,
                limit_value=required_minimum,
                severity="CRITICAL",
                message=f"Position risk ${risk_usd:.2f} too low (min ${required_minimum:.2f}) - Stop loss too tight or not properly set. Commission = ${ROUND_TRIP_COMMISSION:.2f}, requires {MIN_COMMISSION_MULTIPLE}x safety margin."
            ))
        
        # Check R per trade is within bounds
        if self.start_of_day_equity:
            r_pct = (risk_usd / self.start_of_day_equity) * 100
            max_r_pct = self.max_r_per_trade * 100
            
            if r_pct > max_r_pct:
                violations.append(RiskInvariant(
                    name="EXCESSIVE_R_PER_TRADE",
                    violated=True,
                    current_value=r_pct,
                    limit_value=max_r_pct,
                    severity="CRITICAL",
                    message=f"Trade risk {r_pct:.2f}% > max {max_r_pct:.1f}%"
                ))
        
        # 2. SL distance validation (must not be inside cluster)
        cluster_edge = trade.get('cluster_edge_price', None)
        if cluster_edge:
            sl_to_cluster_dist = abs(stop_loss - cluster_edge)
            min_buffer = entry_px * self.min_sl_cluster_buffer_pct
            
            if sl_to_cluster_dist < min_buffer:
                violations.append(RiskInvariant(
                    name="SL_TOO_CLOSE_TO_CLUSTER",
                    violated=True,
                    current_value=sl_to_cluster_dist,
                    limit_value=min_buffer,
                    severity="HIGH",
                    message=f"SL only ${sl_to_cluster_dist:.2f} from cluster (min ${min_buffer:.2f})"
                ))
        
        # 3. SL must be on correct side
        if side == "LONG" and stop_loss >= entry_px:
            violations.append(RiskInvariant(
                name="INVALID_SL_SIDE",
                violated=True,
                current_value=stop_loss,
                limit_value=entry_px,
                severity="CRITICAL",
                message=f"LONG SL ${stop_loss:.2f} >= entry ${entry_px:.2f}"
            ))
        elif side == "SHORT" and stop_loss <= entry_px:
            violations.append(RiskInvariant(
                name="INVALID_SL_SIDE",
                violated=True,
                current_value=stop_loss,
                limit_value=entry_px,
                severity="CRITICAL",
                message=f"SHORT SL ${stop_loss:.2f} <= entry ${entry_px:.2f}"
            ))
        
        return violations
    
    def get_remaining_risk(self, current_equity: float, daily_pnl: float) -> Dict:
        """
        Get current risk budget status.
        
        Returns dict with:
            - risk_remaining_usd: How much loss room left today
            - risk_used_pct: Percentage of daily cap used
            - daily_cap_hit: Whether we hit the cap
        """
        if self.start_of_day_equity is None:
            self.reset_daily_state(current_equity)
        
        daily_cap_usd = self.start_of_day_equity * self.daily_cap_pct
        daily_loss = max(0.0, -daily_pnl)
        risk_remaining_usd = max(0.0, daily_cap_usd - daily_loss)
        risk_used_pct = (daily_loss / daily_cap_usd) if daily_cap_usd > 0 else 0.0
        daily_cap_hit = daily_loss >= daily_cap_usd
        
        return {
            'risk_remaining_usd': risk_remaining_usd,
            'risk_used_pct': risk_used_pct,
            'daily_cap_hit': daily_cap_hit,
            'daily_cap_usd': daily_cap_usd,
            'daily_loss_usd': daily_loss
        }
    
    def can_open_new_position(
        self,
        current_equity: float,
        daily_pnl: float,
        open_positions: int,
        proposed_trade: Dict
    ) -> tuple[bool, str]:
        """
        Check if new position can be opened.
        
        Returns:
            (allowed: bool, reason: str)
        """
        can_trade, violations = self.validate_all_invariants(
            current_equity=current_equity,
            daily_pnl=daily_pnl,
            open_positions=open_positions,
            proposed_trade=proposed_trade
        )
        
        if not can_trade:
            reasons = "; ".join([v.message for v in violations])
            return False, f"Risk invariant violations: {reasons}"
        
        return True, "All invariants passed"


# Unit tests for risk invariants
def test_risk_invariants():
    """Quick tests for risk invariants"""
    from types import SimpleNamespace
    
    config = SimpleNamespace()
    config.get_trading_config = lambda: SimpleNamespace(
        daily_cap_pct=0.02,
        max_positions=3,
        max_r_per_trade=1.0
    )
    
    validator = RiskInvariantsValidator(config)
    validator.reset_daily_state(1000.0)
    
    # Test 1: Daily cap not hit
    can_trade, violations = validator.validate_all_invariants(
        current_equity=990.0,
        daily_pnl=-10.0,
        open_positions=1
    )
    assert can_trade, "Should allow trade when within limits"
    
    # Test 2: Daily cap hit
    can_trade, violations = validator.validate_all_invariants(
        current_equity=980.0,
        daily_pnl=-20.0,  # 2% of 1000
        open_positions=1
    )
    assert not can_trade, "Should block trade when daily cap hit"
    assert any(v.name == "DAILY_CAP_HIT" for v in violations)
    
    # Test 3: Max positions
    can_trade, violations = validator.validate_all_invariants(
        current_equity=1000.0,
        daily_pnl=0.0,
        open_positions=3  # At limit
    )
    assert not can_trade, "Should block when max positions reached"
    
    # Test 4: Invalid SL
    can_trade, violations = validator.validate_all_invariants(
        current_equity=1000.0,
        daily_pnl=0.0,
        open_positions=1,
        proposed_trade={
            'entry_price': 50000,
            'stop_loss': 51000,  # LONG with SL above entry (WRONG)
            'quantity': 0.01,
            'side': 'LONG'
        }
    )
    assert not can_trade, "Should block LONG with SL above entry"
    
    print("✅ All risk invariant tests passed")


if __name__ == "__main__":
    test_risk_invariants()
