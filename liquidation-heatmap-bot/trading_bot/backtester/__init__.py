"""
Backtesting Pipeline for TradingView Signal Analysis

A production-quality backtesting system that consumes TradingView-exported CSV signals
and performs parameter sweeps, OOS walk-forward validation, and produces standardized
backtest artifacts for validation and deployment.

Components:
- data_loader: Load and normalize TradingView CSV signals
- strategy: Strategy base class with parameter configuration
- executor: Backtest execution engine with realistic fills
- metrics: Performance metrics calculation
- sweep: Parameter grid search CLI
- walkforward: Out-of-sample walk-forward validation

Usage:
    from backtester import load_tradingview_csv, Strategy, run_backtest, compute_metrics
"""

__version__ = "1.0.0"

from .data_loader import load_tradingview_csv
from .strategy import Strategy
from .executor import run_backtest
from .metrics import compute_metrics

__all__ = [
    'load_tradingview_csv',
    'Strategy',
    'run_backtest',
    'compute_metrics',
]
