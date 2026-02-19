"""
Advanced Risk Management Module
Implements dynamic position sizing, risk controls, and portfolio management
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum
import logging
from scipy import stats
import math
from datetime import timezone

logger = logging.getLogger(__name__)

class PositionSizingMethod(Enum):
    """Position sizing methods"""
    FIXED = "fixed"
    KELLY = "kelly"
    VOLATILITY = "volatility"
    RISK_PARITY = "risk_parity"
    ADAPTIVE = "adaptive"
    DETERMINISTIC = "deterministic"  # qty = risk_usd / sl_pct / price

@dataclass
class RiskMetrics:
    """Risk metrics container"""
    var_95: float
    var_99: float
    expected_shortfall: float
    max_drawdown: float
    sharpe_ratio: float
    calmar_ratio: float
    sortino_ratio: float
    volatility: float
    skewness: float
    kurtosis: float

@dataclass
class Position:
    """Position information"""
    symbol: str
    side: str  # 'LONG' or 'SHORT'
    size: float
    entry_price: float
    stop_loss: float
    take_profit: float
    timestamp: pd.Timestamp
    confidence: float
    risk_amount: float

class RiskCalculator:
    """Calculate various risk metrics"""
    
    @staticmethod
    def calculate_var(returns: pd.Series, confidence_level: float = 0.95) -> float:
        """Calculate Value at Risk"""
        if len(returns) < 30:
            return 0.02  # Default 2% VaR
        
        return np.percentile(returns, (1 - confidence_level) * 100)
    
    @staticmethod
    def calculate_expected_shortfall(returns: pd.Series, confidence_level: float = 0.95) -> float:
        """Calculate Expected Shortfall (Conditional VaR)"""
        if len(returns) < 30:
            return 0.03  # Default 3% ES
        
        var = RiskCalculator.calculate_var(returns, confidence_level)
        tail_returns = returns[returns <= var]
        
        if len(tail_returns) == 0:
            return var
        
        return tail_returns.mean()
    
    @staticmethod
    def calculate_max_drawdown(returns: pd.Series) -> float:
        """Calculate maximum drawdown"""
        if len(returns) < 2:
            return 0
        
        cumulative_returns = (1 + returns).cumprod()
        running_max = cumulative_returns.expanding().max()
        drawdown = (cumulative_returns - running_max) / running_max
        
        return abs(drawdown.min())
    
    @staticmethod
    def calculate_sharpe_ratio(returns: pd.Series, risk_free_rate: float = 0.02) -> float:
        """Calculate Sharpe ratio"""
        if len(returns) < 30:
            return 0
        
        excess_returns = returns - risk_free_rate / 252  # Daily risk-free rate
        if excess_returns.std() == 0:
            return 0
        
        return excess_returns.mean() / excess_returns.std() * np.sqrt(252)
    
    @staticmethod
    def calculate_sortino_ratio(returns: pd.Series, risk_free_rate: float = 0.02) -> float:
        """Calculate Sortino ratio"""
        if len(returns) < 30:
            return 0
        
        excess_returns = returns - risk_free_rate / 252
        downside_returns = excess_returns[excess_returns < 0]
        
        if len(downside_returns) == 0 or downside_returns.std() == 0:
            return 0
        
        return excess_returns.mean() / downside_returns.std() * np.sqrt(252)
    
    @staticmethod
    def calculate_comprehensive_metrics(returns: pd.Series) -> RiskMetrics:
        """Calculate comprehensive risk metrics"""
        if len(returns) < 30:
            return RiskMetrics(
                var_95=0.02, var_99=0.03, expected_shortfall=0.03,
                max_drawdown=0.05, sharpe_ratio=0, calmar_ratio=0,
                sortino_ratio=0, volatility=0.02, skewness=0, kurtosis=3
            )
        
        return RiskMetrics(
            var_95=RiskCalculator.calculate_var(returns, 0.95),
            var_99=RiskCalculator.calculate_var(returns, 0.99),
            expected_shortfall=RiskCalculator.calculate_expected_shortfall(returns, 0.95),
            max_drawdown=RiskCalculator.calculate_max_drawdown(returns),
            sharpe_ratio=RiskCalculator.calculate_sharpe_ratio(returns),
            calmar_ratio=returns.mean() / RiskCalculator.calculate_max_drawdown(returns) if RiskCalculator.calculate_max_drawdown(returns) > 0 else 0,
            sortino_ratio=RiskCalculator.calculate_sortino_ratio(returns),
            volatility=returns.std() * np.sqrt(252),
            skewness=stats.skew(returns),
            kurtosis=stats.kurtosis(returns)
        )

class PositionSizer:
    """Dynamic position sizing based on various methods"""
    
    def __init__(self, config):
        self.config = config
        self.trading_config = config.get_trading_config()
        
        # Performance tracking
        self.returns_history = []
        self.win_rate_history = []
        self.avg_win_loss_ratio = 1.0
        
        # Risk parameters - force reload from config
        self.trading_config = config.get_trading_config()  # Reload to clear any cache
        self.max_position_size = self.trading_config.max_position_size if hasattr(self.trading_config, 'max_position_size') else 0.1
        self.min_position_size = 0.001  # Minimum position size
        self.kelly_fraction = 0.25  # Conservative Kelly fraction
    
    def calculate_position_size(self, signal_data: Dict, market_features: Dict, 
                              current_balance: float, method: str = None) -> float:
        """Calculate optimal position size"""
        if method is None:
            method = self.trading_config.position_size_method
        
        if method == PositionSizingMethod.FIXED.value:
            return self._fixed_position_sizing(signal_data, current_balance)
        elif method == PositionSizingMethod.KELLY.value:
            return self._kelly_position_sizing(signal_data, current_balance)
        elif method == PositionSizingMethod.VOLATILITY.value:
            return self._volatility_position_sizing(signal_data, market_features, current_balance)
        elif method == PositionSizingMethod.RISK_PARITY.value:
            return self._risk_parity_position_sizing(signal_data, market_features, current_balance)
        elif method == PositionSizingMethod.ADAPTIVE.value:
            return self._adaptive_position_sizing(signal_data, market_features, current_balance)
        elif method == PositionSizingMethod.DETERMINISTIC.value:
            return self._deterministic_position_sizing(signal_data, current_balance)
        elif method == "r_based": # P0 Improvement
            return self._r_based_position_sizing(signal_data, current_balance)
        else:
            return self._fixed_position_sizing(signal_data, current_balance)
    
    def _deterministic_position_sizing(self, signal_data: Dict, current_balance: float,
                                       risk_pct: float = 0.01, step_size: float = 0.001,
                                       min_notional: float = 5.0) -> float:
        """
        Deterministic position sizing per spec:
        qty = risk_usd / sl_pct / price
        
        With validation:
        - qty respects stepSize (rounds down)
        - notional >= minNotional
        
        Args:
            signal_data: Signal data containing entry_price and stop_loss
            current_balance: Current account balance in USD
            risk_pct: Risk percentage per trade (default 1%)
            step_size: Minimum quantity step (default 0.001 BTC)
            min_notional: Minimum order value in USD (default $5)
        
        Returns:
            Position size in BTC
        """
        entry_price = signal_data.get('entry_price', 0)
        stop_loss = signal_data.get('stop_loss', 0)
        
        if entry_price <= 0 or stop_loss <= 0:
            logger.warning("Invalid entry_price or stop_loss for position sizing")
            return self.trading_config.min_trade_amount
        
        # Calculate stop loss percentage
        sl_pct = abs(entry_price - stop_loss) / entry_price
        
        if sl_pct <= 0:
            logger.warning("Stop loss too close to entry, using default 1%")
            sl_pct = 0.01
        
        # Risk USD per trade
        risk_usd = current_balance * risk_pct
        
        # Apply daily risk cap (default -2% daily drawdown limit)
        daily_cap_pct = getattr(self.trading_config, 'daily_risk_cap', 0.02)
        daily_pnl = getattr(self, 'daily_pnl', 0)
        if daily_pnl <= -current_balance * daily_cap_pct:
            logger.warning(f"Daily risk cap hit: {daily_pnl:.2f} <= -{current_balance * daily_cap_pct:.2f}")
            return 0
        
        # Deterministic formula: qty = risk_usd / sl_pct / price
        qty = risk_usd / sl_pct / entry_price
        
        # Round down to stepSize
        qty = math.floor(qty / step_size) * step_size
        
        # Check minNotional
        notional = qty * entry_price
        if notional < min_notional:
            logger.warning(f"Position notional {notional:.2f} < minNotional {min_notional}")
            # Increase qty to meet minNotional
            min_qty = math.ceil(min_notional / entry_price / step_size) * step_size
            qty = min_qty
        
        # Apply position limits
        max_qty = current_balance * self.max_position_size / entry_price
        qty = min(qty, max_qty)
        
        # Apply minimum trade amount
        qty = max(qty, self.trading_config.min_trade_amount)
        
        logger.info(f"Deterministic sizing: risk_usd={risk_usd:.2f}, sl_pct={sl_pct:.2%}, "
                   f"entry={entry_price:.2f}, qty={qty:.6f} BTC")
        
        return qty

    def _r_based_position_sizing(self, signal_data: Dict, current_balance: float) -> float:
        """
        R-based position sizing (P0 invariant implementation) + Tier 2 quality scaling
        risk_budget = f(confidence) × cluster_quality × data_quality × max_R% of equity
        size = risk_budget / |entry-SL|
        
        Confidence tier mapping:
        - confidence < 0.7: 0.25R (0.125% of equity)
        - confidence 0.7-0.8: 0.5R (0.25% of equity)
        - confidence 0.8-0.9: 0.75R (0.375% of equity)
        - confidence >= 0.9: 1.0R (0.5% of equity)
        
        NEW Tier 2: Scale by cluster_quality (0.1-1.0) and data_quality (0-1)
        """
        logger.critical("🔍 DEBUG: _r_based_position_sizing called!")
        confidence = signal_data.get('confidence', signal_data.get('combined_confidence', 0.75))
        entry_price = signal_data.get('entry_price', 0)
        stop_loss = signal_data.get('stop_loss', 0)
        cluster_quality = signal_data.get('cluster_quality', 0.5)  # NEW: From cluster metrics
        data_quality = signal_data.get('data_quality_score', 1.0)  # NEW: From staleness checks
        logger.critical(f"🔍 DEBUG: entry={entry_price}, sl={stop_loss}, conf={confidence}, cluster_q={cluster_quality:.2f}, data_q={data_quality:.2f}")
        
        if entry_price <= 0 or stop_loss <= 0:
            logger.warning("R-sizing: Invalid entry or SL")
            return self.trading_config.min_trade_amount

        # Map confidence to risk tier (P0 spec)
        base_r_pct = 0.005  # 0.5% for 1.0R
        if confidence < 0.7:
            risk_multiplier = 0.25  # 0.25R
        elif confidence < 0.8:
            risk_multiplier = 0.5   # 0.5R
        elif confidence < 0.9:
            risk_multiplier = 0.75  # 0.75R
        else:
            risk_multiplier = 1.0   # 1.0R
        
        # Apply Tier 2 quality scaling: base × confidence_tier × cluster_quality × data_quality
        quality_multiplier = cluster_quality * data_quality
        
        # P2: Premium cluster bonus - high-quality clusters (>0.8) get up to 1.3x multiplier
        # This rewards exceptional setups while maintaining risk controls
        if cluster_quality > 0.8:
            premium_bonus = 0.3 * (cluster_quality - 0.8) / 0.2  # Linear scale from 0 to 0.3
            quality_multiplier *= (1.0 + premium_bonus)
            logger.info(f"🌟 Premium cluster detected: quality={cluster_quality:.2f} -> bonus={premium_bonus:.2f} (total_mult={quality_multiplier:.2f})")
        
        quality_multiplier = max(0.3, min(quality_multiplier, 1.3))  # Clamp to [0.3, 1.3] (raised cap for premium clusters)
        
        # NEW Tier 2: MTF alignment scaling
        # Scale position size by 1.2x when trend-aligned, 0.6x when fighting trend
        mtf_multiplier = 1.0  # Default neutral
        signal_direction = signal_data.get('direction', '').upper()
        
        # Extract MTF trend signals from market_features if available
        # P3 FIX: Handle case where market_features might not be defined in calling scope
        try:
            if 'market_features' in locals() or 'market_features' in globals():
                mtf_data = market_features.get('multi_timeframe', {})
            else:
                mtf_data = signal_data.get('market_features', {}).get('multi_timeframe', {})
        except (NameError, AttributeError):
            mtf_data = {}
            trend_15m = mtf_data.get('15m_trend', 0)
            trend_1h = mtf_data.get('1h_trend', 0)
            trend_4h = mtf_data.get('4h_trend', 0)
            
            # Compute MTF alignment score (-1 to +1)
            mtf_alignment = (trend_15m + trend_1h + trend_4h) / 3.0
            
            # Check if signal direction matches MTF trend
            if signal_direction == 'LONG' and mtf_alignment > 0.3:
                mtf_multiplier = 1.2  # Aligned with uptrend
                logger.info(f"MTF aligned: LONG with uptrend (alignment={mtf_alignment:.2f}) -> 1.2x size")
            elif signal_direction == 'SHORT' and mtf_alignment < -0.3:
                mtf_multiplier = 1.2  # Aligned with downtrend
                logger.info(f"MTF aligned: SHORT with downtrend (alignment={mtf_alignment:.2f}) -> 1.2x size")
            elif signal_direction == 'LONG' and mtf_alignment < -0.3:
                mtf_multiplier = 0.6  # Fighting downtrend
                logger.info(f"MTF fighting trend: LONG against downtrend (alignment={mtf_alignment:.2f}) -> 0.6x size")
            elif signal_direction == 'SHORT' and mtf_alignment > 0.3:
                mtf_multiplier = 0.6  # Fighting uptrend
                logger.info(f"MTF fighting trend: SHORT against uptrend (alignment={mtf_alignment:.2f}) -> 0.6x size")
        
        risk_budget_pct = base_r_pct * risk_multiplier * quality_multiplier * mtf_multiplier
        risk_amount = current_balance * risk_budget_pct
        
        logger.info(f"Quality scaling: cluster_q={cluster_quality:.2f}, data_q={data_quality:.2f}, "
                   f"mtf_mult={mtf_multiplier:.2f}, total_mult={quality_multiplier * mtf_multiplier:.2f} -> risk_budget={risk_budget_pct:.4%}")
        
        # Calculate position size: qty = risk_budget / stop_distance
        stop_distance_pct = abs(entry_price - stop_loss) / entry_price
        
        if stop_distance_pct <= 0:
            stop_distance_pct = 0.01  # Safety fallback
            logger.warning("R-sizing: SL too close, using 1% default")
            
        position_size = risk_amount / stop_distance_pct / entry_price
        
        # Apply limits
        max_size = current_balance * self.max_position_size / entry_price
        position_size = min(position_size, max_size)
        position_size = max(position_size, self.trading_config.min_trade_amount)
        
        logger.info(f"R-sizing: conf={confidence:.2f} -> {risk_multiplier:.2f}R -> "
                   f"risk_budget={risk_budget_pct:.4%} (${risk_amount:.2f}), "
                   f"SL={stop_distance_pct:.2%}, size={position_size:.6f} BTC")
        return position_size

    def _fixed_position_sizing(self, signal_data: Dict, current_balance: float) -> float:
        """Fixed percentage position sizing"""
        fixed_percentage = 0.02  # 2% of balance
        position_value = current_balance * fixed_percentage
        
        # Convert to BTC amount
        entry_price = signal_data.get('entry_price', 50000)
        btc_amount = position_value / entry_price
        
        # Apply minimum trade amount
        min_btc = self.trading_config.min_trade_amount
        return max(btc_amount, min_btc)
    
    def _kelly_position_sizing(self, signal_data: Dict, current_balance: float) -> float:
        """Kelly criterion position sizing"""
        if len(self.win_rate_history) < 20:
            return self._fixed_position_sizing(signal_data, current_balance)
        
        # Calculate win rate and average win/loss ratio
        recent_trades = self.win_rate_history[-50:]  # Last 50 trades
        win_rate = sum(recent_trades) / len(recent_trades)
        
        if win_rate <= 0.5:
            return self._fixed_position_sizing(signal_data, current_balance)
        
        # Kelly formula: f = (bp - q) / b
        # where b = odds, p = win probability, q = loss probability
        avg_win_loss = self.avg_win_loss_ratio
        kelly_fraction = (avg_win_loss * win_rate - (1 - win_rate)) / avg_win_loss
        
        # Apply conservative Kelly fraction
        kelly_fraction = max(0, min(kelly_fraction * self.kelly_fraction, 0.1))  # Cap at 10%
        
        position_value = current_balance * kelly_fraction
        entry_price = signal_data.get('entry_price', 50000)
        btc_amount = position_value / entry_price
        
        # Apply minimum trade amount
        min_btc = self.trading_config.min_trade_amount
        return max(btc_amount, min_btc)
    
    def _volatility_position_sizing(self, signal_data: Dict, market_features: Dict, 
                                   current_balance: float) -> float:
        """Volatility-based position sizing"""
        volatility = market_features.get('historical_volatility', 0.02)
        target_volatility = 0.01  # Target 1% daily volatility
        
        if volatility <= 0:
            return self._fixed_position_sizing(signal_data, current_balance)
        
        # Size inversely proportional to volatility
        volatility_adjustment = target_volatility / volatility
        base_size = current_balance * 0.02  # 2% base size
        
        position_value = base_size * volatility_adjustment
        
        # Apply bounds
        position_value = max(position_value, current_balance * 0.005)  # Min 0.5%
        position_value = min(position_value, current_balance * self.max_position_size)  # Max position size
        
        entry_price = signal_data.get('entry_price', 50000)
        btc_amount = position_value / entry_price
        
        # Apply minimum trade amount
        min_btc = self.trading_config.min_trade_amount
        return max(btc_amount, min_btc)
    
    def _risk_parity_position_sizing(self, signal_data: Dict, market_features: Dict, 
                                    current_balance: float) -> float:
        """Risk parity position sizing"""
        # Calculate risk contribution
        volatility = market_features.get('historical_volatility', 0.02)
        correlation = market_features.get('btc_eth_correlation', 0)
        
        # Adjust for correlation
        correlation_adjustment = 1 - abs(correlation) * 0.5
        
        # Base risk allocation
        base_risk = current_balance * 0.01  # 1% risk allocation
        
        # Adjust for volatility and correlation
        risk_adjusted_size = base_risk / (volatility * correlation_adjustment)
        
        # Apply bounds
        risk_adjusted_size = max(risk_adjusted_size, current_balance * 0.005)
        risk_adjusted_size = min(risk_adjusted_size, current_balance * self.max_position_size)
        
        entry_price = signal_data.get('entry_price', 50000)
        btc_amount = risk_adjusted_size / entry_price
        
        # Apply minimum trade amount
        min_btc = self.trading_config.min_trade_amount
        return max(btc_amount, min_btc)
    
    def _adaptive_position_sizing(self, signal_data: Dict, market_features: Dict, 
                                 current_balance: float) -> float:
        """Adaptive position sizing based on multiple factors"""
        confidence = signal_data.get('combined_confidence', 0.75)
        volatility = market_features.get('historical_volatility', 0.02)
        vol_regime = market_features.get('vol_regime', 0)
        
        # Base size
        base_size = current_balance * 0.02
        
        # Confidence adjustment
        confidence_multiplier = 0.5 + confidence  # Range: 0.5 to 1.5
        
        # Volatility adjustment
        vol_multiplier = 1.0
        if vol_regime == 1:  # High volatility
            vol_multiplier = 0.7
        elif vol_regime == -1:  # Low volatility
            vol_multiplier = 1.3
        
        # Recent performance adjustment
        performance_multiplier = 1.0
        if len(self.returns_history) >= 10:
            recent_performance = np.mean(self.returns_history[-10:])
            if recent_performance > 0.02:  # Good performance
                performance_multiplier = 1.2
            elif recent_performance < -0.02:  # Poor performance
                performance_multiplier = 0.8
        
        # Calculate final size
        final_size = base_size * confidence_multiplier * vol_multiplier * performance_multiplier
        
        # Apply bounds
        final_size = max(final_size, current_balance * 0.005)
        final_size = min(final_size, current_balance * self.max_position_size)
        
        entry_price = signal_data.get('entry_price', 50000)
        btc_amount = final_size / entry_price
        
        # Apply minimum trade amount
        min_btc = self.trading_config.min_trade_amount
        return max(btc_amount, min_btc)
    
    def update_performance(self, trade_outcome: Dict):
        """Update performance metrics for position sizing"""
        if trade_outcome.get('is_profitable', False):
            self.win_rate_history.append(1)
            self.returns_history.append(trade_outcome.get('rr_achieved', 1.0))
        else:
            self.win_rate_history.append(0)
            self.returns_history.append(-trade_outcome.get('loss_ratio', 1.0))
        
        # Update average win/loss ratio
        if len(self.returns_history) >= 20:
            wins = [r for r in self.returns_history if r > 0]
            losses = [abs(r) for r in self.returns_history if r < 0]
            
            if wins and losses:
                avg_win = np.mean(wins)
                avg_loss = np.mean(losses)
                self.avg_win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 1.0

class RiskManager:
    """Comprehensive risk management system"""
    
    def __init__(self, config):
        self.config = config
        self.trading_config = config.get_trading_config()
        
        # Risk calculator and position sizer
        self.risk_calculator = RiskCalculator()
        self.position_sizer = PositionSizer(config)
        
        # Portfolio state
        self.current_positions: List[Position] = []
        self.balance_history = []
        self.returns_history = []
        self.max_balance = 0
        self.current_drawdown = 0
        
        # Risk limits
        self.max_drawdown_limit = self.trading_config.max_drawdown
        self.max_concurrent_positions = self.trading_config.max_concurrent_positions
        self.max_daily_trades = self.trading_config.max_daily_trades
        
        # Daily tracking
        self.daily_trades = 0
        self.daily_pnl = 0.0
        self.last_trade_date = None
        self.start_of_day_equity = self.trading_config.initial_balance
        
        # Daily risk cap (P0 invariant)
        self.daily_cap_breached = False
        self.daily_cap_pct = self.trading_config.daily_risk_cap  # 2% hard cap
        self.max_daily_risk = self.trading_config.daily_risk_cap  # Alias for compatibility
        
        # Circuit breakers
        self.circuit_breaker_active = False
        self.circuit_breaker_reason = ""
    
    def can_open_position(self, signal_data: Dict, current_balance: float, current_price: float = None) -> Tuple[bool, str]:
        """Check if position can be opened with hard daily risk cap enforcement"""
        # Reset daily tracking at UTC 00:00
        today = pd.Timestamp.now(tz='UTC').date()
        if self.last_trade_date != today:
            self.daily_trades = 0
            self.daily_pnl = 0.0
            self.start_of_day_equity = current_balance
            self.daily_cap_breached = False
            self.last_trade_date = today
            self.position_sizer.daily_pnl = 0.0
            logger.info(f"Daily reset: start_of_day_equity=${self.start_of_day_equity:,.2f}")
        
        # Initialize start-of-day equity if not set
        if self.start_of_day_equity is None:
            self.start_of_day_equity = current_balance
        
        # HARD DAILY RISK CAP CHECK (P0 invariant)
        # Calculate total daily PnL (realized + unrealized)
        total_daily_pnl = self.get_total_daily_pnl(current_price if current_price else signal_data.get('entry_price', 0))
        daily_loss_pct = total_daily_pnl / self.start_of_day_equity if self.start_of_day_equity > 0 else 0
        
        if daily_loss_pct <= -self.daily_cap_pct:
            if not self.daily_cap_breached:
                self.daily_cap_breached = True
                logger.critical(f"💀 DAILY RISK CAP BREACHED: {daily_loss_pct:.2%} <= -{self.daily_cap_pct:.2%} | "
                              f"Total PnL: ${total_daily_pnl:,.2f} | Start equity: ${self.start_of_day_equity:,.2f}")
                # Flatten all positions
                if len(self.current_positions) > 0:
                    logger.warning(f"Flattening {len(self.current_positions)} positions due to daily cap breach")
                    # Note: Actual flattening must be triggered by caller
            return False, f"Daily risk cap breached: {daily_loss_pct:.2%} (limit: -{self.daily_cap_pct:.2%})"
        
        # Check circuit breaker
        if self.circuit_breaker_active:
            return False, f"Circuit breaker active: {self.circuit_breaker_reason}"
        
        # Check maximum concurrent positions
        if len(self.current_positions) >= self.max_concurrent_positions:
            return False, f"Maximum concurrent positions reached: {self.max_concurrent_positions}"
        
        # Check daily trade limit (reset already handled above)
        if self.daily_trades >= self.max_daily_trades:
            return False, f"Daily trade limit reached: {self.max_daily_trades}"
        
        # Check drawdown limit
        if self.current_drawdown > self.max_drawdown_limit:
            return False, f"Maximum drawdown exceeded: {self.current_drawdown:.2%}"
        
        # TIER 1 FIX: Check minimum balance against start_of_day_equity, not current_balance
        # (Original logic was tautological: current_balance < current_balance * 0.1 is always False)
        min_balance = self.start_of_day_equity * 0.1  # Keep 10% of daily starting equity as buffer
        if current_balance < min_balance:
            return False, f"Balance {current_balance:.2f} below safety buffer ({min_balance:.2f}, 10% of daily start)"
        
        return True, "OK"
    
    def calculate_position_size(self, signal_data: Dict, market_features: Dict, 
                              current_balance: float) -> float:
        """Calculate position size with risk controls"""
        # Get base position size from PositionSizer (which calls r_based)
        base_size = self.position_sizer.calculate_position_size(
            signal_data, market_features, current_balance
        )
        
        # TEMPORARILY DISABLED: Skip adjustments to test r_based sizing directly
        # adjusted_size = self._apply_risk_adjustments(
        #     base_size, signal_data, market_features, current_balance
        # )
        
        logger.info(f"💰 Position size: {base_size:.6f} BTC (adjustments DISABLED for testing)")
        return base_size
    
    def _apply_risk_adjustments(self, base_size: float, signal_data: Dict, 
                               market_features: Dict, current_balance: float) -> float:
        """Apply risk-based adjustments to position size"""
        logger.critical(f"🔍 DEBUG _apply_risk_adjustments: base_size={base_size:.6f}")
        adjusted_size = base_size
        
        # Drawdown adjustment
        if self.current_drawdown > self.max_drawdown_limit * 0.5:
            drawdown_factor = 1 - (self.current_drawdown / self.max_drawdown_limit)
            adjusted_size *= max(drawdown_factor, 0.5)
            logger.critical(f"🔍 DEBUG: Drawdown adjustment applied: {adjusted_size:.6f}")
        
        # Volatility adjustment
        volatility = market_features.get('historical_volatility', 0.02)
        if volatility > 0.05:  # High volatility
            adjusted_size *= 0.7
            logger.critical(f"🔍 DEBUG: HIGH volatility ({volatility:.4f}) adjustment: {adjusted_size:.6f}")
        elif volatility < 0.01:  # Low volatility
            adjusted_size *= 1.2
            logger.critical(f"🔍 DEBUG: LOW volatility ({volatility:.4f}) adjustment: {adjusted_size:.6f}")
        
        # Correlation adjustment
        correlation = abs(market_features.get('btc_eth_correlation', 0))
        if correlation > 0.8:  # High correlation
            adjusted_size *= 0.8
            logger.critical(f"🔍 DEBUG: Correlation ({correlation:.4f}) adjustment: {adjusted_size:.6f}")
        
        # Recent performance adjustment
        if len(self.returns_history) >= 5:
            recent_performance = np.mean(self.returns_history[-5:])
            if recent_performance < -0.01:  # Poor recent performance
                adjusted_size *= 0.8
                logger.critical(f"🔍 DEBUG: Performance adjustment: {adjusted_size:.6f}")
        
        # Ensure minimum size
        min_btc = self.trading_config.min_trade_amount
        adjusted_size = max(adjusted_size, min_btc)
        
        # Ensure maximum size - use position_sizer's max_position_size
        max_position_size = self.position_sizer.max_position_size
        max_value = current_balance * max_position_size
        entry_price = signal_data.get('entry_price', 50000)
        max_btc = max_value / entry_price
        adjusted_size = min(adjusted_size, max_btc)
        
        logger.critical(f"🔍 DEBUG _apply_risk_adjustments: adjusted_size={adjusted_size:.6f}, returning")
        return adjusted_size
    
    def _calculate_unrealized_pnl(self, current_price: float) -> float:
        """Calculate unrealized PnL for current positions"""
        if not current_price or current_price <= 0:
            return 0.0
        unrealized = 0.0
        for pos in self.current_positions:
            if pos.side == 'LONG':
                unrealized += (current_price - pos.entry_price) * pos.size
            else:
                unrealized += (pos.entry_price - current_price) * pos.size
        return unrealized

    def calculate_stop_loss_take_profit(self, signal_data: Dict, market_features: Dict, 
                                        cluster_width: float = None, opposing_cluster_price: float = None) -> Tuple[float, float]:
        """
        Calculate dynamic stop loss and take profit levels (P0 invariant)
        
        SL derived from cluster width with buckets:
        - tight (<25bps): k=0.5
        - medium (25-60bps): k=1.0
        - wide (>60bps): k=1.5
        
        TP from R/R≥2.0 or opposing cluster boundary
        """
        entry_price = signal_data.get('entry_price', 50000)
        direction = signal_data.get('direction', 'LONG')
        
        # Get ATR for volatility-based fallback
        atr = market_features.get('atr', entry_price * 0.01)  # Default 1% ATR
        stop_loss_multiplier = self.trading_config.stop_loss_multiplier
        
        # P0 Invariant: Width-Based SL with buckets
        if cluster_width and cluster_width > 0:
            # Determine bucket and multiplier
            width_bps = (cluster_width / entry_price) * 10000
            
            if width_bps < 25:
                k = 0.5
                bucket = "tight"
            elif width_bps <= 60:
                k = 1.0
                bucket = "medium"
            else:
                k = 1.5
                bucket = "wide"
            
            stop_distance = cluster_width * k
            logger.info(f"Width-based SL: cluster_width={cluster_width:.2f} ({width_bps:.1f}bps) -> "
                       f"bucket={bucket}, k={k:.1f}, stop_dist={stop_distance:.2f}")
        else:
            # Fallback to ATR if cluster width not available
            stop_distance = atr * stop_loss_multiplier
            logger.info(f"ATR-based SL fallback: atr={atr:.2f}, mult={stop_loss_multiplier:.1f}, "
                       f"stop_dist={stop_distance:.2f}")
        
        if direction == 'LONG':
            stop_loss = entry_price - stop_distance
        else:
            stop_loss = entry_price + stop_distance
        
        # Calculate risk amount for R/R calculation
        risk_amount = abs(entry_price - stop_loss)
        
        # P0 Invariant: TP from R/R≥2.0 or opposing cluster
        min_rr = 2.0
        default_tp_distance = risk_amount * min_rr
        
        if opposing_cluster_price and opposing_cluster_price > 0:
            # Check if opposing cluster gives better R/R
            cluster_distance = abs(opposing_cluster_price - entry_price)
            cluster_rr = cluster_distance / risk_amount if risk_amount > 0 else 0
            
            if cluster_rr >= min_rr:
                # Use opposing cluster as TP
                take_profit = opposing_cluster_price
                logger.info(f"TP from opposing cluster: price={opposing_cluster_price:.2f}, "
                           f"R/R={cluster_rr:.2f}")
            else:
                # Opposing cluster too close, use min R/R
                if direction == 'LONG':
                    take_profit = entry_price + default_tp_distance
                else:
                    take_profit = entry_price - default_tp_distance
                logger.info(f"TP from min R/R {min_rr:.1f}: cluster R/R={cluster_rr:.2f} too low")
        else:
            # No opposing cluster, use min R/R
            if direction == 'LONG':
                take_profit = entry_price + default_tp_distance
            else:
                take_profit = entry_price - default_tp_distance
            logger.info(f"TP from min R/R {min_rr:.1f}: no opposing cluster")
        
        # Final R/R validation
        final_risk = abs(entry_price - stop_loss)
        final_reward = abs(take_profit - entry_price)
        final_rr = final_reward / final_risk if final_risk > 0 else 0
        
        logger.info(f"Final brackets: SL={stop_loss:.2f}, TP={take_profit:.2f}, R/R={final_rr:.2f}")
        
        return stop_loss, take_profit
    
    def add_position(self, position: Position):
        """Add new position to portfolio"""
        self.current_positions.append(position)
        self.daily_trades += 1
        
        logger.info(f"Position added: {position.symbol} {position.side} {position.size:.6f} BTC")
    
    def remove_position(self, position: Position, exit_price: float, exit_reason: str):
        """Remove position from portfolio"""
        # Find position by matching key attributes instead of object identity
        matching_pos = None
        for pos in self.current_positions:
            if (pos.symbol == position.symbol and 
                pos.side == position.side and 
                abs(pos.entry_price - position.entry_price) < 0.01 and
                abs(pos.size - position.size) < 0.000001):
                matching_pos = pos
                break
        
        if matching_pos:
            self.current_positions.remove(matching_pos)
            logger.info(f"✅ Removed position from tracking: {len(self.current_positions)} positions remaining")
            
            # Calculate P&L
            if position.side == 'LONG':
                pnl_ratio = (exit_price - position.entry_price) / position.entry_price
                pnl_amount = (exit_price - position.entry_price) * position.size
            else:
                pnl_ratio = (position.entry_price - exit_price) / position.entry_price
                pnl_amount = (position.entry_price - exit_price) * position.size
            
            # Update daily PnL
            self.daily_pnl += pnl_amount
            self.position_sizer.daily_pnl = self.daily_pnl
            
            # Update performance tracking
            self.returns_history.append(pnl_ratio)
            self.position_sizer.update_performance({
                'is_profitable': pnl_ratio > 0,
                'rr_achieved': pnl_ratio if pnl_ratio > 0 else 0,
                'loss_ratio': abs(pnl_ratio) if pnl_ratio < 0 else 0
            })
            
            logger.info(f"Position closed: {position.symbol} {position.side} "
                       f"P&L: {pnl_ratio:.2%} Reason: {exit_reason}")
        else:
            logger.warning(f"⚠️ Position not found in current_positions for removal: {position.symbol} {position.side} @ {position.entry_price}")
    
    def update_balance(self, new_balance: float):
        """Update balance and calculate drawdown"""
        self.balance_history.append(new_balance)
        
        # Update max balance
        if new_balance > self.max_balance:
            self.max_balance = new_balance
        
        # Calculate current drawdown
        if self.max_balance > 0:
            self.current_drawdown = (self.max_balance - new_balance) / self.max_balance
        
        # Check circuit breaker
        self._check_circuit_breaker()
    
    def _check_circuit_breaker(self):
        """Check if circuit breaker should be activated"""
        if self.current_drawdown > self.max_drawdown_limit:
            self.circuit_breaker_active = True
            self.circuit_breaker_reason = f"Drawdown limit exceeded: {self.current_drawdown:.2%}"
            logger.warning(f"Circuit breaker activated: {self.circuit_breaker_reason}")
        
        # Check consecutive losses
        if len(self.returns_history) >= 5:
            recent_returns = self.returns_history[-5:]
            if all(r < 0 for r in recent_returns):
                self.circuit_breaker_active = True
                self.circuit_breaker_reason = "5 consecutive losses"
                logger.warning(f"Circuit breaker activated: {self.circuit_breaker_reason}")
    
    def reset_circuit_breaker(self):
        """Reset circuit breaker"""
        self.circuit_breaker_active = False
        self.circuit_breaker_reason = ""
        logger.info("Circuit breaker reset")
    
    def get_risk_metrics(self) -> RiskMetrics:
        """Get current risk metrics"""
        if len(self.returns_history) < 10:
            return self.risk_calculator.calculate_comprehensive_metrics(pd.Series())
        
        returns_series = pd.Series(self.returns_history)
        return self.risk_calculator.calculate_comprehensive_metrics(returns_series)
    
    def get_portfolio_summary(self) -> Dict:
        """Get portfolio summary"""
        total_exposure = sum(pos.size * pos.entry_price for pos in self.current_positions)
        
        return {
            'current_positions': len(self.current_positions),
            'total_exposure': total_exposure,
            'current_drawdown': self.current_drawdown,
            'max_drawdown': self.get_risk_metrics().max_drawdown,
            'daily_trades': self.daily_trades,
            'circuit_breaker_active': self.circuit_breaker_active,
            'circuit_breaker_reason': self.circuit_breaker_reason,
            'win_rate': sum(1 for r in self.returns_history if r > 0) / len(self.returns_history) if self.returns_history else 0
        }

    def get_total_daily_pnl(self, current_price: float) -> float:
        """Calculate total daily PnL (realized + unrealized)"""
        unrealized = 0.0
        for pos in self.current_positions:
            if pos.side == 'LONG':
                unrealized += (current_price - pos.entry_price) * pos.size
            else:
                unrealized += (pos.entry_price - current_price) * pos.size
        
        return self.daily_pnl + unrealized
