"""
Performance Metrics Calculator

Computes standard trading performance metrics from backtest results.
Includes risk-adjusted returns, drawdown analysis, and trade statistics.
"""

import pandas as pd
import numpy as np
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


def compute_metrics(
    trades_df: pd.DataFrame,
    equity_df: pd.DataFrame,
    initial_capital: float
) -> Dict[str, Any]:
    """
    Compute comprehensive performance metrics from backtest results.
    
    Args:
        trades_df: DataFrame with completed trades (from run_backtest)
        equity_df: DataFrame with equity curve over time
        initial_capital: Starting capital
    
    Returns:
        Dictionary with metrics:
            - total_trades: Number of completed trades
            - net_pnl_usd: Total net profit/loss
            - profit_factor: Gross profit / gross loss
            - win_rate: Percentage of winning trades
            - avg_win_usd: Average winning trade P&L
            - avg_loss_usd: Average losing trade P&L
            - max_drawdown_usd: Maximum equity drawdown in USD
            - max_drawdown_pct: Maximum equity drawdown as percentage
            - sharpe: Annualized Sharpe ratio (from daily returns)
            - trade_rate_per_day: Average trades per day
            - avg_r_multiple: Average R-multiple (requires SL defined)
            - insufficient_trades: Boolean flag if < 30 trades
            - return_pct: Total return percentage
            - avg_trade_pnl: Average P&L per trade
    
    Note:
        - Sharpe calculation uses 252 trading days per year
        - For < 30 trades, statistical significance is limited
        - Profit factor undefined if no losing trades (returns inf)
    
    Example:
        >>> metrics = compute_metrics(trades_df, equity_df, 10000)
        >>> print(f"Profit Factor: {metrics['profit_factor']:.2f}")
        >>> print(f"Win Rate: {metrics['win_rate']:.1%}")
    """
    metrics = {}
    
    # Basic trade statistics
    total_trades = len(trades_df)
    metrics['total_trades'] = total_trades
    metrics['insufficient_trades'] = total_trades < 30
    
    if total_trades < 30:
        logger.warning(
            f"⚠️  Only {total_trades} trades - need ≥30 for reasonable statistical power. "
            f"Treat results as indicative only."
        )
    
    if total_trades == 0:
        logger.warning("No trades executed - returning zero metrics")
        return {
            'total_trades': 0,
            'net_pnl_usd': 0.0,
            'profit_factor': 0.0,
            'win_rate': 0.0,
            'avg_win_usd': 0.0,
            'avg_loss_usd': 0.0,
            'max_drawdown_usd': 0.0,
            'max_drawdown_pct': 0.0,
            'sharpe': 0.0,
            'trade_rate_per_day': 0.0,
            'avg_r_multiple': None,
            'insufficient_trades': True,
            'return_pct': 0.0,
            'avg_trade_pnl': 0.0
        }
    
    # P&L metrics
    net_pnl = trades_df['pnl_usd'].sum()
    metrics['net_pnl_usd'] = net_pnl
    metrics['return_pct'] = (net_pnl / initial_capital) * 100
    metrics['avg_trade_pnl'] = trades_df['pnl_usd'].mean()
    
    # Win/Loss statistics
    winning_trades = trades_df[trades_df['pnl_usd'] > 0]
    losing_trades = trades_df[trades_df['pnl_usd'] < 0]
    
    num_wins = len(winning_trades)
    num_losses = len(losing_trades)
    
    metrics['win_rate'] = (num_wins / total_trades) * 100 if total_trades > 0 else 0
    
    gross_profit = winning_trades['pnl_usd'].sum() if num_wins > 0 else 0
    gross_loss = abs(losing_trades['pnl_usd'].sum()) if num_losses > 0 else 0
    
    metrics['avg_win_usd'] = winning_trades['pnl_usd'].mean() if num_wins > 0 else 0
    metrics['avg_loss_usd'] = losing_trades['pnl_usd'].mean() if num_losses > 0 else 0
    
    # Profit factor
    if gross_loss > 0:
        metrics['profit_factor'] = gross_profit / gross_loss
    elif gross_profit > 0:
        metrics['profit_factor'] = float('inf')  # Only winners
    else:
        metrics['profit_factor'] = 0.0  # No winners or losers
    
    # R-multiple (if available)
    if 'r_multiple' in trades_df.columns and trades_df['r_multiple'].notna().any():
        metrics['avg_r_multiple'] = trades_df['r_multiple'].mean()
    else:
        metrics['avg_r_multiple'] = None
    
    # Drawdown analysis
    equity_series = equity_df['equity']
    cummax = equity_series.cummax()
    drawdown = equity_series - cummax
    
    metrics['max_drawdown_usd'] = abs(drawdown.min())
    metrics['max_drawdown_pct'] = (abs(drawdown.min()) / cummax[drawdown.idxmin()]) * 100 if len(cummax) > 0 else 0
    
    # Sharpe ratio (annualized from daily returns)
    if len(equity_df) > 1:
        # Calculate daily returns
        equity_df_copy = equity_df.copy()
        equity_df_copy['date'] = equity_df_copy.index.date
        daily_equity = equity_df_copy.groupby('date')['equity'].last()
        
        if len(daily_equity) > 1:
            daily_returns = daily_equity.pct_change().dropna()
            
            if len(daily_returns) > 0 and daily_returns.std() > 0:
                sharpe = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252)
                metrics['sharpe'] = sharpe
            else:
                metrics['sharpe'] = 0.0
                logger.warning("Insufficient return variance for Sharpe calculation")
        else:
            metrics['sharpe'] = 0.0
            logger.warning("Insufficient daily data points for Sharpe calculation")
    else:
        metrics['sharpe'] = 0.0
    
    # Trade rate
    if len(equity_df) > 0:
        duration_days = (equity_df.index[-1] - equity_df.index[0]).total_seconds() / 86400
        metrics['trade_rate_per_day'] = total_trades / duration_days if duration_days > 0 else 0
    else:
        metrics['trade_rate_per_day'] = 0
    
    # Log summary
    logger.info(f"Performance Summary:")
    logger.info(f"  Trades: {total_trades}")
    logger.info(f"  Net P&L: ${net_pnl:,.2f} ({metrics['return_pct']:.2f}%)")
    logger.info(f"  Profit Factor: {metrics['profit_factor']:.2f}")
    logger.info(f"  Win Rate: {metrics['win_rate']:.1f}%")
    logger.info(f"  Sharpe: {metrics['sharpe']:.2f}")
    logger.info(f"  Max DD: ${metrics['max_drawdown_usd']:,.2f} ({metrics['max_drawdown_pct']:.1f}%)")
    
    # Validation hints
    if metrics['insufficient_trades']:
        logger.warning("⚠️  Need ≥100 trades for reasonable stat power, else treat results as indicative only.")
    
    if metrics['profit_factor'] >= 1.2 and metrics['sharpe'] >= 0.8 and not metrics['insufficient_trades']:
        logger.info("✅ For live canary, require profit_factor ≥1.2 and Sharpe ≥0.8 on OOS - CRITERIA MET")
    else:
        logger.info("⚠️  For live canary, require profit_factor ≥1.2 and Sharpe ≥0.8 on OOS - NOT MET")
    
    return metrics
