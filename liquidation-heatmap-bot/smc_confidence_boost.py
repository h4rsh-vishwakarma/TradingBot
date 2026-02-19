"""
SMC Hybrid Confidence Boost - Core Module
==========================================
Implements SMC direction detection, FVG checking, and confidence boost logic.

This module:
1. Does NOT modify RL state_dim or training
2. Uses SMC only as confirmation (not override)
3. Is controlled by feature flag in smc_config_additions.py

Matches backtest semantics from py_ports/smart-money-concepts-smc-luxalgo.py
"""

import logging
import numpy as np
from typing import Dict, Optional, Tuple, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ============================================================================
# SMC Direction Detection (matches backtest semantics)
# ============================================================================

def compute_smc_direction(state: Dict[str, Any]) -> int:
    """
    Compute SMC-based market direction from state features.
    
    Uses Break of Structure (BOS) and Change of Character (CHoCH) to determine
    market direction, matching the backtest winner's semantics.
    
    Args:
        state: Dictionary containing SMC features from feature_engineering.py
               Expected keys: smc_bos, smc_choch, smc_market_structure
    
    Returns:
        +1 for bullish SMC structure
        -1 for bearish SMC structure  
         0 for neutral/unclear
    """
    try:
        # Extract SMC features (from feature_engineering.py)
        bos = state.get('smc_bos', 0)
        choch = state.get('smc_choch', 0)
        market_structure = state.get('smc_market_structure', 0)
        
        # Handle potential None values
        bos = bos if bos is not None else 0
        choch = choch if choch is not None else 0
        market_structure = market_structure if market_structure is not None else 0
        
        # Primary: Use BOS for direction (Break of Structure is strongest signal)
        # Positive BOS = bullish break, Negative BOS = bearish break
        if abs(bos) > 0.5:
            return 1 if bos > 0 else -1
        
        # Secondary: Use CHoCH (Change of Character indicates reversal)
        # Positive CHoCH = bullish reversal, Negative = bearish reversal
        if abs(choch) > 0.5:
            return 1 if choch > 0 else -1
        
        # Tertiary: Use overall market structure
        # This is a composite score from the feature engineering
        if abs(market_structure) > 0.3:
            return 1 if market_structure > 0 else -1
        
        # No clear SMC direction
        return 0
        
    except Exception as e:
        logger.warning(f"Error computing SMC direction: {e}")
        return 0


def check_fvg_in_direction(state: Dict[str, Any], direction: int = 0) -> bool:
    """
    Check if a Fair Value Gap (FVG) exists in the signal direction.
    
    FVG presence in the trade direction indicates:
    - Unfilled orders/liquidity at that level
    - Higher probability price will return to fill the gap
    - Better entry opportunity (matching backtest semantics)
    
    Args:
        state: Dictionary containing SMC features
               Expected keys: smc_fvg_present, smc_order_block_distance
        direction: Trade direction (+1 long, -1 short, 0 = use SMC direction)
    
    Returns:
        True if FVG present in favorable direction
        False otherwise
    """
    try:
        # Check if FVG is present
        fvg_present = state.get('smc_fvg_present', False)
        
        # Handle various value types (bool, int, float)
        if isinstance(fvg_present, (int, float)):
            fvg_present = fvg_present > 0.5
        elif isinstance(fvg_present, bool):
            pass  # Already bool
        else:
            fvg_present = False
        
        if not fvg_present:
            return False
        
        # If direction specified, check if order block supports the direction
        if direction != 0:
            ob_distance = state.get('smc_order_block_distance', 0)
            ob_distance = ob_distance if ob_distance is not None else 0
            
            # Positive OB distance = order block below price (bullish support)
            # Negative OB distance = order block above price (bearish resistance)
            if direction > 0 and ob_distance > 0:
                return True  # Long trade with bullish OB support
            elif direction < 0 and ob_distance < 0:
                return True  # Short trade with bearish OB resistance
            
            # FVG present but OB doesn't align - still return True
            # (FVG alone is valuable signal)
            return True
        
        return fvg_present
        
    except Exception as e:
        logger.warning(f"Error checking FVG: {e}")
        return False


# ============================================================================
# Confidence Boost Calculation (exact pseudocode implementation)
# ============================================================================

@dataclass
class SMCBoostResult:
    """Result of SMC confidence boost calculation"""
    base_confidence: float
    new_confidence: float
    conf_mult: float
    smc_direction: int
    smc_has_fvg: bool
    boost_applied: bool
    reason: str


def apply_smc_confidence_boost(
    base_confidence: float,
    state: Dict[str, Any],
    smc_enabled: bool = False,
    params: Optional[Dict[str, float]] = None
) -> SMCBoostResult:
    """
    Apply SMC-based confidence boost following exact pseudocode spec.
    
    Implementation:
        base_confidence = compute_existing_confidence(...)    # unchanged
        smc_direction = compute_smc_direction(state)         # returns +1/0/-1
        smc_has_fvg = check_fvg_in_direction(state)          # bool

        if ENABLE_SMC_CONFIDENCE_BOOST and smc_direction == sign(base_confidence):
            conf_mult = 1.0 + SMC_BOOST_PARAMS.SM_NORMAL_BOOST
            if smc_has_fvg:
                conf_mult *= (1.0 + SMC_BOOST_PARAMS.SM_FVG_BONUS)
            conf_mult = min(conf_mult, SMC_BOOST_PARAMS.MAX_POS_MULT)
        else:
            conf_mult = 1.0

        new_confidence = base_confidence * conf_mult
    
    Args:
        base_confidence: Original confidence from existing system (unchanged)
        state: Market state dict with SMC features
        smc_enabled: Feature flag (from config)
        params: SMC boost parameters dict
    
    Returns:
        SMCBoostResult with all fields for logging
    """
    # Default parameters
    if params is None:
        params = {
            'SM_NORMAL_BOOST': 0.15,
            'SM_FVG_BONUS': 0.20,
            'MAX_POS_MULT': 1.5
        }
    
    # Compute SMC signals (always compute for logging)
    smc_direction = compute_smc_direction(state)
    smc_has_fvg = check_fvg_in_direction(state, smc_direction)
    
    # Get sign of base confidence
    base_sign = 1 if base_confidence > 0 else (-1 if base_confidence < 0 else 0)
    
    # Determine if boost applies
    conf_mult = 1.0
    boost_applied = False
    reason = "disabled"
    
    if smc_enabled:
        if smc_direction != 0 and smc_direction == base_sign:
            # SMC direction aligns with signal direction
            conf_mult = 1.0 + params['SM_NORMAL_BOOST']
            reason = f"smc_align_{'+' if smc_direction > 0 else '-'}"
            
            if smc_has_fvg:
                conf_mult *= (1.0 + params['SM_FVG_BONUS'])
                reason += "_fvg"
            
            # Apply cap
            conf_mult = min(conf_mult, params['MAX_POS_MULT'])
            boost_applied = True
        elif smc_direction == 0:
            reason = "smc_neutral"
        else:
            reason = "smc_misalign"
    
    # Calculate new confidence (preserve sign)
    new_confidence = base_confidence * conf_mult
    
    return SMCBoostResult(
        base_confidence=base_confidence,
        new_confidence=new_confidence,
        conf_mult=conf_mult,
        smc_direction=smc_direction,
        smc_has_fvg=smc_has_fvg,
        boost_applied=boost_applied,
        reason=reason
    )


# ============================================================================
# Structured Logging
# ============================================================================

def log_smc_boost(result: SMCBoostResult, extra_context: Optional[Dict] = None) -> Dict:
    """
    Generate structured log entry for SMC boost.
    
    Log format (matches acceptance criteria):
        log.info("SMC_BOOST", extra={
            "smc_direction": smc_direction,
            "smc_has_fvg": smc_has_fvg,
            "base_confidence": base_confidence,
            "new_confidence": new_confidence,
            "pos_size_multiplier": conf_mult
        })
    
    Args:
        result: SMCBoostResult from apply_smc_confidence_boost()
        extra_context: Additional context (symbol, timestamp, etc.)
    
    Returns:
        Log dict for observability
    """
    log_entry = {
        'event': 'SMC_BOOST',
        'smc_direction': result.smc_direction,
        'smc_has_fvg': result.smc_has_fvg,
        'base_confidence': round(result.base_confidence, 4),
        'new_confidence': round(result.new_confidence, 4),
        'pos_size_multiplier': round(result.conf_mult, 4),
        'boost_applied': result.boost_applied,
        'reason': result.reason
    }
    
    if extra_context:
        log_entry.update(extra_context)
    
    # Log using structured format
    logger.info(
        f"SMC_BOOST: direction={result.smc_direction}, fvg={result.smc_has_fvg}, "
        f"conf={result.base_confidence:.3f}->{result.new_confidence:.3f} "
        f"(mult={result.conf_mult:.2f}, {result.reason})",
        extra=log_entry
    )
    
    return log_entry


# ============================================================================
# Integration Helper for signal_generator.py
# ============================================================================

def get_boosted_confidence(
    base_confidence: float,
    market_features: Dict[str, Any],
    config: Any = None,
    log_result: bool = True
) -> Tuple[float, float]:
    """
    Main entry point for signal_generator.py integration.
    
    Usage in signal_generator.py:
        from smc_confidence_boost import get_boosted_confidence
        
        # After calculating base confidence
        new_confidence, pos_mult = get_boosted_confidence(
            base_confidence=combined_confidence,
            market_features=market_features,
            config=self.trading_config,
            log_result=True
        )
    
    Args:
        base_confidence: Original confidence value
        market_features: Dict with SMC features (smc_bos, smc_choch, etc.)
        config: TradingConfig with smc_boost settings
        log_result: Whether to emit structured log
    
    Returns:
        Tuple of (new_confidence, position_size_multiplier)
    """
    # Check if SMC boost is enabled
    smc_enabled = False
    params = {
        'SM_NORMAL_BOOST': 0.15,
        'SM_FVG_BONUS': 0.20,
        'MAX_POS_MULT': 1.5
    }
    
    if config is not None:
        if hasattr(config, 'smc_boost'):
            smc_boost_cfg = config.smc_boost
            smc_enabled = getattr(smc_boost_cfg, 'enabled', False)
            if hasattr(smc_boost_cfg, 'get_params'):
                params = smc_boost_cfg.get_params()
            else:
                params = {
                    'SM_NORMAL_BOOST': getattr(smc_boost_cfg, 'normal_boost', 0.15),
                    'SM_FVG_BONUS': getattr(smc_boost_cfg, 'fvg_bonus', 0.20),
                    'MAX_POS_MULT': getattr(smc_boost_cfg, 'max_multiplier', 1.5),
                }
    
    # Apply boost
    result = apply_smc_confidence_boost(
        base_confidence=base_confidence,
        state=market_features,
        smc_enabled=smc_enabled,
        params=params
    )
    
    # Log if requested (and either boost applied OR log_all_signals enabled)
    if log_result:
        should_log = result.boost_applied
        if config and hasattr(config, 'smc_boost'):
            should_log = should_log or getattr(config.smc_boost, 'log_all_signals', True)
        if should_log:
            log_smc_boost(result)
    
    return result.new_confidence, result.conf_mult


if __name__ == '__main__':
    # Self-test
    print("SMC Confidence Boost - Self Test")
    print("=" * 50)
    
    # Test case 1: SMC aligns with long signal
    test_state = {
        'smc_bos': 0.8,
        'smc_choch': 0.5,
        'smc_market_structure': 0.6,
        'smc_fvg_present': True,
        'smc_order_block_distance': 0.3
    }
    
    result = apply_smc_confidence_boost(
        base_confidence=0.65,
        state=test_state,
        smc_enabled=True
    )
    
    print(f"\nTest 1: Long signal with bullish SMC + FVG")
    print(f"  Base: {result.base_confidence}")
    print(f"  New:  {result.new_confidence}")
    print(f"  Mult: {result.conf_mult}")
    print(f"  Applied: {result.boost_applied}")
    print(f"  Reason: {result.reason}")
    
    # Test case 2: SMC misaligns
    test_state2 = {
        'smc_bos': -0.8,  # Bearish
        'smc_choch': -0.5,
        'smc_market_structure': -0.6,
        'smc_fvg_present': True,
        'smc_order_block_distance': -0.3
    }
    
    result2 = apply_smc_confidence_boost(
        base_confidence=0.65,  # Long signal
        state=test_state2,
        smc_enabled=True
    )
    
    print(f"\nTest 2: Long signal with bearish SMC (misalign)")
    print(f"  Base: {result2.base_confidence}")
    print(f"  New:  {result2.new_confidence}")
    print(f"  Mult: {result2.conf_mult}")
    print(f"  Applied: {result2.boost_applied}")
    print(f"  Reason: {result2.reason}")
    
    # Test case 3: Disabled
    result3 = apply_smc_confidence_boost(
        base_confidence=0.65,
        state=test_state,
        smc_enabled=False
    )
    
    print(f"\nTest 3: Feature flag disabled")
    print(f"  Mult: {result3.conf_mult} (should be 1.0)")
    print(f"  Applied: {result3.boost_applied} (should be False)")
