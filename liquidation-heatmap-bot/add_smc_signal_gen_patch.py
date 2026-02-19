#!/usr/bin/env python3
"""
Add SMC Confidence Boost integration to signal_generator.py
"""
import re

SIGNAL_GEN_PATH = '/home/ubuntu/trading_bot/signal_generator.py'

# Read current file
with open(SIGNAL_GEN_PATH, 'r') as f:
    content = f.read()

# Check if already integrated
if 'SMC_BOOST_AVAILABLE' in content:
    print('SMC boost integration already exists in signal_generator.py - skipping')
    exit(0)

print('Adding SMC boost integration to signal_generator.py...')

# Step 1: Add import after other imports (find last import line before class definition)
import_addition = '''
# SMC Hybrid Confidence Boost (feature flag controlled)
try:
    from smc_boost_helpers import calculate_smc_boost, compute_smc_direction, check_fvg_in_direction
    SMC_BOOST_AVAILABLE = True
except ImportError:
    SMC_BOOST_AVAILABLE = False
'''

# Find a safe place to add import - after the RL_MODEL_AVAILABLE check
if 'RL_MODEL_AVAILABLE = True' in content:
    content = content.replace(
        'RL_MODEL_AVAILABLE = True',
        'RL_MODEL_AVAILABLE = True' + import_addition
    )
    print('  - Added SMC boost import')
elif 'RL_MODEL_AVAILABLE = False' in content:
    # Find RL_MODEL_AVAILABLE = False (from except block)
    content = content.replace(
        'RL_MODEL_AVAILABLE = False',
        'RL_MODEL_AVAILABLE = False' + import_addition.replace('SMC_BOOST_AVAILABLE = True', 'SMC_BOOST_AVAILABLE = False')
    )
    print('  - Added SMC boost import (in except block)')
else:
    print('WARNING: Could not find RL_MODEL_AVAILABLE marker')

# Step 2: Add SMC boost logic after combined_confidence calculation
# Look for the section where combined_confidence is set and threshold checked
smc_boost_code = '''
            # === SMC HYBRID CONFIDENCE BOOST ===
            smc_multiplier = 1.0
            smc_boost_log = {}
            if SMC_BOOST_AVAILABLE and hasattr(self.trading_config, 'smc_boost') and self.trading_config.smc_boost.enabled:
                try:
                    smc_state = market_features.copy() if market_features else {}
                    bias_sign = 1 if signal['direction'] == 'LONG' else -1
                    smc_params = self.trading_config.smc_boost.get_params()
                    
                    boosted_conf, smc_multiplier, smc_boost_log = calculate_smc_boost(
                        base_confidence=combined_confidence,
                        state=smc_state,
                        bias_sign=bias_sign,
                        enabled=True,
                        normal_boost=smc_params.get('SM_NORMAL_BOOST', 0.15),
                        fvg_bonus=smc_params.get('SM_FVG_BONUS', 0.20),
                        max_multiplier=smc_params.get('MAX_POS_MULT', 1.5)
                    )
                    
                    if smc_multiplier > 1.0:
                        logger.info(f"SMC_BOOST: conf {combined_confidence:.4f} -> {boosted_conf:.4f} (x{smc_multiplier:.2f})")
                        combined_confidence = boosted_conf
                    
                    logger.info("SMC_BOOST", extra={
                        "smc_direction": smc_boost_log.get('smc_direction', 0),
                        "smc_has_fvg": smc_boost_log.get('smc_has_fvg', False),
                        "base_confidence": smc_boost_log.get('base_confidence', 0),
                        "new_confidence": smc_boost_log.get('new_confidence', 0),
                        "pos_size_multiplier": smc_boost_log.get('pos_size_multiplier', 1.0)
                    })
                except Exception as smc_err:
                    logger.debug(f"SMC boost error: {smc_err}")
            # === END SMC BOOST ===

            # Check if signal meets minimum confidence threshold'''

# Find the confidence threshold check and insert SMC boost before it
target_pattern = '''            # Check if signal meets minimum confidence threshold
            if combined_confidence < self.trading_config.min_confidence_threshold:'''

if target_pattern in content:
    content = content.replace(target_pattern, smc_boost_code)
    print('  - Added SMC boost logic before confidence threshold check')
else:
    # Try alternate pattern
    alt_pattern = '            if combined_confidence < self.trading_config.min_confidence_threshold:'
    if alt_pattern in content:
        content = content.replace(alt_pattern, smc_boost_code.split('# Check if signal')[0] + alt_pattern)
        print('  - Added SMC boost logic (alternate pattern)')
    else:
        print('WARNING: Could not find confidence threshold check pattern')

# Write back
with open(SIGNAL_GEN_PATH, 'w') as f:
    f.write(content)

print('SUCCESS: SMC boost integration added to signal_generator.py!')
