"""
SMC Hybrid Confidence Boost - Configuration Additions
======================================================
Add these to config.py after TradingConfig class

This file contains the additions needed for the SMC hybrid confidence boost feature.
Copy the SMCBoostConfig class and add the smc_boost attribute to TradingConfig.
"""

from dataclasses import dataclass, field
from typing import Dict

@dataclass
class SMCBoostConfig:
    """SMC Hybrid Confidence Boost configuration
    
    Feature flag and parameters for SMC-based confidence boosting.
    This is a confirmation-only system - it does NOT override votes or act as a hard rule.
    """
    # Feature flag - must be True to enable SMC boost
    enabled: bool = False  # Default OFF for safety - toggle at runtime
    
    # Boost parameters
    normal_boost: float = 0.15      # SM_NORMAL_BOOST: 15% boost when SMC aligns
    fvg_bonus: float = 0.20         # SM_FVG_BONUS: Additional 20% bonus for FVG
    max_multiplier: float = 1.5     # MAX_POS_MULT: Cap total multiplier at 1.5x
    
    # Logging control
    log_all_signals: bool = True    # Log SMC info even when boost not applied
    
    def get_params(self) -> Dict[str, float]:
        """Get params as dict for compatibility"""
        return {
            'SM_NORMAL_BOOST': self.normal_boost,
            'SM_FVG_BONUS': self.fvg_bonus,
            'MAX_POS_MULT': self.max_multiplier
        }


# ============================================================================
# INTEGRATION: Add to TradingConfig dataclass
# ============================================================================
# 
# Add this field to TradingConfig:
#
#     # SMC Hybrid Confidence Boost (feature flag)
#     smc_boost: SMCBoostConfig = field(default_factory=SMCBoostConfig)
#
# ============================================================================


# ============================================================================
# ENVIRONMENT VARIABLE SUPPORT
# ============================================================================
# Add these to the env_mappings dict in ConfigManager._load_from_env():
#
#     'ENABLE_SMC_CONFIDENCE_BOOST': ('trading_config', 'smc_boost.enabled', bool),
#     'SMC_NORMAL_BOOST': ('trading_config', 'smc_boost.normal_boost', float),
#     'SMC_FVG_BONUS': ('trading_config', 'smc_boost.fvg_bonus', float),
#     'SMC_MAX_MULTIPLIER': ('trading_config', 'smc_boost.max_multiplier', float),
#
# ============================================================================


# ============================================================================
# RUNTIME TOGGLE SUPPORT
# ============================================================================
def toggle_smc_boost(config, enabled: bool = True) -> None:
    """Toggle SMC boost at runtime without restart
    
    Usage:
        from smc_config_additions import toggle_smc_boost
        toggle_smc_boost(config_manager.trading_config, enabled=True)
    """
    if hasattr(config, 'smc_boost'):
        config.smc_boost.enabled = enabled
    else:
        raise AttributeError("SMC boost config not found - ensure SMCBoostConfig is added to TradingConfig")
