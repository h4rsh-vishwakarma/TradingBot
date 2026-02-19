"""
SMC Hybrid Confidence Boost - Feature Engineering Helpers
==========================================================
Add these functions to feature_engineering.py after calculate_smart_money_concepts()

These helper functions provide the interface for the SMC confidence boost system.
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)


def compute_smc_direction(state: Dict) -> int:
    """
    Compute SMC direction from current market state.
    
    Returns:
        +1: Bullish SMC structure (HH/HL, bullish BOS)
        -1: Bearish SMC structure (LH/LL, bearish BOS)
         0: Neutral/unclear structure
         
    The direction is determined by:
    1. Primary: market_structure (+1 bullish, -1 bearish, 0 neutral)
    2. Secondary: BOS direction (confirms or overrides neutral structure)
    3. Tertiary: CHoCH (change of character signals potential reversal)
    """
    try:
        # Extract SMC features from state
        # State can be MarketFeatures dict or raw feature dict
        smc_structure = state.get('smc_market_structure', state.get('market_structure', 0))
        smc_bos = state.get('smc_bos', state.get('bos', 0))
        smc_choch = state.get('smc_choch', state.get('choch', 0))
        
        # Convert to numeric if needed
        smc_structure = float(smc_structure) if smc_structure else 0
        smc_bos = float(smc_bos) if smc_bos else 0
        smc_choch = float(smc_choch) if smc_choch else 0
        
        # Primary: Use market structure as base
        direction = 0
        
        if smc_structure > 0:
            direction = 1  # Bullish structure (HH/HL)
        elif smc_structure < 0:
            direction = -1  # Bearish structure (LH/LL)
        
        # Secondary: BOS can confirm or set direction
        if smc_bos != 0:
            if direction == 0:
                # No clear structure, use BOS direction
                direction = 1 if smc_bos > 0 else -1
            elif (smc_bos > 0 and direction > 0) or (smc_bos < 0 and direction < 0):
                # BOS confirms structure - strong signal (direction unchanged)
                pass
            else:
                # BOS contradicts structure - conflicting signal, be cautious
                logger.debug(f"SMC: BOS ({smc_bos}) contradicts structure ({smc_structure})")
                # Keep structure direction but note the conflict
                
        # Tertiary: CHoCH indicates potential reversal
        if smc_choch != 0:
            # CHoCH is a warning signal - it doesn't change direction
            # but we log it for awareness
            logger.debug(f"SMC: CHoCH detected ({smc_choch}) - potential reversal brewing")
            
            # If CHoCH is strong and contradicts current direction, reduce confidence
            # by returning 0 (neutral) - let the main system decide
            if (smc_choch > 0 and direction < 0) or (smc_choch < 0 and direction > 0):
                logger.debug("SMC: CHoCH suggests reversal - returning neutral direction")
                return 0
        
        return int(direction)
        
    except Exception as e:
        logger.warning(f"compute_smc_direction error: {e}")
        return 0  # Default to neutral on error


def check_fvg_in_direction(state: Dict, bias_direction: Optional[int] = None) -> bool:
    """
    Check if there's a Fair Value Gap (FVG) aligned with the trade direction.
    
    FVG is a 3-candle imbalance that often acts as a magnet for price.
    For the boost to apply, the FVG should be in the direction of the trade.
    
    Args:
        state: Market state dictionary with SMC features
        bias_direction: Optional explicit direction (+1 long, -1 short)
                       If None, uses SMC direction from state
    
    Returns:
        True if FVG present AND aligned with direction
        False otherwise
    """
    try:
        # Check if FVG is present at all
        fvg_present = state.get('smc_fvg_present', state.get('fvg_present', False))
        
        # Handle various boolean representations
        if isinstance(fvg_present, str):
            fvg_present = fvg_present.lower() in ('true', '1', 'yes')
        else:
            fvg_present = bool(fvg_present)
            
        if not fvg_present:
            return False
            
        # If no explicit bias given, use SMC direction
        if bias_direction is None:
            bias_direction = compute_smc_direction(state)
            
        if bias_direction == 0:
            # Neutral bias - FVG present but not directionally aligned
            return False
            
        # Check order block distance to determine FVG type
        # Positive distance = price above order block = bullish context
        # Negative distance = price below order block = bearish context
        ob_distance = state.get('smc_order_block_distance', state.get('order_block_distance', 0))
        ob_distance = float(ob_distance) if ob_distance else 0
        
        # FVG is aligned if:
        # - Bullish bias (+1) and price is near/above order block (positive distance)
        # - Bearish bias (-1) and price is near/below order block (negative distance)
        
        # For simplicity, if FVG is present and we have a directional bias, consider it aligned
        # The existing calculate_smart_money_concepts already filters FVGs
        # More sophisticated alignment would require tracking FVG direction separately
        
        # Check if market structure matches bias
        smc_structure = state.get('smc_market_structure', state.get('market_structure', 0))
        smc_structure = float(smc_structure) if smc_structure else 0
        
        # FVG is aligned if structure matches bias direction
        if bias_direction > 0 and smc_structure >= 0:
            return True  # Bullish or neutral structure with long bias
        elif bias_direction < 0 and smc_structure <= 0:
            return True  # Bearish or neutral structure with short bias
            
        return False
        
    except Exception as e:
        logger.warning(f"check_fvg_in_direction error: {e}")
        return False


def calculate_smc_boost(
    base_confidence: float,
    state: Dict,
    bias_sign: int,
    enabled: bool = False,
    normal_boost: float = 0.15,
    fvg_bonus: float = 0.20,
    max_multiplier: float = 1.5,
    log_callback=None
) -> tuple[float, float, Dict]:
    """
    Calculate SMC confidence boost multiplier.
    
    This is the main entry point for the SMC hybrid confidence boost system.
    It ONLY boosts confidence when SMC aligns with the existing signal direction.
    It NEVER overrides or contradicts the base signal.
    
    Args:
        base_confidence: Original confidence value from voting system
        state: Market state dictionary with SMC features
        bias_sign: Sign of base confidence (+1 for long, -1 for short)
        enabled: Feature flag - must be True for boost to apply
        normal_boost: Base boost when SMC aligns (default 0.15 = 15%)
        fvg_bonus: Additional boost when FVG present (default 0.20 = 20%)
        max_multiplier: Maximum total multiplier (default 1.5x)
        log_callback: Optional callback for structured logging
        
    Returns:
        tuple of (new_confidence, multiplier, log_data)
    """
    # Get SMC direction
    smc_direction = compute_smc_direction(state)
    
    # Check FVG alignment
    smc_has_fvg = check_fvg_in_direction(state, bias_sign)
    
    # Calculate multiplier
    conf_mult = 1.0
    
    if enabled and smc_direction == bias_sign and bias_sign != 0:
        # SMC aligns with bias - apply boost
        conf_mult = 1.0 + normal_boost
        
        if smc_has_fvg:
            # FVG bonus compounds with normal boost
            conf_mult *= (1.0 + fvg_bonus)
            
        # Cap at maximum
        conf_mult = min(conf_mult, max_multiplier)
    
    # Calculate new confidence
    new_confidence = base_confidence * conf_mult
    
    # Prepare log data
    log_data = {
        'smc_direction': smc_direction,
        'smc_has_fvg': smc_has_fvg,
        'base_confidence': round(base_confidence, 4),
        'new_confidence': round(new_confidence, 4),
        'pos_size_multiplier': round(conf_mult, 4),
        'smc_boost_enabled': enabled,
        'bias_sign': bias_sign,
        'boost_applied': conf_mult > 1.0
    }
    
    # Call logging callback if provided
    if log_callback:
        try:
            log_callback(log_data)
        except Exception as e:
            logger.warning(f"SMC boost log callback error: {e}")
    
    return new_confidence, conf_mult, log_data


# ============================================================================
# INTEGRATION: Add these to FeatureEngine class in feature_engineering.py
# ============================================================================
#
# class FeatureEngine:
#     ...
#     
#     def compute_smc_direction(self, state: Dict) -> int:
#         """Compute SMC direction from market state"""
#         return compute_smc_direction(state)
#     
#     def check_fvg_in_direction(self, state: Dict, bias_direction: int = None) -> bool:
#         """Check if FVG aligns with trade direction"""
#         return check_fvg_in_direction(state, bias_direction)
#     
#     def calculate_smc_boost(self, base_confidence: float, state: Dict, 
#                             bias_sign: int, config) -> tuple:
#         """Calculate SMC confidence boost"""
#         return calculate_smc_boost(
#             base_confidence=base_confidence,
#             state=state,
#             bias_sign=bias_sign,
#             enabled=getattr(config, 'smc_boost', {}).get('enabled', False),
#             normal_boost=getattr(config, 'smc_boost', {}).get('normal_boost', 0.15),
#             fvg_bonus=getattr(config, 'smc_boost', {}).get('fvg_bonus', 0.20),
#             max_multiplier=getattr(config, 'smc_boost', {}).get('max_multiplier', 1.5)
#         )
#
# ============================================================================
