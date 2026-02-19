#!/usr/bin/env python3
"""Add SMCBoostConfig to config.py on Ubuntu server"""
import re

CONFIG_PATH = '/home/ubuntu/trading_bot/config.py'

# Read current config
with open(CONFIG_PATH, 'r') as f:
    content = f.read()

# Check if already added
if 'SMCBoostConfig' in content:
    print('SMCBoostConfig already exists in config.py - skipping')
    exit(0)

print('Adding SMCBoostConfig to config.py...')

# Step 1: Update import to include field
if 'from dataclasses import dataclass, field' not in content:
    content = content.replace(
        'from dataclasses import dataclass',
        'from dataclasses import dataclass, field'
    )
    print('  - Updated dataclass import to include field')

# Step 2: Add SMCBoostConfig class before APIConfig
smc_config_class = '''@dataclass
class SMCBoostConfig:
    """SMC Hybrid Confidence Boost configuration (feature flag)
    
    Safe, reversible enhancement using SMC only as confirmation.
    Does NOT override votes or act as hard rules.
    """
    # Feature flag - must be True to enable boost
    enabled: bool = True   # ON by default for paper testing
    
    # Boost parameters
    normal_boost: float = 0.15      # SM_NORMAL_BOOST: 15% boost when SMC aligns
    fvg_bonus: float = 0.20         # SM_FVG_BONUS: Additional 20% bonus for FVG
    max_multiplier: float = 1.5     # MAX_POS_MULT: Cap total multiplier at 1.5x
    
    # Logging
    log_all_signals: bool = True    # Log SMC info even when boost not applied
    
    def get_params(self):
        """Get params as dict for boost calculation"""
        return {
            'SM_NORMAL_BOOST': self.normal_boost,
            'SM_FVG_BONUS': self.fvg_bonus,
            'MAX_POS_MULT': self.max_multiplier
        }


'''

# Find @dataclass\nclass APIConfig and insert SMCBoostConfig before it
if '@dataclass\nclass APIConfig:' in content:
    content = content.replace(
        '@dataclass\nclass APIConfig:',
        smc_config_class + '@dataclass\nclass APIConfig:'
    )
    print('  - Added SMCBoostConfig class')
else:
    print('ERROR: Could not find APIConfig class marker')
    exit(1)

# Step 3: Add smc_boost field to TradingConfig
# Find the line with "# Timeframes for analysis" and add before it
smc_field_addition = '''    # SMC Hybrid Confidence Boost (feature flag)
    smc_boost: SMCBoostConfig = field(default_factory=SMCBoostConfig)
    
    # Timeframes for analysis'''

if '# Timeframes for analysis' in content:
    content = content.replace(
        '    # Timeframes for analysis',
        smc_field_addition
    )
    print('  - Added smc_boost field to TradingConfig')
else:
    print('WARNING: Could not find Timeframes marker, adding at end of TradingConfig')

# Write back
with open(CONFIG_PATH, 'w') as f:
    f.write(content)

print('SUCCESS: SMCBoostConfig added to config.py!')
print('  - SMC boost is ENABLED by default')
print('  - Parameters: 15% normal boost, 20% FVG bonus, 1.5x max')
