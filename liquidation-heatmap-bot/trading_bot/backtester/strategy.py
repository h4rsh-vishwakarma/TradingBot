"""
Strategy Configuration and Signal Generation

Base class for backtesting strategies with parameter management.
Strategies can transform or filter signals before execution.
"""

import pandas as pd
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class Strategy:
    """
    Base strategy class for backtesting.
    
    Encapsulates trading parameters and optional signal transformation logic.
    Default behavior passes through signals from data loader unchanged.
    
    Parameters:
        params: Dictionary of strategy parameters including:
            - slippage_bps: Slippage in basis points (e.g., 5 = 0.05%)
            - commission_pct: Commission per trade as decimal (e.g., 0.0002 = 0.02%)
            - sl_pct: Stop loss percentage from entry (e.g., 0.01 = 1%)
            - tp_pct: Take profit percentage from entry (e.g., 0.02 = 2%)
            - size_usd: Fixed position size in USD (for fixed sizing)
            - risk_pct: Risk percentage of equity per trade (for risk-based sizing)
            - enter_on: Entry timing - 'next_open' (default) or 'same_bar'
    
    Example:
        >>> params = {
        ...     'slippage_bps': 5,
        ...     'commission_pct': 0.0002,
        ...     'sl_pct': 0.01,
        ...     'tp_pct': 0.02,
        ...     'size_usd': 1000
        ... }
        >>> strategy = Strategy(params)
    """
    
    def __init__(self, params: Dict[str, Any]):
        """
        Initialize strategy with parameters.
        
        Args:
            params: Dictionary of trading parameters
        """
        self.params = params
        
        # Extract and validate key parameters
        self.slippage_bps = params.get('slippage_bps', 0)
        self.commission_pct = params.get('commission_pct', 0.0)
        self.sl_pct = params.get('sl_pct', None)
        self.tp_pct = params.get('tp_pct', None)
        self.size_usd = params.get('size_usd', None)
        self.risk_pct = params.get('risk_pct', None)
        self.enter_on = params.get('enter_on', 'next_open')
        
        # Validate sizing configuration
        if self.size_usd is None and self.risk_pct is None:
            raise ValueError(
                "Must specify either 'size_usd' for fixed sizing or 'risk_pct' for risk-based sizing"
            )
        
        if self.size_usd is not None and self.risk_pct is not None:
            logger.warning("Both size_usd and risk_pct specified. Using size_usd (fixed sizing).")
            self.risk_pct = None
        
        # Validate risk-based sizing requirements
        if self.risk_pct is not None and self.sl_pct is None:
            raise ValueError(
                "Risk-based sizing (risk_pct) requires stop loss (sl_pct) to calculate position size"
            )
        
        # Validate entry timing
        if self.enter_on not in ['next_open', 'same_bar']:
            raise ValueError(f"enter_on must be 'next_open' or 'same_bar', got: {self.enter_on}")
        
        logger.info(f"Strategy initialized with params: {self.params}")
    
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """
        Generate or transform trading signals.
        
        Default implementation returns signals as-is from the data loader.
        Override this method to implement custom signal logic, filtering,
        or thresholding.
        
        Args:
            df: DataFrame with OHLCV data and 'signal' column
        
        Returns:
            Series with same index as df containing signals:
                1 for long entry, -1 for short entry, 0 for no signal
        
        Example override:
            def generate_signals(self, df):
                # Filter signals by volatility threshold
                signals = df['signal'].copy()
                volatility = df['close'].pct_change().rolling(20).std()
                signals[volatility < 0.01] = 0  # No trade in low volatility
                return signals
        """
        if 'signal' not in df.columns:
            raise ValueError("DataFrame must have 'signal' column from data loader")
        
        return df['signal']
    
    def __repr__(self):
        return f"Strategy(params={self.params})"
