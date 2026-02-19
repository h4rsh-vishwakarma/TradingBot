#!/usr/bin/env python3
"""
Calibration runner - fits prediction calibration from historical data.

Usage:
    python3 run_calibration.py --min-samples 200 --no-trade-band 15

This script:
1. Loads predictions from logs/events/prediction.jsonl
2. Loads equity from equity.csv (or health.jsonl)
3. Aligns predictions with realized returns
4. Fits calibration: realized_bps = a + b * pred_bps
5. Saves coefficients to calibration_params.json
6. Computes IC(200) and calibration diagnostics
"""

import argparse
from prediction_logging import PredictionLogger, CalibrationPipeline
import pandas as pd
import json
import numpy as np
from pathlib import Path


def compute_ic_200(predictions_df: pd.DataFrame, equity_df: pd.DataFrame) -> dict:
    """Compute IC(200) metric."""
    # Compute realized returns
    eq = equity_df.copy()
    eq['ts'] = pd.to_datetime(eq['ts'], utc=True)
    eq = eq.set_index('ts').sort_index()
    eq['returns'] = eq['equity_value'].pct_change()
    eq['realized_bps'] = eq['returns'].shift(-1) * 1e4
    
    # Aggregate predictions to bars
    pred = predictions_df.copy()
    pred['ts'] = pd.to_datetime(pred['ts'], utc=True)
    pred['bar'] = pred['ts'].dt.floor('5T')
    pred_agg = pred.groupby('bar')['pred_bps'].last()
    
    # Align
    aligned = pd.merge(
        eq.reset_index(),
        pred_agg.reset_index(),
        left_on='ts',
        right_on='bar',
        how='inner'
    )
    
    aligned = aligned[['pred_bps', 'realized_bps']].dropna()
    
    if len(aligned) < 200:
        return {
            'ic_mean': None,
            'ic_std': None,
            'n_windows': 0,
            'reason': f'Insufficient data: {len(aligned)} < 200'
        }
    
    # Rolling IC(200)
    ic_200 = aligned['pred_bps'].rolling(200).corr(aligned['realized_bps'])
    
    return {
        'ic_mean': float(ic_200.mean()),
        'ic_std': float(ic_200.std()),
        'n_windows': int(ic_200.count()),
        'n_samples': len(aligned)
    }


def main():
    parser = argparse.ArgumentParser(description='Fit prediction calibration')
    parser.add_argument('--min-samples', type=int, default=200, help='Min samples for fitting')
    parser.add_argument('--no-trade-band', type=float, default=15.0, help='No-trade band (bps)')
    parser.add_argument('--equity-file', type=str, default='equity.csv', help='Equity CSV file')
    parser.add_argument('--compute-ic', action='store_true', help='Also compute IC(200)')
    args = parser.parse_args()
    
    print('=== Calibration Runner ===\n')
    
    # Load predictions
    logger = PredictionLogger()
    predictions = logger.load_predictions()
    print(f'Loaded {len(predictions)} predictions')
    
    if len(predictions) == 0:
        print('❌ No predictions found. Start logging predictions first.')
        print('\nTo enable prediction logging:')
        print('1. Ensure prediction_logging.py is imported in signal_generator.py')
        print('2. Call obs_hub.emit_prediction() before decision logic')
        print('3. Restart trading bot')
        return
    
    # Check required columns
    if 'pred_bps' not in predictions.columns:
        print('❌ pred_bps column missing from predictions')
        return
    
    print(f'   Predictions date range: {predictions["ts"].min()} to {predictions["ts"].max()}')
    
    # Load equity
    if not Path(args.equity_file).exists():
        print(f'❌ Equity file not found: {args.equity_file}')
        return
    
    equity = pd.read_csv(args.equity_file)
    print(f'Loaded {len(equity)} equity rows')
    
    if 'equity_value' not in equity.columns:
        print('❌ equity_value column missing from equity.csv')
        return
    
    print(f'   Equity date range: {equity["ts"].min()} to {equity["ts"].max()}')
    
    # Fit calibration
    calibration = CalibrationPipeline(
        no_trade_band_bps=args.no_trade_band,
        min_samples_for_fit=args.min_samples
    )
    
    print(f'\nFitting calibration (min_samples={args.min_samples})...')
    result = calibration.fit_calibration(predictions, equity)
    
    print('\n' + '='*60)
    print('CALIBRATION RESULTS')
    print('='*60)
    
    if result['success']:
        print(f'✅ Calibration fitted and saved to calibration_params.json')
        print(f'\nFormula: {result["formula"]}')
        print(f'R² (goodness of fit): {result["r_squared"]:.4f}')
        print(f'Samples used: {result["n_samples"]}')
        print(f'Intercept: {result["intercept"]:.4f} bps')
        print(f'Slope: {result["slope"]:.4f}')
        print(f'\nNo-trade band: ±{args.no_trade_band} bps')
        
        # Example predictions
        print('\nExample calibrated predictions:')
        for raw_pred in [-30, -15, 0, 15, 30]:
            cal_pred, should_trade = calibration.apply_calibration(raw_pred)
            trade_str = '✅ TRADE' if should_trade else '❌ NO TRADE'
            print(f'  Raw: {raw_pred:+6.1f} bps → Calibrated: {cal_pred:+6.1f} bps [{trade_str}]')
        
    else:
        print(f'❌ Calibration failed: {result["reason"]}')
        print(f'   Samples found: {result["n_samples"]}')
        print(f'   Required: {args.min_samples}')
    
    # Compute IC if requested
    if args.compute_ic:
        print('\n' + '='*60)
        print('IC(200) ANALYSIS')
        print('='*60)
        
        ic_result = compute_ic_200(predictions, equity)
        
        if ic_result['ic_mean'] is not None:
            print(f'✅ IC(200) computed')
            print(f'\nMean IC: {ic_result["ic_mean"]:.4f}')
            print(f'Std IC: {ic_result["ic_std"]:.4f}')
            print(f'Valid windows: {ic_result["n_windows"]}')
            print(f'Samples: {ic_result["n_samples"]}')
            
            # Interpretation
            ic_mean = ic_result['ic_mean']
            if abs(ic_mean) < 0.02:
                print('\n⚠️  IC close to zero - predictions have weak correlation with returns')
            elif ic_mean > 0.05:
                print('\n✅ Positive IC - predictions have predictive power')
            elif ic_mean < -0.05:
                print('\n⚠️  Negative IC - predictions are inversely correlated (consider flipping sign)')
        else:
            print(f'❌ IC(200) not computable: {ic_result["reason"]}')
    
    print('\n' + '='*60)
    print('Next steps:')
    if result['success']:
        print('1. Calibration is now active (loaded automatically on bot restart)')
        print('2. No-trade band will filter predictions < ±15 bps')
        print('3. Monitor performance with new calibrated predictions')
        print('4. Re-run calibration periodically as more data accumulates')
    else:
        print('1. Continue running bot to collect more predictions')
        print(f'2. Need {args.min_samples - result.get("n_samples", 0)} more aligned samples')
        print('3. Re-run this script when sufficient data is available')


if __name__ == '__main__':
    main()
