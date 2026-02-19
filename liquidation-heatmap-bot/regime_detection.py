"""
Multi-Timeframe Regime Detection
Classifies market regimes (trend, volatility, funding) to filter trades.
"""

import numpy as np
from typing import Dict, Optional, List
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class TrendRegime(Enum):
    """Trend classification"""
    STRONG_UPTREND = "STRONG_UPTREND"
    WEAK_UPTREND = "WEAK_UPTREND"
    SIDEWAYS = "SIDEWAYS"
    WEAK_DOWNTREND = "WEAK_DOWNTREND"
    STRONG_DOWNTREND = "STRONG_DOWNTREND"


class VolatilityRegime(Enum):
    """Volatility classification"""
    VERY_LOW = "VERY_LOW"
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    EXTREME = "EXTREME"


class FundingRegime(Enum):
    """Funding rate classification"""
    VERY_NEGATIVE = "VERY_NEGATIVE"  # Strong shorts, contrarian LONG
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"
    POSITIVE = "POSITIVE"
    VERY_POSITIVE = "VERY_POSITIVE"  # Strong longs, contrarian SHORT


@dataclass
class RegimeState:
    """Current market regime across dimensions"""
    trend: TrendRegime
    volatility: VolatilityRegime
    funding: FundingRegime
    regime_tag: str  # Combined tag for logging (e.g., "STRONG_UP_HIGH_VOL_NEUTRAL")
    trend_strength: float  # -1 to +1
    volatility_z: float  # Z-score
    funding_rate_pct: float  # Annualized funding rate %
    confidence: float  # 0-1, data quality


class RegimeDetector:
    """
    Multi-dimensional regime classifier.
    
    Purpose: Filter trades based on market conditions:
    - Trend: Avoid counter-trend in strong trends
    - Volatility: Avoid trading in extreme volatility (poor fills)
    - Funding: Use contrarian signals (fade crowded positions)
    """
    
    def __init__(self, config):
        self.config = config
        
        # Trend thresholds (based on EMA slope)
        self.trend_thresholds = {
            'strong': 0.15,  # >15% slope = strong trend
            'weak': 0.05     # 5-15% = weak trend
        }
        
        # Volatility thresholds (Z-score)
        self.vol_thresholds = {
            'very_low': -1.5,
            'low': -0.5,
            'high': 1.0,
            'extreme': 2.0
        }
        
        # Funding rate thresholds (annualized %)
        self.funding_thresholds = {
            'very_negative': -50,  # < -50% APR
            'negative': -10,
            'positive': 10,
            'very_positive': 50   # > 50% APR
        }
        
        # Historical data for Z-score computation
        self.volatility_history = []
        self.max_history = 500
        
        logger.info("Regime detector initialized")
    
    def detect_regime(self, market_data: Dict) -> RegimeState:
        """
        Classify current market regime.
        
        Args:
            market_data: Dict with:
                - prices: List of recent prices (newest last)
                - funding_rate: Current 8h funding rate (as decimal, e.g., 0.0001)
                - timestamps: Optional timestamps for prices
        
        Returns:
            RegimeState with all regime dimensions
        """
        try:
            # Extract data
            prices = market_data.get('prices', [])
            funding_rate = market_data.get('funding_rate', 0.0)
            
            if len(prices) < 20:
                # Not enough data, return neutral regime
                return self._neutral_regime()
            
            # Detect trend
            trend, trend_strength = self._detect_trend(prices)
            
            # Detect volatility
            volatility, volatility_z = self._detect_volatility(prices)
            
            # Detect funding regime
            funding, funding_pct = self._detect_funding(funding_rate)
            
            # Construct regime tag
            regime_tag = f"{trend.value}_{volatility.value}_{funding.value}"
            
            # Confidence based on data quantity
            confidence = min(1.0, len(prices) / 200)
            
            return RegimeState(
                trend=trend,
                volatility=volatility,
                funding=funding,
                regime_tag=regime_tag,
                trend_strength=trend_strength,
                volatility_z=volatility_z,
                funding_rate_pct=funding_pct,
                confidence=confidence
            )
            
        except Exception as e:
            logger.error(f"Regime detection error: {e}")
            return self._neutral_regime()
    
    def _detect_trend(self, prices: List[float]) -> tuple[TrendRegime, float]:
        """
        Detect trend regime using EMA slope.
        
        Returns:
            (TrendRegime, strength: -1 to +1)
        """
        # Compute short and long EMAs
        prices_arr = np.array(prices)
        ema_short = self._ema(prices_arr, 20)
        ema_long = self._ema(prices_arr, 50)
        
        # Trend strength = (short - long) / long
        trend_strength = (ema_short[-1] - ema_long[-1]) / ema_long[-1]
        
        # Classify
        if trend_strength > self.trend_thresholds['strong']:
            regime = TrendRegime.STRONG_UPTREND
        elif trend_strength > self.trend_thresholds['weak']:
            regime = TrendRegime.WEAK_UPTREND
        elif trend_strength < -self.trend_thresholds['strong']:
            regime = TrendRegime.STRONG_DOWNTREND
        elif trend_strength < -self.trend_thresholds['weak']:
            regime = TrendRegime.WEAK_DOWNTREND
        else:
            regime = TrendRegime.SIDEWAYS
        
        return regime, trend_strength
    
    def _detect_volatility(self, prices: List[float]) -> tuple[VolatilityRegime, float]:
        """
        Detect volatility regime using ATR Z-score.
        
        Returns:
            (VolatilityRegime, z_score)
        """
        # Compute ATR (simplified: std of returns)
        prices_arr = np.array(prices)
        returns = np.diff(prices_arr) / prices_arr[:-1]
        current_vol = np.std(returns[-20:]) if len(returns) >= 20 else np.std(returns)
        
        # Update history
        self.volatility_history.append(current_vol)
        if len(self.volatility_history) > self.max_history:
            self.volatility_history.pop(0)
        
        # Compute Z-score
        if len(self.volatility_history) >= 20:
            mean_vol = np.mean(self.volatility_history)
            std_vol = np.std(self.volatility_history)
            vol_z = (current_vol - mean_vol) / std_vol if std_vol > 0 else 0.0
        else:
            vol_z = 0.0
        
        # Classify
        if vol_z < self.vol_thresholds['very_low']:
            regime = VolatilityRegime.VERY_LOW
        elif vol_z < self.vol_thresholds['low']:
            regime = VolatilityRegime.LOW
        elif vol_z < self.vol_thresholds['high']:
            regime = VolatilityRegime.NORMAL
        elif vol_z < self.vol_thresholds['extreme']:
            regime = VolatilityRegime.HIGH
        else:
            regime = VolatilityRegime.EXTREME
        
        return regime, vol_z
    
    def _detect_funding(self, funding_rate: float) -> tuple[FundingRegime, float]:
        """
        Detect funding regime.
        
        Args:
            funding_rate: 8h funding rate as decimal (e.g., 0.0001 = 0.01%)
        
        Returns:
            (FundingRegime, annualized_pct)
        """
        # Convert to annualized percentage
        # 8h rate × 3 per day × 365 days
        funding_pct = funding_rate * 3 * 365 * 100
        
        # Classify
        if funding_pct < self.funding_thresholds['very_negative']:
            regime = FundingRegime.VERY_NEGATIVE
        elif funding_pct < self.funding_thresholds['negative']:
            regime = FundingRegime.NEGATIVE
        elif funding_pct < self.funding_thresholds['positive']:
            regime = FundingRegime.NEUTRAL
        elif funding_pct < self.funding_thresholds['very_positive']:
            regime = FundingRegime.POSITIVE
        else:
            regime = FundingRegime.VERY_POSITIVE
        
        return regime, funding_pct
    
    def _ema(self, data: np.ndarray, period: int) -> np.ndarray:
        """Compute exponential moving average"""
        alpha = 2 / (period + 1)
        ema = np.zeros(len(data))
        ema[0] = data[0]
        for i in range(1, len(data)):
            ema[i] = alpha * data[i] + (1 - alpha) * ema[i-1]
        return ema
    
    def _neutral_regime(self) -> RegimeState:
        """Return neutral regime when data is insufficient"""
        return RegimeState(
            trend=TrendRegime.SIDEWAYS,
            volatility=VolatilityRegime.NORMAL,
            funding=FundingRegime.NEUTRAL,
            regime_tag="SIDEWAYS_NORMAL_NEUTRAL",
            trend_strength=0.0,
            volatility_z=0.0,
            funding_rate_pct=0.0,
            confidence=0.0
        )
    
    def should_trade(self, regime: RegimeState, trade_side: str) -> tuple[bool, str]:
        """
        Filter trade based on regime.
        
        Args:
            regime: Current regime state
            trade_side: 'LONG' or 'SHORT'
        
        Returns:
            (should_trade: bool, rejection_reason: str)
        """
        # Don't trade in extreme volatility
        if regime.volatility in [VolatilityRegime.EXTREME]:
            return False, "EXTREME_VOLATILITY"
        
        # Don't trade counter to strong trend
        if trade_side == 'LONG' and regime.trend == TrendRegime.STRONG_DOWNTREND:
            return False, "COUNTER_STRONG_DOWNTREND"
        if trade_side == 'SHORT' and regime.trend == TrendRegime.STRONG_UPTREND:
            return False, "COUNTER_STRONG_UPTREND"
        
        # Optional: Fade extreme funding
        # (Don't go LONG when funding is very positive = too crowded)
        if trade_side == 'LONG' and regime.funding == FundingRegime.VERY_POSITIVE:
            return False, "CROWDED_LONG_FUNDING"
        if trade_side == 'SHORT' and regime.funding == FundingRegime.VERY_NEGATIVE:
            return False, "CROWDED_SHORT_FUNDING"
        
        return True, ""


def test_regime_detector():
    """Quick test of regime detector"""
    from types import SimpleNamespace
    
    config = SimpleNamespace()
    detector = RegimeDetector(config)
    
    # Simulate uptrending market
    base = 50000
    prices = [base + i * 100 + np.random.normal(0, 50) for i in range(100)]
    
    market_data = {
        'prices': prices,
        'funding_rate': 0.0001  # Slightly positive
    }
    
    regime = detector.detect_regime(market_data)
    print(f"Regime: {regime}")
    
    # Test filtering
    should_trade, reason = detector.should_trade(regime, 'LONG')
    print(f"Should trade LONG: {should_trade}, reason: {reason}")
    
    should_trade, reason = detector.should_trade(regime, 'SHORT')
    print(f"Should trade SHORT: {should_trade}, reason: {reason}")
    
    print("✅ Regime detector tests passed")


if __name__ == "__main__":
    test_regime_detector()
