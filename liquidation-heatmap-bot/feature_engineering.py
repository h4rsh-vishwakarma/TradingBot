"""
Enhanced Feature Engineering Module
Implements advanced market features for RL trading bot
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import talib
from scipy import stats
import logging

logger = logging.getLogger(__name__)

@dataclass
class MarketFeatures:
    """Container for market features"""
    # Price features
    price_features: Dict[str, float]
    
    # Volume features
    volume_features: Dict[str, float]
    
    # Volatility features
    volatility_features: Dict[str, float]
    
    # Market microstructure features
    microstructure_features: Dict[str, float]
    
    # Time-based features
    time_features: Dict[str, float]
    
    # Cross-asset features
    cross_asset_features: Dict[str, float]
    
    # Liquidation features
    liquidation_features: Dict[str, float]
    
    def normalize_features(self) -> Dict[str, float]:
        """Normalize features for ML model"""
        normalized = {}
        
        # Combine all features
        all_features = {
            **self.price_features,
            **self.volume_features,
            **self.volatility_features,
            **self.microstructure_features,
            **self.time_features,
            **self.cross_asset_features,
            **self.liquidation_features
        }
        
        # Apply normalization
        for key, value in all_features.items():
            if isinstance(value, (int, float)) and not np.isnan(value):
                # Simple min-max normalization for most features
                if 'ratio' in key or 'correlation' in key:
                    normalized[key] = np.clip(value, -1, 1)
                elif 'volatility' in key:
                    normalized[key] = np.clip(value, 0, 2)  # Cap at 200% annualized
                elif 'distance' in key:
                    normalized[key] = np.clip(value, 0, 0.1)  # Cap at 10%
                else:
                    normalized[key] = np.clip(value, -2, 2)  # General cap
            else:
                normalized[key] = 0
        
        return normalized

class TechnicalIndicators:
    """Technical analysis indicators"""
    
    @staticmethod
    def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        """Calculate Average True Range"""
        return talib.ATR(high.values, low.values, close.values, timeperiod=period)
    
    @staticmethod
    def calculate_bollinger_bands(close: pd.Series, period: int = 20, std_dev: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Calculate Bollinger Bands"""
        upper, middle, lower = talib.BBANDS(close.values, timeperiod=period, nbdevup=std_dev, nbdevdn=std_dev)
        return pd.Series(upper), pd.Series(middle), pd.Series(lower)
    
    @staticmethod
    def calculate_rsi(close: pd.Series, period: int = 14) -> pd.Series:
        """Calculate RSI"""
        return pd.Series(talib.RSI(close.values, timeperiod=period))
    
    @staticmethod
    def calculate_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Calculate MACD"""
        macd, signal_line, histogram = talib.MACD(close.values, fastperiod=fast, slowperiod=slow, signalperiod=signal)
        return pd.Series(macd), pd.Series(signal_line), pd.Series(histogram)
    
    @staticmethod
    def calculate_stochastic(high: pd.Series, low: pd.Series, close: pd.Series, k_period: int = 14, d_period: int = 3) -> Tuple[pd.Series, pd.Series]:
        """Calculate Stochastic Oscillator"""
        k_percent, d_percent = talib.STOCH(high.values, low.values, close.values, 
                                          fastk_period=k_period, slowk_period=d_period, slowd_period=d_period)
        return pd.Series(k_percent), pd.Series(d_percent)
    
    @staticmethod
    def calculate_squeeze_momentum(high: pd.Series, low: pd.Series, close: pd.Series, 
                                  bb_length: int = 20, bb_mult: float = 2.0,
                                  kc_length: int = 20, kc_mult: float = 1.5) -> Dict[str, float]:
        """Calculate Squeeze Momentum Indicator [LazyBear]
        
        Detects low volatility consolidation (squeeze) and explosive momentum releases.
        Returns squeeze state and momentum histogram value.
        """
        try:
            # Bollinger Bands
            bb_upper, bb_middle, bb_lower = talib.BBANDS(close.values, timeperiod=bb_length, 
                                                          nbdevup=bb_mult, nbdevdn=bb_mult)
            
            # Keltner Channels (ATR-based)
            atr = talib.ATR(high.values, low.values, close.values, timeperiod=kc_length)
            kc_middle = talib.SMA(close.values, timeperiod=kc_length)
            kc_upper = kc_middle + (kc_mult * atr)
            kc_lower = kc_middle - (kc_mult * atr)
            
            # Squeeze detection: BB inside KC = squeeze ON
            squeeze_on = (bb_lower[-1] > kc_lower[-1]) and (bb_upper[-1] < kc_upper[-1])
            squeeze_release = not squeeze_on and (bb_lower[-2] > kc_lower[-2]) and (bb_upper[-2] < kc_upper[-2])
            
            # Momentum calculation: Linear regression of price
            # Using close price deviation from basis
            length = 20
            if len(close) < length:
                return {'squeeze_on': False, 'momentum': 0, 'momentum_trend': 0, 'squeeze_release': False}
            
            # Linear regression for momentum
            src = close.values[-length:]
            x = np.arange(length)
            slope, intercept, _, _, _ = stats.linregress(x, src)
            linreg = intercept + slope * x
            
            # Momentum is deviation from linear regression
            momentum = src[-1] - linreg[-1]
            
            # Momentum trend (positive or negative)
            if len(close) >= length + 1:
                prev_src = close.values[-length-1:-1]
                prev_linreg_slope, prev_linreg_intercept, _, _, _ = stats.linregress(x, prev_src)
                prev_linreg = prev_linreg_intercept + prev_linreg_slope * x
                prev_momentum = prev_src[-1] - prev_linreg[-1]
                momentum_trend = 1 if momentum > prev_momentum else -1
            else:
                momentum_trend = 0
            
            return {
                'squeeze_on': squeeze_on,
                'momentum': float(momentum),
                'momentum_trend': momentum_trend,
                'squeeze_release': squeeze_release
            }
        except Exception as e:
            logger.warning(f"Squeeze Momentum calculation error: {e}")
            return {'squeeze_on': False, 'momentum': 0, 'momentum_trend': 0, 'squeeze_release': False}
    
    @staticmethod
    def calculate_wavetrend(high: pd.Series, low: pd.Series, close: pd.Series,
                           channel_length: int = 10, average_length: int = 21,
                           overbought: float = 60, oversold: float = -60) -> Dict[str, float]:
        """Calculate WaveTrend Oscillator [LazyBear]
        
        Mean reversion oscillator for overbought/oversold detection.
        Returns WT1, WT2 lines and signal state.
        """
        try:
            # Typical price
            hlc3 = (high + low + close) / 3
            
            # EMA of typical price
            esa = hlc3.ewm(span=channel_length, adjust=False).mean()
            
            # Absolute deviation
            d = (hlc3 - esa).abs()
            d_ema = d.ewm(span=channel_length, adjust=False).mean()
            
            # Normalized price (CI)
            ci = (hlc3 - esa) / (0.015 * d_ema)
            ci = ci.fillna(0)
            
            # Smoothed CI (WT1)
            wt1 = ci.ewm(span=average_length, adjust=False).mean()
            
            # Signal line (WT2) - SMA of WT1
            wt2 = wt1.rolling(window=4).mean()
            
            # Get current values
            current_wt1 = wt1.iloc[-1] if not wt1.empty else 0
            current_wt2 = wt2.iloc[-1] if not wt2.empty else 0
            
            # Signal generation
            # Long: WT1 crosses above WT2 in oversold zone
            # Short: WT1 crosses below WT2 in overbought zone
            wt1_prev = wt1.iloc[-2] if len(wt1) >= 2 else current_wt1
            wt2_prev = wt2.iloc[-2] if len(wt2) >= 2 else current_wt2
            
            signal = 0  # 0 = neutral, 1 = long, -1 = short
            if current_wt1 > current_wt2 and wt1_prev <= wt2_prev:
                # Bullish cross
                if current_wt1 < oversold:
                    signal = 1  # Strong long signal in oversold
                elif current_wt1 < 0:
                    signal = 0.5  # Weak long signal below zero
            elif current_wt1 < current_wt2 and wt1_prev >= wt2_prev:
                # Bearish cross
                if current_wt1 > overbought:
                    signal = -1  # Strong short signal in overbought
                elif current_wt1 > 0:
                    signal = -0.5  # Weak short signal above zero
            
            # Zone detection
            overbought_zone = current_wt1 > overbought
            oversold_zone = current_wt1 < oversold
            
            # Momentum (difference between WT1 and WT2)
            wt_momentum = current_wt1 - current_wt2
            
            return {
                'wt1': float(current_wt1),
                'wt2': float(current_wt2),
                'signal': float(signal),
                'overbought_zone': overbought_zone,
                'oversold_zone': oversold_zone,
                'wt_momentum': float(wt_momentum)
            }
        except Exception as e:
            logger.warning(f"WaveTrend calculation error: {e}")
            return {'wt1': 0, 'wt2': 0, 'signal': 0, 'overbought_zone': False, 
                   'oversold_zone': False, 'wt_momentum': 0}
    
    @staticmethod
    def calculate_smart_money_concepts(high: pd.Series, low: pd.Series, close: pd.Series,
                                      swing_length: int = 5) -> Dict[str, float]:
        """Calculate Smart Money Concepts (SMC) features
        
        Detects market structure: BOS (Break of Structure), CHoCH (Change of Character),
        Order Blocks, and Fair Value Gaps (FVG).
        """
        try:
            if len(close) < swing_length * 2:
                return {'bos': 0, 'choch': 0, 'order_block_distance': 0, 
                       'fvg_present': False, 'market_structure': 0}
            
            # Market structure: identify swing highs and lows
            swing_highs = []
            swing_lows = []
            
            for i in range(swing_length, len(high) - swing_length):
                # Swing high: highest point in window
                if high.iloc[i] == high.iloc[i-swing_length:i+swing_length+1].max():
                    swing_highs.append((i, high.iloc[i]))
                
                # Swing low: lowest point in window
                if low.iloc[i] == low.iloc[i-swing_length:i+swing_length+1].min():
                    swing_lows.append((i, low.iloc[i]))
            
            # BOS and CHoCH detection
            bos = 0  # Break of Structure
            choch = 0  # Change of Character
            market_structure = 0  # 1 = bullish, -1 = bearish, 0 = neutral
            
            if len(swing_highs) >= 2 and len(swing_lows) >= 2:
                # Recent highs and lows
                recent_high = swing_highs[-1][1]
                prev_high = swing_highs[-2][1]
                recent_low = swing_lows[-1][1]
                prev_low = swing_lows[-2][1]
                
                current_price = close.iloc[-1]
                
                # Bullish structure: Higher Highs and Higher Lows
                if recent_high > prev_high and recent_low > prev_low:
                    market_structure = 1
                    if current_price > recent_high:
                        bos = 1  # Bullish BOS
                
                # Bearish structure: Lower Highs and Lower Lows
                elif recent_high < prev_high and recent_low < prev_low:
                    market_structure = -1
                    if current_price < recent_low:
                        bos = -1  # Bearish BOS
                
                # CHoCH: Structure change
                # Bullish CHoCH: In downtrend, price breaks above previous lower high
                if market_structure == -1 and current_price > prev_high:
                    choch = 1
                # Bearish CHoCH: In uptrend, price breaks below previous higher low
                elif market_structure == 1 and current_price < prev_low:
                    choch = -1
            
            # Order Block detection (last strong move before reversal)
            order_block_distance = 0
            if len(swing_lows) >= 1:
                last_swing_low = swing_lows[-1][1]
                order_block_distance = (close.iloc[-1] - last_swing_low) / close.iloc[-1]
            
            # Fair Value Gap (FVG) detection
            # FVG = 3-candle imbalance (gap between candle 1 high and candle 3 low)
            fvg_present = False
            if len(close) >= 3:
                # Bullish FVG: Gap up
                if low.iloc[-1] > high.iloc[-3]:
                    fvg_present = True
                # Bearish FVG: Gap down
                elif high.iloc[-1] < low.iloc[-3]:
                    fvg_present = True
            
            return {
                'bos': float(bos),
                'choch': float(choch),
                'order_block_distance': float(order_block_distance),
                'fvg_present': fvg_present,
                'market_structure': float(market_structure)
            }
        except Exception as e:
            logger.warning(f"SMC calculation error: {e}")
            return {'bos': 0, 'choch': 0, 'order_block_distance': 0, 
                   'fvg_present': False, 'market_structure': 0}
    
    @staticmethod
    def calculate_supertrend(high: pd.Series, low: pd.Series, close: pd.Series,
                            atr_period: int = 10, atr_multiplier: float = 3.0) -> Dict[str, float]:
        """Calculate SuperTrend Indicator
        
        Trend-following indicator using ATR-based volatility stops.
        Returns trend direction and signal state.
        """
        try:
            # Calculate ATR
            atr = talib.ATR(high.values, low.values, close.values, timeperiod=atr_period)
            
            # Calculate basic bands
            hl2 = (high + low) / 2
            upper_band = hl2 + (atr_multiplier * atr)
            lower_band = hl2 - (atr_multiplier * atr)
            
            # Initialize SuperTrend
            supertrend = pd.Series(index=close.index, dtype=float)
            direction = pd.Series(index=close.index, dtype=int)
            
            # First value
            supertrend.iloc[0] = upper_band.iloc[0]
            direction.iloc[0] = 1
            
            # Calculate SuperTrend line
            for i in range(1, len(close)):
                # Update bands based on previous close
                if close.iloc[i-1] <= supertrend.iloc[i-1]:
                    # Downtrend
                    supertrend.iloc[i] = min(upper_band.iloc[i], supertrend.iloc[i-1]) if upper_band.iloc[i] < supertrend.iloc[i-1] else upper_band.iloc[i]
                    direction.iloc[i] = -1
                else:
                    # Uptrend
                    supertrend.iloc[i] = max(lower_band.iloc[i], supertrend.iloc[i-1]) if lower_band.iloc[i] > supertrend.iloc[i-1] else lower_band.iloc[i]
                    direction.iloc[i] = 1
                
                # Check for trend reversal
                if close.iloc[i] > supertrend.iloc[i-1] and direction.iloc[i-1] == -1:
                    direction.iloc[i] = 1  # Trend change to bullish
                    supertrend.iloc[i] = lower_band.iloc[i]
                elif close.iloc[i] < supertrend.iloc[i-1] and direction.iloc[i-1] == 1:
                    direction.iloc[i] = -1  # Trend change to bearish
                    supertrend.iloc[i] = upper_band.iloc[i]
            
            # Get current values
            current_direction = direction.iloc[-1]
            current_supertrend = supertrend.iloc[-1]
            current_price = close.iloc[-1]
            
            # Signal generation
            prev_direction = direction.iloc[-2] if len(direction) >= 2 else current_direction
            signal = 0
            if current_direction == 1 and prev_direction == -1:
                signal = 1  # Buy signal
            elif current_direction == -1 and prev_direction == 1:
                signal = -1  # Sell signal
            
            # Distance from SuperTrend (for position sizing / stop loss)
            distance_pct = abs(current_price - current_supertrend) / current_price
            
            return {
                'direction': float(current_direction),
                'signal': float(signal),
                'distance_pct': float(distance_pct),
                'in_uptrend': current_direction == 1,
                'supertrend_value': float(current_supertrend)
            }
        except Exception as e:
            logger.warning(f"SuperTrend calculation error: {e}")
            return {'direction': 0, 'signal': 0, 'distance_pct': 0, 
                   'in_uptrend': False, 'supertrend_value': 0}

class VolumeAnalysis:
    """Volume-based analysis"""
    
    @staticmethod
    def calculate_cvd(close: pd.Series, volume: pd.Series, period: int = 50) -> pd.Series:
        """Calculate Cumulative Volume Delta"""
        price_change = close.diff()
        volume_delta = np.where(price_change > 0, volume, 
                               np.where(price_change < 0, -volume, 0))
        cvd = pd.Series(volume_delta).cumsum()
        return cvd.rolling(window=period).mean()
    
    @staticmethod
    def calculate_volume_profile(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, bins: int = 20) -> Dict[str, float]:
        """Calculate volume profile features"""
        price_range = high.max() - low.min()
        bin_size = price_range / bins
        
        volume_profile = {}
        for i in range(bins):
            price_level = low.min() + (i + 0.5) * bin_size
            mask = (high >= price_level - bin_size/2) & (low <= price_level + bin_size/2)
            level_volume = volume[mask].sum()
            volume_profile[f'volume_level_{i}'] = level_volume
        
        # Calculate volume-weighted average price
        vwap_calc = (high + low + close) / 3
        volume_profile['vwap'] = (vwap_calc * volume).sum() / volume.sum()
        
        return volume_profile
    
    @staticmethod
    def calculate_volume_indicators(volume: pd.Series, close: pd.Series, period: int = 20) -> Dict[str, float]:
        """Calculate volume-based indicators"""
        volume_sma = volume.rolling(window=period).mean()
        volume_ratio = volume.iloc[-1] / volume_sma.iloc[-1] if volume_sma.iloc[-1] > 0 else 1.0
        
        # Volume-price trend
        vpt = (volume * close.pct_change()).cumsum()
        vpt_sma = vpt.rolling(window=period).mean()
        vpt_ratio = vpt.iloc[-1] / vpt_sma.iloc[-1] if vpt_sma.iloc[-1] > 0 else 1.0
        
        return {
            'volume_ratio': volume_ratio,
            'vpt_ratio': vpt_ratio,
            'volume_trend': 1 if volume.iloc[-1] > volume_sma.iloc[-1] else -1
        }

class VolatilityAnalysis:
    """Volatility-based analysis"""
    
    @staticmethod
    def calculate_volatility_features(close: pd.Series, high: pd.Series, low: pd.Series, period: int = 20) -> Dict[str, float]:
        """Calculate comprehensive volatility features"""
        returns = close.pct_change().dropna()
        
        # Historical volatility
        hist_vol = returns.rolling(window=period).std() * np.sqrt(252)
        
        # Parkinson volatility (using high-low)
        parkinson_vol = np.sqrt(0.25 * np.log(high/low)**2).rolling(window=period).mean() * np.sqrt(252)
        
        # Garman-Klass volatility
        gk_vol = np.sqrt(0.5 * np.log(high/low)**2 - (2*np.log(2)-1) * np.log(close/close.shift(1))**2).rolling(window=period).mean() * np.sqrt(252)
        
        # Volatility of volatility
        vol_of_vol = hist_vol.rolling(window=period).std()
        
        # Volatility regime
        vol_percentile = hist_vol.rolling(window=period*5).rank(pct=True)
        
        return {
            'historical_volatility': hist_vol.iloc[-1] if not hist_vol.empty else 0,
            'parkinson_volatility': parkinson_vol.iloc[-1] if not parkinson_vol.empty else 0,
            'gk_volatility': gk_vol.iloc[-1] if not gk_vol.empty else 0,
            'vol_of_vol': vol_of_vol.iloc[-1] if not vol_of_vol.empty else 0,
            'vol_percentile': vol_percentile.iloc[-1] if not vol_percentile.empty else 0.5,
            'vol_regime': 1 if vol_percentile.iloc[-1] > 0.8 else -1 if vol_percentile.iloc[-1] < 0.2 else 0
        }

class MarketMicrostructure:
    """Market microstructure analysis"""
    
    @staticmethod
    def calculate_order_flow_imbalance(bid_prices: List[float], ask_prices: List[float], 
                                     bid_volumes: List[float], ask_volumes: List[float]) -> Dict[str, float]:
        """Calculate order flow imbalance"""
        if not bid_prices or not ask_prices:
            return {'order_flow_imbalance': 0, 'bid_ask_spread': 0, 'mid_price': 0}
        
        # Calculate weighted mid price
        bid_volume_weighted = sum(p * v for p, v in zip(bid_prices, bid_volumes)) / sum(bid_volumes)
        ask_volume_weighted = sum(p * v for p, v in zip(ask_prices, ask_volumes)) / sum(ask_volumes)
        mid_price = (bid_volume_weighted + ask_volume_weighted) / 2
        
        # Order flow imbalance
        total_bid_volume = sum(bid_volumes)
        total_ask_volume = sum(ask_volumes)
        imbalance = (total_bid_volume - total_ask_volume) / (total_bid_volume + total_ask_volume) if (total_bid_volume + total_ask_volume) > 0 else 0
        
        # Bid-ask spread
        spread = (ask_prices[0] - bid_prices[0]) / mid_price if mid_price > 0 else 0
        
        return {
            'order_flow_imbalance': imbalance,
            'bid_ask_spread': spread,
            'mid_price': mid_price,
            'bid_ask_ratio': total_bid_volume / total_ask_volume if total_ask_volume > 0 else 1
        }
    
    @staticmethod
    def calculate_tick_analysis(price_changes: List[float], volumes: List[float]) -> Dict[str, float]:
        """Analyze tick-by-tick data"""
        if not price_changes:
            return {'tick_imbalance': 0, 'tick_momentum': 0, 'tick_volatility': 0}
        
        # Tick imbalance (up ticks vs down ticks)
        up_ticks = sum(1 for change in price_changes if change > 0)
        down_ticks = sum(1 for change in price_changes if change < 0)
        tick_imbalance = (up_ticks - down_ticks) / len(price_changes) if price_changes else 0
        
        # Volume-weighted tick momentum
        volume_weighted_changes = [change * vol for change, vol in zip(price_changes, volumes)]
        tick_momentum = sum(volume_weighted_changes) / sum(volumes) if volumes else 0
        
        # Tick volatility
        tick_volatility = np.std(price_changes) if len(price_changes) > 1 else 0
        
        return {
            'tick_imbalance': tick_imbalance,
            'tick_momentum': tick_momentum,
            'tick_volatility': tick_volatility,
            'tick_frequency': len(price_changes)  # ticks per period
        }

class TimeBasedFeatures:
    """Time-based feature engineering"""
    
    @staticmethod
    def calculate_time_features(timestamp: pd.Timestamp) -> Dict[str, float]:
        """Calculate time-based features"""
        hour = timestamp.hour
        day_of_week = timestamp.dayofweek
        day_of_month = timestamp.day
        
        # Cyclical encoding
        hour_sin = np.sin(2 * np.pi * hour / 24)
        hour_cos = np.cos(2 * np.pi * hour / 24)
        day_sin = np.sin(2 * np.pi * day_of_week / 7)
        day_cos = np.cos(2 * np.pi * day_of_week / 7)
        
        # Market session features
        is_asian_session = 0 <= hour < 8
        is_european_session = 8 <= hour < 16
        is_american_session = 16 <= hour < 24
        
        # Weekend effect
        is_weekend = day_of_week >= 5
        
        # Month-end effect
        is_month_end = day_of_month >= 28
        
        return {
            'hour_sin': hour_sin,
            'hour_cos': hour_cos,
            'day_sin': day_sin,
            'day_cos': day_cos,
            'is_asian_session': 1 if is_asian_session else 0,
            'is_european_session': 1 if is_european_session else 0,
            'is_american_session': 1 if is_american_session else 0,
            'is_weekend': 1 if is_weekend else 0,
            'is_month_end': 1 if is_month_end else 0,
            'hour': hour,
            'day_of_week': day_of_week
        }

class CrossAssetAnalysis:
    """Cross-asset correlation analysis"""
    
    @staticmethod
    def calculate_correlation_features(btc_prices: pd.Series, eth_prices: pd.Series = None, 
                                     dxy_prices: pd.Series = None, period: int = 50) -> Dict[str, float]:
        """Calculate cross-asset correlation features (BTC-focused)"""
        features = {}
        
        # ETH correlation logic removed - focusing only on BTC
        # if eth_prices is not None and len(eth_prices) >= period:
        #     btc_returns = btc_prices.pct_change().dropna()
        #     eth_returns = eth_prices.pct_change().dropna()
        #     
        #     # Align the series
        #     min_length = min(len(btc_returns), len(eth_returns))
        #     btc_aligned = btc_returns.tail(min_length)
        #     eth_aligned = eth_returns.tail(min_length)
        #     
        #     if min_length >= period:
        #         correlation = btc_aligned.rolling(window=period).corr(eth_aligned).iloc[-1]
        #         features['btc_eth_correlation'] = correlation if not np.isnan(correlation) else 0
        #         
        #         # Ratio analysis
        #         btc_eth_ratio = btc_prices.iloc[-1] / eth_prices.iloc[-1] if eth_prices.iloc[-1] > 0 else 0
        #         ratio_ma = (btc_prices / eth_prices).rolling(window=period).mean().iloc[-1]
        #         features['btc_eth_ratio'] = btc_eth_ratio
        #         features['btc_eth_ratio_deviation'] = (btc_eth_ratio - ratio_ma) / ratio_ma if ratio_ma > 0 else 0
        
        if dxy_prices is not None and len(dxy_prices) >= period:
            btc_returns = btc_prices.pct_change().dropna()
            dxy_returns = dxy_prices.pct_change().dropna()
            
            # Align the series
            min_length = min(len(btc_returns), len(dxy_returns))
            btc_aligned = btc_returns.tail(min_length)
            dxy_aligned = dxy_returns.tail(min_length)
            
            if min_length >= period:
                correlation = btc_aligned.rolling(window=period).corr(dxy_aligned).iloc[-1]
                features['btc_dxy_correlation'] = correlation if not np.isnan(correlation) else 0
        
        return features

class LiquidationFeatureExtractor:
    """Extract features from liquidation data"""
    
    @staticmethod
    def extract_liquidation_features(clusters_df: pd.DataFrame, current_price: float) -> Dict[str, float]:
        """Extract comprehensive liquidation features"""
        if clusters_df.empty:
            return {
                'cluster_density': 0,
                'cluster_strength': 0,
                'cluster_width': 0,
                'nearest_cluster_distance': 0,
                'cluster_imbalance': 0,
                'liquidation_pressure': 0
            }
        
        # Basic cluster features
        total_density = clusters_df['density'].sum()
        avg_strength = clusters_df.get('strength_score', clusters_df['density']).mean()
        avg_width = clusters_df.get('width', pd.Series([0.001] * len(clusters_df))).mean()
        
        # Distance to nearest cluster
        price_col = clusters_df.get('mean_price', clusters_df.get('price', pd.Series([current_price] * len(clusters_df))))
        clusters_df['distance'] = abs(price_col - current_price)
        nearest_cluster = clusters_df.loc[clusters_df['distance'].idxmin()]
        nearest_distance = nearest_cluster['distance'] / current_price if current_price > 0 else 0
        
        # Cluster imbalance (long vs short) - handle missing cluster_type column
        cluster_type_col = clusters_df.get('cluster_type', pd.Series(['MIXED'] * len(clusters_df)))
        long_clusters = clusters_df[cluster_type_col == 'LONG_HEAVY']
        short_clusters = clusters_df[cluster_type_col == 'SHORT_HEAVY']
        
        long_density = long_clusters['density'].sum()
        short_density = short_clusters['density'].sum()
        total_cluster_density = long_density + short_density
        
        cluster_imbalance = (long_density - short_density) / total_cluster_density if total_cluster_density > 0 else 0
        
        # Liquidation pressure (clusters above/below current price)
        price_col = clusters_df.get('mean_price', clusters_df.get('price', pd.Series([current_price] * len(clusters_df))))
        above_clusters = clusters_df[price_col > current_price]
        below_clusters = clusters_df[price_col < current_price]
        
        above_pressure = above_clusters['density'].sum()
        below_pressure = below_clusters['density'].sum()
        
        liquidation_pressure = (above_pressure - below_pressure) / (above_pressure + below_pressure) if (above_pressure + below_pressure) > 0 else 0
        
        return {
            'cluster_density': total_density / 1000000,  # Normalize
            'cluster_strength': avg_strength / 100000,   # Normalize
            'cluster_width': avg_width / 1000,          # Normalize
            'nearest_cluster_distance': nearest_distance,
            'cluster_imbalance': cluster_imbalance,
            'liquidation_pressure': liquidation_pressure,
            'cluster_count': len(clusters_df),
            'strong_cluster_count': len(clusters_df[clusters_df['density'] >= 150000])
        }

class FeatureEngine:
    """Main feature engineering engine"""
    
    def __init__(self, config):
        self.config = config
        self.feature_config = config.get_feature_config()
        
        # Initialize analyzers
        self.technical_indicators = TechnicalIndicators()
        self.volume_analysis = VolumeAnalysis()
        self.volatility_analysis = VolatilityAnalysis()
        self.microstructure = MarketMicrostructure()
        self.time_features = TimeBasedFeatures()
        self.cross_asset = CrossAssetAnalysis()
        self.liquidation_extractor = LiquidationFeatureExtractor()
    
    def extract_all_features(self, market_data: Dict, liquidation_data: Dict, 
                           current_price: float) -> MarketFeatures:
        """Extract all market features"""
        try:
            # Create OHLCV DataFrame from individual series
            ohlcv = self._create_ohlcv_dataframe(market_data)
            if ohlcv.empty:
                raise ValueError("No OHLCV data available")
            
            # Price features
            price_features = self._extract_price_features(ohlcv)
            
            # Volume features
            volume_features = self._extract_volume_features(ohlcv)
            
            # Volatility features
            volatility_features = self._extract_volatility_features(ohlcv)
            
            # Market microstructure features
            microstructure_features = self._extract_microstructure_features(market_data)
            
            # Time-based features (use current timestamp)
            current_timestamp = pd.Timestamp.now()
            time_features = self.time_features.calculate_time_features(current_timestamp)
            
            # Cross-asset features
            cross_asset_features = self._extract_cross_asset_features(market_data)
            
            # Liquidation features
            liquidation_features = self._extract_liquidation_features(liquidation_data, current_price)
            
            return MarketFeatures(
                price_features=price_features,
                volume_features=volume_features,
                volatility_features=volatility_features,
                microstructure_features=microstructure_features,
                time_features=time_features,
                cross_asset_features=cross_asset_features,
                liquidation_features=liquidation_features
            )
            
        except Exception as e:
            logger.error(f"Error extracting features: {e}")
            return self._get_default_features()
    
    def _extract_price_features(self, ohlcv: pd.DataFrame) -> Dict[str, float]:
        """Extract price-based features"""
        if len(ohlcv) < 20:
            return {'price_momentum': 0, 'price_acceleration': 0, 'trend_strength': 0}
        
        close = ohlcv['close']
        high = ohlcv['high']
        low = ohlcv['low']
        
        # Price momentum
        price_momentum = close.pct_change(periods=5).iloc[-1] if len(close) >= 5 else 0
        
        # Price acceleration
        price_acceleration = close.pct_change(periods=5).diff().iloc[-1] if len(close) >= 10 else 0
        
        # Trend strength using linear regression
        if len(close) >= 20:
            x = np.arange(len(close))
            slope, _, r_value, _, _ = stats.linregress(x, close.values)
            trend_strength = r_value ** 2  # R-squared
        else:
            trend_strength = 0
        
        # Technical indicators
        rsi = self.technical_indicators.calculate_rsi(close)
        macd, signal, histogram = self.technical_indicators.calculate_macd(close)
        
        # NEW: Advanced indicators
        squeeze_momentum = self.technical_indicators.calculate_squeeze_momentum(high, low, close)
        wavetrend = self.technical_indicators.calculate_wavetrend(high, low, close)
        smc = self.technical_indicators.calculate_smart_money_concepts(high, low, close)
        supertrend = self.technical_indicators.calculate_supertrend(high, low, close)
        
        return {
            'price_momentum': price_momentum,
            'price_acceleration': price_acceleration,
            'trend_strength': trend_strength,
            'rsi': rsi.iloc[-1] if not rsi.empty else 50,
            'macd': macd.iloc[-1] if not macd.empty else 0,
            'macd_signal': signal.iloc[-1] if not signal.empty else 0,
            'macd_histogram': histogram.iloc[-1] if not histogram.empty else 0,
            # Squeeze Momentum Indicator [LazyBear]
            'squeeze_on': 1 if squeeze_momentum['squeeze_on'] else 0,
            'squeeze_momentum': squeeze_momentum['momentum'],
            'squeeze_momentum_trend': squeeze_momentum['momentum_trend'],
            'squeeze_release': 1 if squeeze_momentum['squeeze_release'] else 0,
            # WaveTrend Oscillator [LazyBear]
            'wavetrend_wt1': wavetrend['wt1'],
            'wavetrend_wt2': wavetrend['wt2'],
            'wavetrend_signal': wavetrend['signal'],
            'wavetrend_overbought': 1 if wavetrend['overbought_zone'] else 0,
            'wavetrend_oversold': 1 if wavetrend['oversold_zone'] else 0,
            'wavetrend_momentum': wavetrend['wt_momentum'],
            # Smart Money Concepts [LuxAlgo]
            'smc_bos': smc['bos'],
            'smc_choch': smc['choch'],
            'smc_order_block_distance': smc['order_block_distance'],
            'smc_fvg_present': 1 if smc['fvg_present'] else 0,
            'smc_market_structure': smc['market_structure'],
            # SuperTrend [KivancOzbilgic]
            'supertrend_direction': supertrend['direction'],
            'supertrend_signal': supertrend['signal'],
            'supertrend_distance_pct': supertrend['distance_pct'],
            'supertrend_in_uptrend': 1 if supertrend['in_uptrend'] else 0
        }
    
    def _extract_volume_features(self, ohlcv: pd.DataFrame) -> Dict[str, float]:
        """Extract volume-based features"""
        if len(ohlcv) < 20:
            return {'volume_ratio': 1, 'vpt_ratio': 1, 'volume_trend': 0}
        
        volume = ohlcv['volume']
        close = ohlcv['close']
        
        # Basic volume indicators
        volume_features = self.volume_analysis.calculate_volume_indicators(volume, close)
        
        # CVD
        cvd = self.volume_analysis.calculate_cvd(close, volume)
        cvd_momentum = cvd.iloc[-1] - cvd.iloc[-5] if len(cvd) >= 5 else 0
        
        volume_features['cvd_momentum'] = cvd_momentum
        
        return volume_features
    
    def _extract_volatility_features(self, ohlcv: pd.DataFrame) -> Dict[str, float]:
        """Extract volatility features"""
        if len(ohlcv) < 20:
            return {'historical_volatility': 0, 'vol_regime': 0}
        
        close = ohlcv['close']
        high = ohlcv['high']
        low = ohlcv['low']
        
        return self.volatility_analysis.calculate_volatility_features(close, high, low)
    
    def _extract_microstructure_features(self, market_data: Dict) -> Dict[str, float]:
        """Extract market microstructure features"""
        # Order book data (if available)
        orderbook = market_data.get('orderbook', {})
        if orderbook:
            bid_prices = orderbook.get('bids', [])
            ask_prices = orderbook.get('asks', [])
            bid_volumes = orderbook.get('bid_volumes', [])
            ask_volumes = orderbook.get('ask_volumes', [])
            
            return self.microstructure.calculate_order_flow_imbalance(
                bid_prices, ask_prices, bid_volumes, ask_volumes
            )
        
        # Tick data (if available)
        tick_data = market_data.get('tick_data', {})
        if tick_data:
            price_changes = tick_data.get('price_changes', [])
            volumes = tick_data.get('volumes', [])
            
            return self.microstructure.calculate_tick_analysis(price_changes, volumes)
        
        return {'order_flow_imbalance': 0, 'bid_ask_spread': 0, 'mid_price': 0}
    
    def _extract_cross_asset_features(self, market_data: Dict) -> Dict[str, float]:
        """Extract cross-asset features (BTC-focused)"""
        btc_prices = market_data.get('btc_prices', pd.Series())
        # eth_prices = market_data.get('eth_prices', pd.Series())  # Removed ETH
        dxy_prices = market_data.get('dxy_prices', pd.Series())
        
        return self.cross_asset.calculate_correlation_features(btc_prices, None, dxy_prices)
    
    def _extract_liquidation_features(self, liquidation_data: Dict, current_price: float) -> Dict[str, float]:
        """Extract liquidation features"""
        clusters_df = liquidation_data.get('clusters', pd.DataFrame())
        return self.liquidation_extractor.extract_liquidation_features(clusters_df, current_price)
    
    def _get_default_features(self) -> MarketFeatures:
        """Return default features when extraction fails"""
        return MarketFeatures(
            price_features={'price_momentum': 0, 'trend_strength': 0},
            volume_features={'volume_ratio': 1, 'volume_trend': 0},
            volatility_features={'historical_volatility': 0, 'vol_regime': 0},
            microstructure_features={'order_flow_imbalance': 0, 'bid_ask_spread': 0},
            time_features={'hour_sin': 0, 'hour_cos': 0},
            cross_asset_features={},  # Removed ETH correlation
            liquidation_features={'cluster_density': 0, 'cluster_strength': 0}
        )
    
    
    def _create_ohlcv_dataframe(self, market_data: Dict) -> pd.DataFrame:
        """Create OHLCV DataFrame from individual series"""
        try:
            # Check if we have individual series
            if 'btc_prices' in market_data:
                close = market_data['btc_prices']
                high = market_data.get('high', close)
                low = market_data.get('low', close)
                open_price = market_data.get('open', close)
                volume = market_data.get('volumes', pd.Series([1] * len(close)))
                
                ohlcv = pd.DataFrame({
                    'open': open_price,
                    'high': high,
                    'low': low,
                    'close': close,
                    'volume': volume
                })
                
                return ohlcv
            
            # Check if we already have OHLCV DataFrame
            elif 'ohlcv' in market_data:
                return market_data['ohlcv']
            
            return pd.DataFrame()
            
        except Exception as e:
            logger.error(f"Error creating OHLCV DataFrame: {e}")
            return pd.DataFrame()
