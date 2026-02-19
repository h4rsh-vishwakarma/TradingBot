#!/usr/bin/env python3
"""
Prediction logging and calibration infrastructure.

This module provides:
1. PredictionEvent schema for logging raw model predictions
2. Calibration pipeline for fitting and applying prediction calibration
3. No-trade band enforcement based on calibrated predictions
"""

import json
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass, asdict


@dataclass
class PredictionEvent:
    """
    Raw model prediction event - logged BEFORE decision logic.
    
    This enables:
    - IC(200) computation with actual predictions
    - Calibration fitting (pred_raw -> realized_bps)
    - Signal quality analysis independent of decision rules
    """
    ts: str
    run_id: str
    session_id: str
    prediction_id: str
    symbol: str
    mode: str
    
    # Raw model outputs
    pred_raw: float  # Raw model prediction (e.g., -0.0023 for -23 bps)
    pred_bps: float  # Prediction in basis points (pred_raw * 10000)
    
    # Model components (for debugging/analysis)
    oi_signal: Optional[str] = None
    funding_signal: Optional[str] = None
    cluster_signal: Optional[str] = None
    
    # Confidence/quality
    confidence: Optional[float] = None
    quality_score: Optional[float] = None
    
    # Features used (for feature importance analysis)
    features: Optional[Dict] = None
    
    # Model metadata
    model_version: Optional[str] = None
    event: str = 'prediction'
    
    def to_dict(self):
        d = asdict(self)
        # Remove None values to keep events clean
        return {k: v for k, v in d.items() if v is not None}
    
    def to_json(self):
        return json.dumps(self.to_dict())


class PredictionLogger:
    """Handles prediction event logging to JSONL files."""
    
    def __init__(self, log_dir: str = 'logs/events'):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.prediction_file = self.log_dir / 'prediction.jsonl'
    
    def log_prediction(self, event: PredictionEvent):
        """Append prediction event to JSONL file."""
        with open(self.prediction_file, 'a') as f:
            f.write(event.to_json() + '\n')
    
    def load_predictions(self, limit: Optional[int] = None) -> pd.DataFrame:
        """Load prediction events from JSONL file."""
        if not self.prediction_file.exists():
            return pd.DataFrame()
        
        predictions = []
        with open(self.prediction_file, 'r') as f:
            for i, line in enumerate(f):
                if limit and i >= limit:
                    break
                predictions.append(json.loads(line))
        
        return pd.DataFrame(predictions)


class CalibrationPipeline:
    """
    Calibration pipeline for prediction adjustment.
    
    Fits: realized_bps = a + b * pred_bps
    Applies: calibrated_pred = a + b * raw_pred
    Enforces: |calibrated_pred| >= no_trade_band_bps → trade
    """
    
    def __init__(self, 
                 no_trade_band_bps: float = 15.0,
                 min_samples_for_fit: int = 200,
                 calibration_file: str = 'calibration_params.json'):
        self.no_trade_band_bps = no_trade_band_bps
        self.min_samples_for_fit = min_samples_for_fit
        self.calibration_file = Path(calibration_file)
        
        # Calibration parameters
        self.intercept = 0.0
        self.slope = 1.0
        self.is_fitted = False
        self.n_samples = 0
        self.r_squared = 0.0
        
        # Load existing calibration if available
        self.load_calibration()
    
    def fit_calibration(self, 
                       predictions_df: pd.DataFrame, 
                       equity_df: pd.DataFrame) -> Dict:
        """
        Fit calibration model: realized_bps = a + b * pred_bps
        
        Args:
            predictions_df: DataFrame with columns [ts, pred_bps]
            equity_df: DataFrame with columns [ts, equity_value]
        
        Returns:
            Dict with fit statistics
        """
        # Compute realized returns from equity
        eq = equity_df.copy()
        eq['ts'] = pd.to_datetime(eq['ts'], utc=True)
        eq = eq.set_index('ts').sort_index()
        eq['returns'] = eq['equity_value'].pct_change()
        eq['realized_bps'] = eq['returns'].shift(-1) * 1e4  # Next-bar return
        
        # Align predictions with realized returns
        pred = predictions_df.copy()
        pred['ts'] = pd.to_datetime(pred['ts'], utc=True)
        pred['bar'] = pred['ts'].dt.floor('5T')  # 5-min bars
        
        # Aggregate predictions to bars (last prediction per bar)
        pred_agg = pred.groupby('bar')['pred_bps'].last()
        
        # Merge with realized returns
        aligned = pd.merge(
            eq.reset_index(),
            pred_agg.reset_index(),
            left_on='ts',
            right_on='bar',
            how='inner'
        )
        
        # Drop NaNs
        aligned = aligned[['pred_bps', 'realized_bps']].dropna()
        
        if len(aligned) < self.min_samples_for_fit:
            return {
                'success': False,
                'reason': f'Insufficient samples: {len(aligned)} < {self.min_samples_for_fit}',
                'n_samples': len(aligned)
            }
        
        # Fit linear regression
        from sklearn.linear_model import LinearRegression
        
        X = aligned['pred_bps'].values.reshape(-1, 1)
        y = aligned['realized_bps'].values
        
        lr = LinearRegression()
        lr.fit(X, y)
        
        self.intercept = float(lr.intercept_)
        self.slope = float(lr.coef_[0])
        self.n_samples = len(aligned)
        self.r_squared = float(lr.score(X, y))
        self.is_fitted = True
        
        # Save calibration parameters
        self.save_calibration()
        
        return {
            'success': True,
            'intercept': self.intercept,
            'slope': self.slope,
            'r_squared': self.r_squared,
            'n_samples': self.n_samples,
            'formula': f'realized_bps = {self.intercept:.4f} + {self.slope:.4f} * pred_bps'
        }
    
    def apply_calibration(self, pred_bps: float) -> Tuple[float, bool]:
        """
        Apply calibration and no-trade band.
        
        Args:
            pred_bps: Raw prediction in basis points
        
        Returns:
            (calibrated_pred_bps, should_trade)
        """
        # Apply calibration
        calibrated = self.intercept + self.slope * pred_bps
        
        # Check no-trade band
        should_trade = abs(calibrated) >= self.no_trade_band_bps
        
        return calibrated, should_trade
    
    def save_calibration(self):
        """Save calibration parameters to JSON file."""
        params = {
            'intercept': self.intercept,
            'slope': self.slope,
            'r_squared': self.r_squared,
            'n_samples': self.n_samples,
            'is_fitted': self.is_fitted,
            'no_trade_band_bps': self.no_trade_band_bps,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        
        with open(self.calibration_file, 'w') as f:
            json.dump(params, f, indent=2)
    
    def load_calibration(self):
        """Load calibration parameters from JSON file."""
        if not self.calibration_file.exists():
            return
        
        with open(self.calibration_file, 'r') as f:
            params = json.load(f)
        
        self.intercept = params.get('intercept', 0.0)
        self.slope = params.get('slope', 1.0)
        self.r_squared = params.get('r_squared', 0.0)
        self.n_samples = params.get('n_samples', 0)
        self.is_fitted = params.get('is_fitted', False)
    
    def get_stats(self) -> Dict:
        """Get calibration statistics."""
        return {
            'is_fitted': self.is_fitted,
            'intercept': self.intercept,
            'slope': self.slope,
            'r_squared': self.r_squared,
            'n_samples': self.n_samples,
            'no_trade_band_bps': self.no_trade_band_bps,
            'formula': f'realized_bps = {self.intercept:.4f} + {self.slope:.4f} * pred_bps' if self.is_fitted else 'Not fitted'
        }


def compute_model_prediction(oi_signal: str, funding_signal: str, cluster_signal: str, 
                            oi_strength: float = 0.0, funding_strength: float = 0.0,
                            cluster_strength: float = 0.0) -> Tuple[float, float, float]:
    """
    Compute raw model prediction from signal components.
    
    This is a placeholder - replace with actual model logic.
    
    Args:
        oi_signal: OI trend signal (BULLISH/BEARISH/NEUTRAL)
        funding_signal: Funding rate signal
        cluster_signal: Cluster signal
        oi_strength, funding_strength, cluster_strength: Signal strengths [0-1]
    
    Returns:
        (pred_raw, pred_bps, confidence)
    """
    # Simple ensemble: weighted average of signals
    signal_map = {'BULLISH': 1.0, 'BEARISH': -1.0, 'NEUTRAL': 0.0}
    
    oi_val = signal_map.get(oi_signal, 0.0) * oi_strength
    funding_val = signal_map.get(funding_signal, 0.0) * funding_strength
    cluster_val = signal_map.get(cluster_signal, 0.0) * cluster_strength
    
    # Weighted average (can be tuned)
    weights = [0.4, 0.3, 0.3]  # OI, Funding, Cluster
    pred_raw = (oi_val * weights[0] + 
                funding_val * weights[1] + 
                cluster_val * weights[2])
    
    # Scale to bps (typical prediction range: -50 to +50 bps)
    pred_bps = pred_raw * 50.0
    
    # Improved confidence calculation:
    # 1. Base confidence from signal strengths (0-1)
    # 2. Boost when signals align (all bullish or all bearish)
    # 3. Reduce when signals conflict
    strengths = [s for s in [oi_strength, funding_strength, cluster_strength] if s > 0]
    base_confidence = np.mean(strengths) if strengths else 0.0
    
    # Signal alignment factor
    signals = [signal_map.get(oi_signal, 0.0), 
               signal_map.get(funding_signal, 0.0), 
               signal_map.get(cluster_signal, 0.0)]
    non_neutral_signals = [s for s in signals if s != 0.0]
    
    if len(non_neutral_signals) >= 2:
        # Check if signals agree
        if all(s > 0 for s in non_neutral_signals):
            # All bullish - boost confidence
            alignment_factor = 1.2
        elif all(s < 0 for s in non_neutral_signals):
            # All bearish - boost confidence  
            alignment_factor = 1.2
        else:
            # Mixed signals - reduce confidence
            alignment_factor = 0.7
    else:
        # Only one signal or all neutral
        alignment_factor = 0.8
    
    # Final confidence (capped at 1.0)
    confidence = min(base_confidence * alignment_factor, 1.0)
    
    return pred_raw, pred_bps, confidence


if __name__ == '__main__':
    # Example usage
    print('=== Prediction Logging & Calibration Pipeline ===\n')
    
    # 1. Create prediction logger
    logger = PredictionLogger()
    
    # 2. Example: Log a prediction
    pred_event = PredictionEvent(
        ts=datetime.now(timezone.utc).isoformat(),
        run_id='test_run',
        session_id='test_session',
        prediction_id='pred_001',
        symbol='BTCUSDT',
        mode='PAPER',
        pred_raw=0.0023,
        pred_bps=23.0,
        oi_signal='BULLISH',
        funding_signal='NEUTRAL',
        cluster_signal='BULLISH',
        confidence=0.75,
        quality_score=0.82
    )
    
    logger.log_prediction(pred_event)
    print(f'✓ Logged prediction: {pred_event.pred_bps:.2f} bps')
    
    # 3. Example: Fit calibration (would need real data)
    calibration = CalibrationPipeline(
        no_trade_band_bps=15.0,
        min_samples_for_fit=200
    )
    
    print(f'\nCalibration stats: {calibration.get_stats()}')
    
    # 4. Example: Apply calibration
    raw_pred_bps = 23.0
    calibrated, should_trade = calibration.apply_calibration(raw_pred_bps)
    
    print(f'\nRaw prediction: {raw_pred_bps:.2f} bps')
    print(f'Calibrated: {calibrated:.2f} bps')
    print(f'Should trade: {should_trade} (|{calibrated:.2f}| >= {calibration.no_trade_band_bps})')
