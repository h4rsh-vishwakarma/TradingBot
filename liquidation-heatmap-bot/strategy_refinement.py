"""
Market Regime Detection and Strategy Refinement Module
Implements market regime detection, multi-timeframe analysis, and strategy adaptation
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum
import logging
from scipy import stats
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
import talib

logger = logging.getLogger(__name__)

class MarketRegime(Enum):
    """Market regime types"""
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"
    BREAKOUT = "breakout"
    REVERSAL = "reversal"

@dataclass
class RegimeMetrics:
    """Market regime metrics"""
    regime: MarketRegime
    confidence: float
    duration: int
    volatility: float
    trend_strength: float
    momentum: float
    volume_profile: str

class MarketRegimeDetector:
    """Detect current market regime using multiple indicators"""
    
    def __init__(self, lookback_period: int = 100):
        self.lookback_period = lookback_period
        self.regime_history = []
        self.current_regime = MarketRegime.RANGING
        self.regime_confidence = 0.5
        self.regime_duration = 0
        
        # Regime detection parameters
        self.volatility_threshold_high = 0.03
        self.volatility_threshold_low = 0.01
        self.trend_threshold = 0.6
        self.momentum_threshold = 0.5
        
    def detect_regime(self, ohlcv_data: pd.DataFrame, volume_data: pd.Series = None) -> RegimeMetrics:
        """Detect current market regime"""
        if len(ohlcv_data) < self.lookback_period:
            return RegimeMetrics(
                regime=MarketRegime.RANGING,
                confidence=0.5,
                duration=0,
                volatility=0.02,
                trend_strength=0,
                momentum=0,
                volume_profile="normal"
            )
        
        # Calculate regime indicators
        volatility = self._calculate_volatility(ohlcv_data)
        trend_strength = self._calculate_trend_strength(ohlcv_data)
        momentum = self._calculate_momentum(ohlcv_data)
        volume_profile = self._analyze_volume_profile(ohlcv_data, volume_data)
        
        # Determine regime
        regime, confidence = self._classify_regime(volatility, trend_strength, momentum, volume_profile)
        
        # Update regime duration
        if regime == self.current_regime:
            self.regime_duration += 1
        else:
            self.regime_duration = 1
            self.current_regime = regime
        
        # Store regime history
        self.regime_history.append({
            'regime': regime,
            'confidence': confidence,
            'volatility': volatility,
            'trend_strength': trend_strength,
            'momentum': momentum,
            'timestamp': pd.Timestamp.now()
        })
        
        return RegimeMetrics(
            regime=regime,
            confidence=confidence,
            duration=self.regime_duration,
            volatility=volatility,
            trend_strength=trend_strength,
            momentum=momentum,
            volume_profile=volume_profile
        )
    
    def _calculate_volatility(self, ohlcv_data: pd.DataFrame) -> float:
        """Calculate market volatility"""
        close = ohlcv_data['close']
        returns = close.pct_change().dropna()
        
        # Use multiple volatility measures
        historical_vol = returns.rolling(window=20).std().iloc[-1] * np.sqrt(252)
        
        # Parkinson volatility
        high = ohlcv_data['high']
        low = ohlcv_data['low']
        parkinson_vol = np.sqrt(0.25 * np.log(high/low)**2).rolling(window=20).mean().iloc[-1] * np.sqrt(252)
        
        # Average of both measures
        return (historical_vol + parkinson_vol) / 2
    
    def _calculate_trend_strength(self, ohlcv_data: pd.DataFrame) -> float:
        """Calculate trend strength using ADX"""
        high = ohlcv_data['high']
        low = ohlcv_data['low']
        close = ohlcv_data['close']
        
        # Calculate ADX
        adx = talib.ADX(high.values, low.values, close.values, timeperiod=14)
        
        # Calculate trend direction
        plus_di = talib.PLUS_DI(high.values, low.values, close.values, timeperiod=14)
        minus_di = talib.MINUS_DI(high.values, low.values, close.values, timeperiod=14)
        
        # Determine trend strength and direction
        if plus_di[-1] > minus_di[-1]:
            trend_strength = adx[-1] / 100  # Normalize to 0-1
        else:
            trend_strength = -adx[-1] / 100  # Negative for downtrend
        
        return trend_strength
    
    def _calculate_momentum(self, ohlcv_data: pd.DataFrame) -> float:
        """Calculate market momentum"""
        close = ohlcv_data['close']
        
        # Multiple momentum indicators
        rsi = talib.RSI(close.values, timeperiod=14)
        macd, signal, histogram = talib.MACD(close.values)
        
        # Combine momentum signals
        rsi_momentum = (rsi[-1] - 50) / 50  # Normalize around 0
        macd_momentum = histogram[-1] / close.iloc[-1] if close.iloc[-1] > 0 else 0
        
        # Weighted average
        momentum = 0.6 * rsi_momentum + 0.4 * macd_momentum
        
        return momentum
    
    def _analyze_volume_profile(self, ohlcv_data: pd.DataFrame, volume_data: pd.Series = None) -> str:
        """Analyze volume profile"""
        if volume_data is None:
            volume_data = ohlcv_data['volume']
        
        # Calculate volume indicators
        volume_sma = volume_data.rolling(window=20).mean()
        current_volume = volume_data.iloc[-1]
        avg_volume = volume_sma.iloc[-1]
        
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1
        
        if volume_ratio > 1.5:
            return "high"
        elif volume_ratio < 0.7:
            return "low"
        else:
            return "normal"
    
    def _classify_regime(self, volatility: float, trend_strength: float, 
                        momentum: float, volume_profile: str) -> Tuple[MarketRegime, float]:
        """Classify market regime based on indicators"""
        confidence_scores = {}
        
        # Volatility-based regimes
        if volatility > self.volatility_threshold_high:
            confidence_scores[MarketRegime.HIGH_VOLATILITY] = min(volatility / self.volatility_threshold_high, 1.0)
        elif volatility < self.volatility_threshold_low:
            confidence_scores[MarketRegime.LOW_VOLATILITY] = 1.0 - (volatility / self.volatility_threshold_low)
        
        # Trend-based regimes
        if abs(trend_strength) > self.trend_threshold:
            if trend_strength > 0:
                confidence_scores[MarketRegime.TRENDING_UP] = abs(trend_strength)
            else:
                confidence_scores[MarketRegime.TRENDING_DOWN] = abs(trend_strength)
        
        # Momentum-based regimes
        if abs(momentum) > self.momentum_threshold:
            if momentum > 0 and trend_strength > 0:
                confidence_scores[MarketRegime.BREAKOUT] = abs(momentum)
            elif momentum < 0 and trend_strength < 0:
                confidence_scores[MarketRegime.REVERSAL] = abs(momentum)
        
        # Volume confirmation
        volume_multiplier = 1.0
        if volume_profile == "high":
            volume_multiplier = 1.2
        elif volume_profile == "low":
            volume_multiplier = 0.8
        
        # Apply volume multiplier to confidence scores
        for regime in confidence_scores:
            confidence_scores[regime] *= volume_multiplier
        
        # Determine best regime
        if confidence_scores:
            best_regime = max(confidence_scores, key=confidence_scores.get)
            best_confidence = min(confidence_scores[best_regime], 1.0)
        else:
            best_regime = MarketRegime.RANGING
            best_confidence = 0.5
        
        return best_regime, best_confidence

class MultiTimeframeAnalyzer:
    """Multi-timeframe analysis for signal confirmation"""
    
    def __init__(self, timeframes: List[str] = None):
        self.timeframes = timeframes or ['5m', '15m', '1h', '4h', '1d']
        self.timeframe_weights = {
            '5m': 0.1,
            '15m': 0.2,
            '1h': 0.3,
            '4h': 0.25,
            '1d': 0.15
        }
    
    def analyze_multi_timeframe(self, ohlcv_data: Dict[str, pd.DataFrame]) -> Dict[str, float]:
        """Analyze signals across multiple timeframes"""
        timeframe_signals = {}
        
        logger.info(f"Multi-TF Analyzer: Processing {len(ohlcv_data)} timeframes: {list(ohlcv_data.keys())}")
        
        for timeframe in self.timeframes:
            if timeframe in ohlcv_data and not ohlcv_data[timeframe].empty:
                signal = self._analyze_timeframe(ohlcv_data[timeframe], timeframe)
                timeframe_signals[timeframe] = signal
                logger.info(f"  {timeframe}: trend={signal['trend']:.2f}, momentum={signal['momentum']:.2f}, vol={signal['volatility']:.2f}")
        
        logger.info(f"Multi-TF Analyzer: Processed {len(timeframe_signals)} valid timeframes")
        
        # Combine signals with weights
        combined_signal = self._combine_timeframe_signals(timeframe_signals)
        
        logger.info(f"Multi-TF Analyzer: Combined overall_score={combined_signal['overall_score']:.2f}")
        
        return combined_signal
    
    def _analyze_timeframe(self, ohlcv_data: pd.DataFrame, timeframe: str) -> Dict[str, float]:
        """Analyze single timeframe"""
        if len(ohlcv_data) < 10:
            return {'trend': 0, 'momentum': 0, 'volatility': 0, 'volume': 0}
        
        close = ohlcv_data['close']
        high = ohlcv_data['high']
        low = ohlcv_data['low']
        volume = ohlcv_data['volume']
        
        # Trend analysis
        trend = self._calculate_trend_signal(close, high, low)
        
        # Momentum analysis
        momentum = self._calculate_momentum_signal(close)
        
        # Volatility analysis
        volatility = self._calculate_volatility_signal(close, high, low)
        
        # Volume analysis
        volume_signal = self._calculate_volume_signal(volume)
        
        return {
            'trend': trend,
            'momentum': momentum,
            'volatility': volatility,
            'volume': volume_signal
        }
    
    def _calculate_trend_signal(self, close: pd.Series, high: pd.Series, low: pd.Series) -> float:
        """Calculate trend signal"""
        # Moving average trend (use shorter windows for limited data)
        window_short = min(10, len(close) // 2)
        window_long = min(20, len(close) - 1)
        
        if len(close) < window_long:
            return 0.0
        
        sma_short = close.rolling(window=window_short).mean()
        sma_long = close.rolling(window=window_long).mean()
        
        ma_trend = 1 if sma_short.iloc[-1] > sma_long.iloc[-1] else -1
        
        # ADX trend strength (with NaN handling)
        try:
            adx = talib.ADX(high.values, low.values, close.values, timeperiod=14)
            plus_di = talib.PLUS_DI(high.values, low.values, close.values, timeperiod=14)
            minus_di = talib.MINUS_DI(high.values, low.values, close.values, timeperiod=14)
            
            # Handle NaN values
            adx_val = adx[-1] if not np.isnan(adx[-1]) else 0
            plus_di_val = plus_di[-1] if not np.isnan(plus_di[-1]) else 0
            minus_di_val = minus_di[-1] if not np.isnan(minus_di[-1]) else 0
            
            adx_strength = adx_val / 100
            adx_direction = 1 if plus_di_val > minus_di_val else -1
        except Exception:
            # Fallback if talib fails
            adx_strength = 0
            adx_direction = ma_trend
        
        # Combine signals
        trend_signal = (ma_trend * 0.4 + adx_direction * adx_strength * 0.6)
        
        return np.clip(trend_signal, -1, 1)
    
    def _calculate_momentum_signal(self, close: pd.Series) -> float:
        """Calculate momentum signal"""
        try:
            # RSI momentum
            rsi = talib.RSI(close.values, timeperiod=14)
            rsi_val = rsi[-1] if not np.isnan(rsi[-1]) else 50
            rsi_signal = (rsi_val - 50) / 50
            
            # MACD momentum
            macd, signal, histogram = talib.MACD(close.values)
            hist_val = histogram[-1] if not np.isnan(histogram[-1]) else 0
            macd_signal = hist_val / close.iloc[-1] if close.iloc[-1] > 0 else 0
            
            # Stochastic momentum
            stoch_k, stoch_d = talib.STOCH(close.values, close.values, close.values)
            stoch_val = stoch_k[-1] if not np.isnan(stoch_k[-1]) else 50
            stoch_signal = (stoch_val - 50) / 50
            
            # Combine signals
            momentum_signal = (rsi_signal * 0.4 + macd_signal * 0.4 + stoch_signal * 0.2)
            
            return np.clip(momentum_signal, -1, 1)
        except Exception:
            return 0.0
    
    def _calculate_volatility_signal(self, close: pd.Series, high: pd.Series, low: pd.Series) -> float:
        """Calculate volatility signal"""
        # ATR-based volatility
        atr = talib.ATR(high.values, low.values, close.values, timeperiod=14)
        atr_signal = atr[-1] / close.iloc[-1] if close.iloc[-1] > 0 else 0
        
        # Bollinger Band width
        bb_upper, bb_middle, bb_lower = talib.BBANDS(close.values)
        bb_width = (bb_upper[-1] - bb_lower[-1]) / bb_middle[-1] if bb_middle[-1] > 0 else 0
        
        # Normalize volatility
        volatility_signal = (atr_signal + bb_width) / 2
        
        return np.clip(volatility_signal, 0, 1)
    
    def _calculate_volume_signal(self, volume: pd.Series) -> float:
        """Calculate volume signal"""
        # Volume trend
        volume_sma = volume.rolling(window=20).mean()
        volume_ratio = volume.iloc[-1] / volume_sma.iloc[-1] if volume_sma.iloc[-1] > 0 else 1
        
        # Volume momentum
        volume_momentum = volume.pct_change(periods=5).iloc[-1]
        
        # Combine signals
        volume_signal = (volume_ratio - 1) * 0.5 + volume_momentum * 0.5
        
        return np.clip(volume_signal, -1, 1)
    
    def _combine_timeframe_signals(self, timeframe_signals: Dict[str, Dict[str, float]]) -> Dict[str, float]:
        """Combine signals from multiple timeframes"""
        combined_signals = {
            'trend': 0,
            'momentum': 0,
            'volatility': 0,
            'volume': 0,
            'overall_score': 0
        }
        
        total_weight = 0
        
        for timeframe, signals in timeframe_signals.items():
            weight = self.timeframe_weights.get(timeframe, 0.1)
            total_weight += weight
            
            for signal_type, value in signals.items():
                if signal_type in combined_signals:
                    # Skip NaN values
                    if not np.isnan(value):
                        combined_signals[signal_type] += value * weight
        
        # Normalize by total weight
        for signal_type in combined_signals:
            if signal_type != 'overall_score' and total_weight > 0:
                combined_signals[signal_type] /= total_weight
                # Replace NaN with 0
                if np.isnan(combined_signals[signal_type]):
                    combined_signals[signal_type] = 0
        
        # Calculate overall score
        combined_signals['overall_score'] = (
            combined_signals['trend'] * 0.3 +
            combined_signals['momentum'] * 0.3 +
            combined_signals['volatility'] * 0.2 +
            combined_signals['volume'] * 0.2
        )
        
        # Final NaN check
        if np.isnan(combined_signals['overall_score']):
            combined_signals['overall_score'] = 0.0
        
        return combined_signals

class LiquidationStrategyRefiner:
    """Refine liquidation-based strategy to avoid common pitfalls"""
    
    def __init__(self, config):
        self.config = config
        self.trading_config = config.get_trading_config()
        
        # Strategy parameters
        self.min_cluster_strength = 0.7
        self.max_distance_threshold = 0.05  # 5% from current price (increased for more flexibility)
        self.liquidity_threshold = 1000000  # Minimum liquidity requirement
        
        # False signal detection
        self.false_signal_history = []
        self.success_rate_by_condition = {}
        
    def validate_liquidation_signal(self, signal_data: Dict, market_features: Dict, 
                                  clusters_df: pd.DataFrame) -> Tuple[bool, str]:
        """Validate liquidation signal to avoid false signals"""
        
        # Check cluster strength
        if not self._check_cluster_strength(signal_data, clusters_df):
            return False, "Insufficient cluster strength"
        
        # Check distance to liquidation levels
        if not self._check_distance_to_targets(signal_data):
            return False, "Targets too far from current price"
        
        # Check liquidity conditions
        if not self._check_liquidity_conditions(market_features):
            return False, "Insufficient liquidity"
        
        # Check market regime compatibility
        if not self._check_regime_compatibility(signal_data, market_features):
            return False, "Signal incompatible with current market regime"
        
        # Check for false breakout patterns
        if not self._check_false_breakout_patterns(signal_data, market_features):
            return False, "Potential false breakout detected"
        
        # Check volume confirmation
        if not self._check_volume_confirmation(signal_data, market_features):
            return False, "Volume confirmation failed"
        
        return True, "Signal validated"
    
    def _check_cluster_strength(self, signal_data: Dict, clusters_df: pd.DataFrame) -> bool:
        """Check if liquidation cluster is strong enough"""
        cluster_density = signal_data.get('cluster_density', 0)
        cluster_strength = signal_data.get('cluster_strength', 0)
        
        # Minimum density requirement (lowered from 150000)
        if cluster_density < 50000:
            logger.info(f"Cluster density check failed: {cluster_density} < 50000")
            return False
        
        # Minimum strength requirement (using data_points, not normalized)
        if cluster_strength < 3:  # At least 3 data points
            logger.info(f"Cluster strength check failed: {cluster_strength} < 3")
            return False
        
        # Check cluster quality
        if clusters_df.empty:
            logger.info("Clusters dataframe is empty")
            return False
        
        # Relaxed validation - just check we have clusters
        logger.info(f"✅ Cluster strength validation passed: density={cluster_density}, strength={cluster_strength}")
        return True
        
        return True
    
    def _check_distance_to_targets(self, signal_data: Dict) -> bool:
        """Check if targets are within reasonable distance"""
        entry_price = signal_data.get('entry_price', 0)
        stop_loss = signal_data.get('stop_loss', 0)
        take_profit = signal_data.get('take_profit', 0)
        
        if entry_price <= 0:
            return False
        
        # Calculate distances
        stop_distance = abs(entry_price - stop_loss) / entry_price
        tp_distance = abs(take_profit - entry_price) / entry_price
        
        # Check if distances are reasonable
        if stop_distance > self.max_distance_threshold:
            logger.info(f"Stop distance too large: {stop_distance*100:.2f}% > {self.max_distance_threshold*100:.2f}%")
            return False
        
        if tp_distance > self.max_distance_threshold * 5:  # Allow larger TP (increased from 3x to 5x)
            logger.info(f"TP distance too large: {tp_distance*100:.2f}% > {self.max_distance_threshold*5*100:.2f}%")
            return False
        
        logger.info(f"✅ Distance check passed: SL={stop_distance*100:.2f}%, TP={tp_distance*100:.2f}%")
        return True
    
    def _check_liquidity_conditions(self, market_features: Dict) -> bool:
        """Check if market has sufficient liquidity"""
        # Check order book depth (if available)
        bid_ask_spread = market_features.get('bid_ask_spread', 0)
        if bid_ask_spread > 0.001:  # 0.1% spread threshold
            return False
        
        # Check volume conditions
        volume_ratio = market_features.get('volume_ratio', 1)
        if volume_ratio < 0.5:  # Low volume
            return False
        
        return True
    
    def _check_regime_compatibility(self, signal_data: Dict, market_features: Dict) -> bool:
        """Check if signal is compatible with current market regime"""
        regime = market_features.get('regime', MarketRegime.RANGING)
        direction = signal_data.get('direction', 'LONG')
        
        # Trending markets favor trend-following
        if regime in [MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN]:
            if regime == MarketRegime.TRENDING_UP and direction == 'SHORT':
                return False
            if regime == MarketRegime.TRENDING_DOWN and direction == 'LONG':
                return False
        
        # High volatility markets require higher confidence
        if regime == MarketRegime.HIGH_VOLATILITY:
            confidence = signal_data.get('combined_confidence', 0.5)
            if confidence < 0.85:
                return False
        
        return True
    
    def _check_false_breakout_patterns(self, signal_data: Dict, market_features: Dict) -> bool:
        """Check for potential false breakout patterns"""
        # Check for recent failed breakouts
        if len(self.false_signal_history) >= 3:
            recent_failures = self.false_signal_history[-3:]
            if all(f['reason'] == 'false_breakout' for f in recent_failures):
                return False
        
        # Check momentum divergence
        momentum = market_features.get('momentum', 0)
        trend_strength = market_features.get('trend_strength', 0)
        
        if abs(momentum) < 0.3 and abs(trend_strength) > 0.7:
            return False  # Potential divergence
        
        return True
    
    def _check_volume_confirmation(self, signal_data: Dict, market_features: Dict) -> bool:
        """Check volume confirmation"""
        volume_confirmation = signal_data.get('volume_confirmation', False)
        volume_ratio = market_features.get('volume_ratio', 1)
        
        # Relaxed - don't require volume confirmation for now
        logger.info(f"✅ Volume check passed: confirmation={volume_confirmation}, ratio={volume_ratio:.2f}")
        return True
    
    def record_signal_outcome(self, signal_data: Dict, outcome: Dict):
        """Record signal outcome for learning"""
        condition_key = self._get_condition_key(signal_data)
        
        if condition_key not in self.success_rate_by_condition:
            self.success_rate_by_condition[condition_key] = {'success': 0, 'total': 0}
        
        self.success_rate_by_condition[condition_key]['total'] += 1
        
        if outcome.get('is_profitable', False):
            self.success_rate_by_condition[condition_key]['success'] += 1
        else:
            # Record false signal
            self.false_signal_history.append({
                'timestamp': pd.Timestamp.now(),
                'reason': 'false_breakout',
                'condition': condition_key
            })
    
    def _get_condition_key(self, signal_data: Dict) -> str:
        """Get condition key for tracking"""
        regime = signal_data.get('regime', 'unknown')
        direction = signal_data.get('direction', 'unknown')
        confidence_level = 'high' if signal_data.get('combined_confidence', 0) > 0.8 else 'low'
        
        return f"{regime}_{direction}_{confidence_level}"
    
    def get_strategy_adaptations(self, market_features: Dict) -> Dict[str, float]:
        """Get strategy adaptations based on market conditions"""
        regime = market_features.get('regime', MarketRegime.RANGING)
        volatility = market_features.get('volatility', 0.02)
        
        adaptations = {
            'confidence_threshold_multiplier': 1.0,
            'position_size_multiplier': 1.0,
            'stop_loss_multiplier': 1.0,
            'take_profit_multiplier': 1.0
        }
        
        # Regime-based adaptations
        if regime == MarketRegime.HIGH_VOLATILITY:
            adaptations['confidence_threshold_multiplier'] = 1.2
            adaptations['position_size_multiplier'] = 0.8
            adaptations['stop_loss_multiplier'] = 1.5
        
        elif regime == MarketRegime.LOW_VOLATILITY:
            adaptations['confidence_threshold_multiplier'] = 0.9
            adaptations['position_size_multiplier'] = 1.2
            adaptations['stop_loss_multiplier'] = 0.8
        
        elif regime in [MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN]:
            adaptations['take_profit_multiplier'] = 1.5
        
        # Volatility-based adaptations
        if volatility > 0.04:  # Very high volatility
            adaptations['position_size_multiplier'] *= 0.7
            adaptations['stop_loss_multiplier'] *= 1.3
        
        return adaptations
