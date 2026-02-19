"""
Parameter Sweep CLI

Command-line interface for grid search across strategy parameters.
Runs multiple backtests with different parameter combinations and produces
a summary CSV for comparison.

Usage:
    # Single run with specific parameters
    python -m backtester.sweep --input data/tv_signals.csv \\
        --params '{"slippage_bps":1,"commission_pct":0.0002,"sl_pct":0.01,"tp_pct":0.02,"size_usd":100}' \\
        --outdir backtest_artifacts/run1

    # Grid sweep across multiple parameter combinations
    python -m backtester.sweep --input data/tv_signals.csv \\
        --grid params.json \\
        --outdir backtest_artifacts/

    # With custom initial capital
    python -m backtester.sweep --input data/tv_signals.csv \\
        --grid params.json \\
        --outdir backtest_artifacts/ \\
        --capital 50000

Example params.json:
    {
      "slippage_bps": [1, 5],
      "commission_pct": [0.0002, 0.0005],
      "sl_pct": [0.005, 0.01],
      "tp_pct": [0.01, 0.02],
      "size_usd": [100, 500]
    }
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from itertools import product
from datetime import datetime
from typing import Dict, List, Any
import pandas as pd

# Add parent directory to path for imports
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


def generate_param_grid(grid_config: Dict[str, List]) -> List[Dict[str, Any]]:
    """
    Generate all combinations from parameter grid.
    
    Args:
        grid_config: Dictionary with parameter names as keys and lists of values
    
    Returns:
        List of parameter dictionaries (one per combination)
    
    Example:
        >>> grid = {"sl_pct": [0.01, 0.02], "tp_pct": [0.02, 0.03]}
        >>> generate_param_grid(grid)
        [
            {"sl_pct": 0.01, "tp_pct": 0.02},
            {"sl_pct": 0.01, "tp_pct": 0.03},
            {"sl_pct": 0.02, "tp_pct": 0.02},
            {"sl_pct": 0.02, "tp_pct": 0.03}
        ]
    """
    keys = list(grid_config.keys())
    values = [grid_config[k] if isinstance(grid_config[k], list) else [grid_config[k]] 
              for k in keys]
    
    combinations = list(product(*values))
    param_sets = [dict(zip(keys, combo)) for combo in combinations]
    
    logger.info(f"Generated {len(param_sets)} parameter combinations")
    return param_sets


def run_single_backtest(
    df: pd.DataFrame,
    params: Dict[str, Any],
    initial_capital: float,
    run_id: str,
    outdir: Path
) -> Dict[str, Any]:
    """
    Run a single backtest and save results.
    
    Args:
        df: Price data with signals
        params: Strategy parameters
        initial_capital: Starting capital
        run_id: Unique identifier for this run
        outdir: Output directory for artifacts
    
    Returns:
        Dictionary with run metadata and metrics
    """
    logger.info(f"Running backtest: {run_id}")
    logger.info(f"Parameters: {params}")
    
    # Create run directory
    run_dir = outdir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        # Initialize strategy and run backtest
        strategy = Strategy(params)
        trades_df, equity_df = run_backtest(df, strategy, initial_capital)
        
        # Compute metrics
        metrics = compute_metrics(trades_df, equity_df, initial_capital)
        
        # Save artifacts
        trades_df.to_csv(run_dir / 'trade_log.csv', index=False)
        equity_df.to_csv(run_dir / 'equity.csv')
        
        with open(run_dir / 'metrics.json', 'w') as f:
            json.dump(metrics, f, indent=2, default=str)
        
        # Safe formatting (handle non-numeric types)
        total_trades = metrics.get('total_trades', 0)
        net_pnl = float(metrics.get('net_pnl_usd', 0)) if metrics.get('net_pnl_usd') is not None else 0.0
        profit_factor = float(metrics.get('profit_factor', 0)) if metrics.get('profit_factor') is not None else 0.0
        
        logger.info(f"✅ Run {run_id} complete: {total_trades} trades, "
                   f"PnL=${net_pnl:.2f}, PF={profit_factor:.2f}")
        
        # Return summary
        result = {
            'run_id': run_id,
            **params,
            **metrics
        }
        return result
        
    except Exception as e:
        logger.error(f"❌ Run {run_id} failed: {e}")
        result = {
            'run_id': run_id,
            **params,
            'error': str(e),
            'total_trades': 0,
            'net_pnl_usd': 0.0,
            'profit_factor': 0.0,
            'win_rate': 0.0,
            'sharpe': 0.0
        }
        return result


def main():
    parser = argparse.ArgumentParser(
        description='Backtest parameter sweep',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('--input', required=True, help='Path to TradingView CSV file')
    parser.add_argument('--params', help='JSON string with single parameter set')
    parser.add_argument('--grid', help='Path to JSON file with parameter grid')
    parser.add_argument('--outdir', required=True, help='Output directory for results')
    parser.add_argument('--capital', type=float, default=10000, help='Initial capital (default: 10000)')
    
    args = parser.parse_args()
    
    # Validate inputs
    if not args.params and not args.grid:
        parser.error('Must specify either --params or --grid')
    
    if args.params and args.grid:
        parser.error('Cannot specify both --params and --grid')
    
    # Load data
    logger.info(f"Loading data from {args.input}")
    try:
        df = load_tradingview_csv(args.input)
    except Exception as e:
        logger.error(f"Failed to load data: {e}")
        sys.exit(1)
    
    # Parse parameters
    if args.params:
        # Single run
        try:
            param_sets = [json.loads(args.params)]
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in --params: {e}")
            sys.exit(1)
    else:
        # Grid sweep
        try:
            with open(args.grid, 'r') as f:
                grid_config = json.load(f)
            param_sets = generate_param_grid(grid_config)
        except FileNotFoundError:
            logger.error(f"Grid file not found: {args.grid}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in grid file: {e}")
            sys.exit(1)
    
    # Create output directory
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    
    # Run backtests
    results = []
    for i, params in enumerate(param_sets, 1):
        run_id = f"run_{i:04d}"
        result = run_single_backtest(df, params, args.capital, run_id, outdir)
        results.append(result)
    
    # Create summary
    summary_df = pd.DataFrame(results)
    
    # Sort by profit factor (descending), then sharpe (descending)
    summary_df = summary_df.sort_values(
        by=['profit_factor', 'sharpe'],
        ascending=[False, False]
    )
    
    # Save summary
    summary_path = outdir / 'summary.csv'
    summary_df.to_csv(summary_path, index=False)
    
    logger.info(f"\n{'='*60}")
    logger.info(f"SWEEP COMPLETE")
    logger.info(f"{'='*60}")
    logger.info(f"Total runs: {len(results)}")
    logger.info(f"Results saved to: {outdir}")
    logger.info(f"Summary: {summary_path}")
    logger.info(f"\nTop 5 parameter sets:")
    
    # Display top results
    display_cols = ['run_id', 'profit_factor', 'sharpe', 'win_rate', 'total_trades', 
                   'net_pnl_usd', 'max_drawdown_pct']
    available_cols = [c for c in display_cols if c in summary_df.columns]
    print(summary_df[available_cols].head().to_string(index=False))
    
    print(f"\n💾 Full results: {summary_path}")
    print(f"📁 Individual run artifacts: {outdir}/run_XXXX/")


if __name__ == '__main__':
    main()
