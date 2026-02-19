#!/usr/bin/env python3
import re

with open('/home/ubuntu/trading_bot/config.py', 'r') as f:
    content = f.read()

if 'SMCBoostConfig' in content:
    print('SMCBoostConfig already exists')
    exit(0)

content = content.replace(
    'from dataclasses import dataclass',
    'from dataclasses import dataclass, field'
)

smc_class = '''
@dataclass
class SMCBoostConfig:
    enabled: bool = True
    normal_boost: float = 0.15
    fvg_bonus: float = 0.20
    max_multiplier: float = 1.5
    log_all_signals: bool = True
    def get_params(self):
        return {'SM_NORMAL_BOOST': self.normal_boost, 'SM_FVG_BONUS': self.fvg_bonus, 'MAX_POS_MULT': self.max_multiplier}


'''

content = content.replace('@dataclass\nclass APIConfig:', smc_class + '@dataclass\nclass APIConfig:')

smc_field = '''    
    smc_boost: SMCBoostConfig = field(default_factory=SMCBoostConfig)
    
    # Timeframes for analysis'''

content = content.replace('    # Timeframes for analysis', smc_field)

with open('/home/ubuntu/trading_bot/config.py', 'w') as f:
    f.write(content)

print('SMCBoostConfig added!')
