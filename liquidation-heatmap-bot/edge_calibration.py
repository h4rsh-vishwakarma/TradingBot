"""
Edge Calibration Module
Calibrates predicted edge against realized returns to avoid trading when EV is negative.
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional, Tuple
from datetime import datetime, timezone
import logging
from dataclasses import dataclass
from collections import deque

logger = logging.getLogger(__name__)


@dataclass
class EdgeCalibration:
    """Calibration parameters for edge prediction"""
    intercept: float  # a in: effective_edge = a + b * pred_edge
    slope: float      # b in: effective_edge = a + b * pred_edge
    r_squared: float  # Fit quality
    sample_count: int
    last_updated: datetime
    no_trade_band_bps: float  # Don't trade if |calibrated_edge| < this


class EdgeCalibrator:
    """
    Calibrates predicted edge (pred_bps, edge_bps) vs realized returns.
    
    Purpose: Ensure we only trade when EV > costs in production.
    
    Workflow:
    1. Accumulate (predicted_edge, realized_return) pairs
    2. Fit linear calibration: realized = a + b * predicted
    3. Use calibrated edge to gate trades
    """
    
    def __init__(self, config):
        self.config = config
        self.trading_config = config.get_trading_config()
        
        # Calibration history
        self.max_history = 500  # Keep last N predictions
        self.pred_edge_history = deque(maxlen=self.max_history)
        self.realized_return_history = deque(maxlen=self.max_history)
        
        # Current calibration
        self.calibration: Optional[EdgeCalibration] = None
        self.min_samples_for_calibration = 50
        
        # Trading costs (BPS)
        self.fee_bps = 4.0  # 0.04% maker fee on Binance futures
        self.slippage_bps = 5.0  # Estimated 0.05% slippage
        self.total_cost_bps = self.fee_bps + self.slippage_bps  # 9 BPS
        self.costs_bps = self.total_cost_bps  # Alias for backward compatibility
        
        # No-trade band (legacy - now using min_profit_threshold in should_trade)
        self.no_trade_band_bps = 0.0  # Deprecated - using direct profit threshold instead
        
        logger.info(f"Edge Calibrator initialized: costs={self.costs_bps:.1f} BPS, "
                   f"no_trade_band={self.no_trade_band_bps:.1f} BPS")
    
    def add_prediction_outcome(self, predicted_edge_bps: float, realized_return_bps: float):
        """
        Record a (prediction, outcome) pair for calibration.
        
        Args:
            predicted_edge_bps: Original edge prediction in BPS
            realized_return_bps: Actual return achieved in BPS
        """
        self.pred_edge_history.append(predicted_edge_bps)
        self.realized_return_history.append(realized_return_bps)
        
        # Refit calibration if we have enough samples
        if len(self.pred_edge_history) >= self.min_samples_for_calibration:
            self._refit_calibration()
    
    def _refit_calibration(self):
        """Fit linear regression: realized = a + b * predicted"""
        try:
            pred = np.array(self.pred_edge_history)
            realized = np.array(self.realized_return_history)
            
            # Simple linear regression
            slope, intercept = np.polyfit(pred, realized, 1)
            
            # Calculate R²
            y_mean = np.mean(realized)
            ss_tot = np.sum((realized - y_mean) ** 2)
            y_pred = intercept + slope * pred
            ss_res = np.sum((realized - y_pred) ** 2)
            r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
            
            self.calibration = EdgeCalibration(
                intercept=intercept,
                slope=slope,
                r_squared=r_squared,
                sample_count=len(pred),
                last_updated=datetime.now(timezone.utc),
                no_trade_band_bps=self.no_trade_band_bps
            )
            
            logger.info(f"📊 Edge calibration updated: "
                       f"effective_edge = {intercept:.1f} + {slope:.2f} * pred_edge "
                       f"(R²={r_squared:.3f}, N={len(pred)})")
            
        except Exception as e:
            logger.error(f"Calibration fit error: {e}")
    
    def get_calibrated_edge(self, predicted_edge_bps: float) -> float:
        """
        Apply calibration to raw prediction.
        
        Returns:
            Calibrated edge in BPS (negative means expected loss)
        """
        if self.calibration is None:
            # No calibration yet - use raw prediction (system already conservative)
            return predicted_edge_bps
        
        effective_edge = self.calibration.intercept + self.calibration.slope * predicted_edge_bps
        return effective_edge
    
    def should_trade(self, predicted_edge_bps: float) -> Tuple[bool, Dict]:
        """
        Gate trade based on calibrated edge vs costs.
        
        Returns:
            (should_trade: bool, details: Dict)
        """
        calibrated_edge = self.get_calibrated_edge(predicted_edge_bps)
        edge_after_costs = calibrated_edge - self.total_cost_bps
        
        # Check if edge after costs meets minimum threshold
        # Threshold: 3 BPS minimum profit after all costs
        min_profit_threshold = 3.0  # BPS
        meets_threshold = edge_after_costs >= min_profit_threshold
        
        should_trade = meets_threshold
        
        details = {
            'predicted_edge_bps': predicted_edge_bps,
            'calibrated_edge_bps': calibrated_edge,
            'edge_after_costs_bps': edge_after_costs,
            'total_cost_bps': self.total_cost_bps,
            'min_profit_threshold_bps': min_profit_threshold,
            'calibrated': self.calibration is not None,
            'should_trade': should_trade,
            'rejection_reason': None if should_trade else 'EDGE_TOO_SMALL'
        }
        
        if not should_trade:
            logger.debug(f"❌ Trade rejected: {details['rejection_reason']} "
                        f"(cal_edge={calibrated_edge:.1f}, after_costs={edge_after_costs:.1f} BPS)")
        
        return should_trade, details
    
    def get_stats(self) -> Dict:
        """Get calibration statistics"""
        if self.calibration is None:
            return {
                'calibrated': False,
                'sample_count': len(self.pred_edge_history),
                'min_samples_needed': self.min_samples_for_calibration
            }
        
        return {
            'calibrated': True,
            'intercept': self.calibration.intercept,
            'slope': self.calibration.slope,
            'r_squared': self.calibration.r_squared,
            'sample_count': self.calibration.sample_count,
            'last_updated': self.calibration.last_updated.isoformat(),
            'no_trade_band_bps': self.calibration.no_trade_band_bps,
            'total_cost_bps': self.total_cost_bps
        }
    
    def save_calibration(self, filepath: str):
        """Save calibration to disk"""
        if self.calibration is None:
            logger.warning("No calibration to save")
            return
        
        import json
        data = {
            'intercept': self.calibration.intercept,
            'slope': self.calibration.slope,
            'r_squared': self.calibration.r_squared,
            'sample_count': self.calibration.sample_count,
            'last_updated': self.calibration.last_updated.isoformat(),
            'no_trade_band_bps': self.no_trade_band_bps,
            'total_cost_bps': self.total_cost_bps,
            'pred_history': list(self.pred_edge_history),
            'realized_history': list(self.realized_return_history)
        }
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"✅ Calibration saved to {filepath}")
    
    def load_calibration(self, filepath: str):
        """Load calibration from disk"""
        import json
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            self.calibration = EdgeCalibration(
                intercept=data['intercept'],
                slope=data['slope'],
                r_squared=data['r_squared'],
                sample_count=data['sample_count'],
                last_updated=datetime.fromisoformat(data['last_updated']),
                no_trade_band_bps=data['no_trade_band_bps']
            )
            
            self.pred_edge_history = deque(data['pred_history'], maxlen=self.max_history)
            self.realized_return_history = deque(data['realized_history'], maxlen=self.max_history)
            
            logger.info(f"✅ Calibration loaded from {filepath} "
                       f"(N={self.calibration.sample_count}, R²={self.calibration.r_squared:.3f})")
            
        except Exception as e:
            logger.error(f"Failed to load calibration: {e}")


def test_edge_calibrator():
    """Quick test of edge calibrator"""
    from types import SimpleNamespace
    
    config = SimpleNamespace()
    config.get_trading_config = lambda: SimpleNamespace()
    
    calibrator = EdgeCalibrator(config)
    
    # Simulate some predictions and outcomes
    # Realistic scenario: predictions are overoptimistic
    np.random.seed(42)
    for i in range(100):
        pred_edge = np.random.uniform(5, 50)  # Predicted 5-50 BPS
        # Reality: only 40% of predicted edge + noise
        realized = 0.4 * pred_edge + np.random.normal(0, 10)
        calibrator.add_prediction_outcome(pred_edge, realized)
    
    # Test calibration
    assert calibrator.calibration is not None, "Calibration should be fitted"
    print(f"Calibration: {calibrator.get_stats()}")
    
    # Test gating
    should_trade, details = calibrator.should_trade(predicted_edge_bps=30.0)
    print(f"Should trade (30 BPS pred): {should_trade}, details: {details}")
    
    should_trade, details = calibrator.should_trade(predicted_edge_bps=10.0)
    print(f"Should trade (10 BPS pred): {should_trade}, details: {details}")
    
    print("✅ Edge calibrator tests passed")


if __name__ == "__main__":
    test_edge_calibrator()
