"""
Walk-Forward Out-of-Sample Validation

Implements sliding window train/test validation to assess strategy robustness
on unseen data. Produces aggregated OOS metrics across multiple folds.

Usage:
    python -m backtester.walkforward --input data/tv_signals.csv \\
        --params params.json \\
        --train_days 60 \\
        --test_days 10 \\
        --outdir backtest_artifacts/wf

    python -m backtester.walkforward --input data/tv_signals.csv \\
        --params '{"slippage_bps":5,"commission_pct":0.0002,"sl_pct":0.01,"tp_pct":0.02,"size_usd":500}' \\
        --train_days 90 \\
        --test_days 15 \\
        --outdir backtest_artifacts/wf \\
        --capital 20000
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Any
import pandas as pd
import numpy as np

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtester.data_loader import load_tradingview_csv
from backtester.strategy import Strategy
from backtester.executor import run_backtest
from backtester.metrics import compute_metrics

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def walk_forward(
    df: pd.DataFrame,
    strategy_params: Dict[str, Any],
    initial_capital: float,
    train_days: int = 60,
    test_days: int = 10,
    min_folds: int = 5
) -> Dict[str, Any]:
    """
    Perform walk-forward out-of-sample validation.
    
    Slides a window of train_days followed by test_days across the dataset.
    Currently evaluates the same parameters on each test fold. Future enhancement
    could optimize parameters on the train set.
    
    Args:
        df: Price data with signals (full dataset)
        strategy_params: Strategy parameters to test
        initial_capital: Starting capital for each fold
        train_days: Days for training window (currently unused, but reserved)
        test_days: Days for test window (OOS evaluation)
        min_folds: Minimum number of folds required
    
    Returns:
        Dictionary with:
            - folds: List of fold results (one per test window)
            - oos_metrics_mean: Mean of metrics across folds
            - oos_metrics_std: Std dev of metrics across folds
            - total_folds: Number of folds evaluated
    
    Note:
        Each fold uses a fresh capital allocation (not compounded across folds).
        This isolates each fold's performance for statistical analysis.
    """
    logger.info(f"Starting walk-forward validation")
    logger.info(f"Parameters: train={train_days}d, test={test_days}d, min_folds={min_folds}")
    
    # Calculate fold boundaries
    total_days = (df.index[-1] - df.index[0]).days
    logger.info(f"Total data span: {total_days} days")
    
    folds = []
    current_start = df.index[0]
    fold_num = 0
    
    while True:
        # Define train and test windows
        train_end = current_start + pd.Timedelta(days=train_days)
        test_start = train_end
        test_end = test_start + pd.Timedelta(days=test_days)
        
        # Check if we have enough data for test window
        if test_end > df.index[-1]:
            logger.info(f"Reached end of data after {fold_num} folds")
            break
        
        # Extract test data
        test_mask = (df.index >= test_start) & (df.index < test_end)
        test_df = df[test_mask].copy()
        
        if len(test_df) < 10:
            logger.warning(f"Fold {fold_num + 1}: insufficient test data ({len(test_df)} bars), skipping")
            current_start = test_start
            continue
        
        fold_num += 1
        logger.info(f"\n{'='*60}")
        logger.info(f"Fold {fold_num}: {test_start.date()} to {test_end.date()} ({len(test_df)} bars)")
        
        try:
            # Run backtest on test fold
            strategy = Strategy(strategy_params)
            trades_df, equity_df = run_backtest(test_df, strategy, initial_capital)
            metrics = compute_metrics(trades_df, equity_df, initial_capital)
            
            fold_result = {
                'fold': fold_num,
                'test_start': test_start,
                'test_end': test_end,
                'test_days': (test_end - test_start).days,
                'test_bars': len(test_df),
                **metrics
            }
            folds.append(fold_result)
            
            logger.info(f"Fold {fold_num} results: "
                       f"trades={metrics['total_trades']}, "
                       f"PF={metrics['profit_factor']:.2f}, "
                       f"Sharpe={metrics['sharpe']:.2f}")
            
        except Exception as e:
            logger.error(f"Fold {fold_num} failed: {e}")
            fold_result = {
                'fold': fold_num,
                'test_start': test_start,
                'test_end': test_end,
                'error': str(e),
                'total_trades': 0,
                'profit_factor': 0.0,
                'sharpe': 0.0
            }
            folds.append(fold_result)
        
        # Move to next fold
        current_start = test_start
    
    if fold_num < min_folds:
        logger.warning(f"⚠️  Only {fold_num} folds - need ≥{min_folds} for robust OOS validation")
    
    # Aggregate OOS metrics
    if len(folds) == 0:
        logger.error("No folds completed successfully")
        return {
            'folds': [],
            'oos_metrics_mean': {},
            'oos_metrics_std': {},
            'total_folds': 0
        }
    
    # Extract metric columns
    fold_df = pd.DataFrame(folds)
    metric_cols = ['profit_factor', 'win_rate', 'sharpe', 'net_pnl_usd', 
                   'max_drawdown_pct', 'total_trades']
    available_metrics = [c for c in metric_cols if c in fold_df.columns]
    
    oos_mean = fold_df[available_metrics].mean().to_dict()
    oos_std = fold_df[available_metrics].std().to_dict()
    
    logger.info(f"\n{'='*60}")
    logger.info(f"WALK-FORWARD SUMMARY")
    logger.info(f"{'='*60}")
    logger.info(f"Total folds: {fold_num}")
    logger.info(f"\nOOS Metrics (mean ± std):")
    for metric in available_metrics:
        mean_val = oos_mean[metric]
        std_val = oos_std[metric]
        logger.info(f"  {metric}: {mean_val:.4f} ± {std_val:.4f}")
    
    # Check OOS criteria
    pf_mean = oos_mean.get('profit_factor', 0)
    sharpe_mean = oos_mean.get('sharpe', 0)
    
    if pf_mean >= 1.2 and sharpe_mean >= 0.8:
        logger.info(f"\n✅ OOS validation passed: PF={pf_mean:.2f}≥1.2, Sharpe={sharpe_mean:.2f}≥0.8")
    else:
        logger.info(f"\n⚠️  OOS validation criteria not met: PF={pf_mean:.2f}, Sharpe={sharpe_mean:.2f}")
        logger.info("   For live canary, require profit_factor ≥1.2 and Sharpe ≥0.8 on OOS")
    
    return {
        'folds': folds,
        'oos_metrics_mean': oos_mean,
        'oos_metrics_std': oos_std,
        'total_folds': fold_num
    }


def main():
    parser = argparse.ArgumentParser(
        description='Walk-forward out-of-sample validation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('--input', required=True, help='Path to TradingView CSV file')
    parser.add_argument('--params', required=True, help='JSON string or file path with parameters')
    parser.add_argument('--train_days', type=int, default=60, help='Training window days (default: 60)')
    parser.add_argument('--test_days', type=int, default=10, help='Test window days (default: 10)')
    parser.add_argument('--outdir', required=True, help='Output directory for results')
    parser.add_argument('--capital', type=float, default=10000, help='Initial capital per fold (default: 10000)')
    
    args = parser.parse_args()
    
    # Load data
    logger.info(f"Loading data from {args.input}")
    try:
        df = load_tradingview_csv(args.input)
    except Exception as e:
        logger.error(f"Failed to load data: {e}")
        sys.exit(1)
    
    # Parse parameters
    try:
        if args.params.startswith('{'):
            # JSON string
            strategy_params = json.loads(args.params)
        else:
            # File path
            with open(args.params, 'r') as f:
                strategy_params = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        logger.error(f"Failed to parse parameters: {e}")
        sys.exit(1)
    
    # Create output directory
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    
    # Run walk-forward
    results = walk_forward(
        df=df,
        strategy_params=strategy_params,
        initial_capital=args.capital,
        train_days=args.train_days,
        test_days=args.test_days
    )
    
    # Save results
    # Save fold details
    fold_df = pd.DataFrame(results['folds'])
    fold_df.to_csv(outdir / 'wf_folds.csv', index=False)
    
    # Save aggregated metrics
    summary = {
        'parameters': strategy_params,
        'total_folds': results['total_folds'],
        'oos_metrics_mean': results['oos_metrics_mean'],
        'oos_metrics_std': results['oos_metrics_std']
    }
    
    with open(outdir / 'wf_summary.json', 'w') as f:
        json.dump(summary, f, indent=2, default=str)
    
    logger.info(f"\n💾 Results saved:")
    logger.info(f"   Fold details: {outdir}/wf_folds.csv")
    logger.info(f"   Summary: {outdir}/wf_summary.json")


if __name__ == '__main__':
    main()
