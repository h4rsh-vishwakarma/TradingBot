"""
Backtest Execution Engine

Simulates trade execution with realistic fills, slippage, commissions,
stop-loss and take-profit logic. Produces detailed trade logs and equity curves.
"""

import pandas as pd
import numpy as np
import logging
from datetime import timezone
from typing import Tuple, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


def run_backtest(
    df: pd.DataFrame,
    strategy,
    initial_capital: float
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Execute backtest simulation with realistic trade execution.
    
    Simulates entries/exits with configurable slippage, commissions, and stop-loss/take-profit.
    Uses next-bar-open execution by default. Applies intra-bar high/low for SL/TP checks.
    
    Args:
        df: OHLCV DataFrame with timezone-aware datetime index and 'signal' column
        strategy: Strategy instance with parameters (slippage, commission, sl, tp, sizing)
        initial_capital: Starting capital in USD
    
    Returns:
        Tuple of (trades_df, equity_curve):
            - trades_df: DataFrame with columns [decision_id, ts_open, ts_close, side,
                         qty, entry_px, exit_px, pnl_usd, r_multiple, slippage_bps,
                         fees_usd, exit_reason, oi_change_pct, funding_rate,
                         cluster_count, expected_price]
            - equity_curve: DataFrame with timestamp index and 'equity' column
    
    Trade Execution Logic:
        - Entry: On signal change from 0→1 or 0→-1 (prevents repeated entries)
        - Fill: Next bar open (or same bar close if enter_on='same_bar')
        - Slippage: Applied to entry and exit (unfavorable direction)
        - Exit: Stop loss OR take profit OR opposing signal
        - SL/TP: Checked against intra-bar high/low (worst-case assumption if both hit)
    
    Example:
        >>> from backtester import load_tradingview_csv, Strategy, run_backtest
        >>> df = load_tradingview_csv('signals.csv')
        >>> strategy = Strategy({'slippage_bps': 5, 'commission_pct': 0.0002,
        ...                      'sl_pct': 0.01, 'tp_pct': 0.02, 'size_usd': 1000})
        >>> trades, equity = run_backtest(df, strategy, initial_capital=10000)
    """
    # Validate inputs
    if df.empty:
        raise ValueError("DataFrame is empty")
    
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("DataFrame index must be DatetimeIndex")
    
    if df.index.tz is None:
        raise ValueError("DataFrame index must be timezone-aware")
    
    required_cols = ['open', 'high', 'low', 'close', 'volume']
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")
    
    # Generate signals from strategy
    signals = strategy.generate_signals(df)
    
    # Initialize tracking
    equity = initial_capital
    position = None  # {'side': 'LONG'/'SHORT', 'qty': float, 'entry_px': float, 'entry_idx': int, 'decision_id': str}
    trades = []
    equity_curve = []
    
    # Extract parameters
    slippage_bps = strategy.slippage_bps
    commission_pct = strategy.commission_pct
    sl_pct = strategy.sl_pct
    tp_pct = strategy.tp_pct
    enter_on = strategy.enter_on
    
    logger.info(f"Starting backtest: capital=${initial_capital:,.2f}, {len(df)} bars")
    logger.info(f"Parameters: slippage={slippage_bps}bps, commission={commission_pct:.4%}, "
                f"sl={sl_pct}, tp={tp_pct}, enter_on={enter_on}")
    
    # Track previous signal to detect changes
    prev_signal = 0
    
    for idx in range(len(df)):
        current_bar = df.iloc[idx]
        current_signal = signals.iloc[idx]
        timestamp = df.index[idx]
        
        # Record equity at each bar
        equity_curve.append({
            'timestamp': timestamp,
            'equity': equity
        })
        
        # Check if we have an open position - evaluate stop loss / take profit
        if position is not None:
            exit_reason = None
            exit_px = None
            
            # Determine SL and TP levels
            if position['side'] == 'LONG':
                sl_level = position['entry_px'] * (1 - sl_pct) if sl_pct else None
                tp_level = position['entry_px'] * (1 + tp_pct) if tp_pct else None
                
                # Check if SL or TP hit using intra-bar high/low
                sl_hit = sl_level and current_bar['low'] <= sl_level
                tp_hit = tp_level and current_bar['high'] >= tp_level
                
                if sl_hit and tp_hit:
                    # Both hit - assume worst case (SL first)
                    exit_reason = 'SL'
                    exit_px = sl_level
                elif sl_hit:
                    exit_reason = 'SL'
                    exit_px = sl_level
                elif tp_hit:
                    exit_reason = 'TP'
                    exit_px = tp_level
                
            else:  # SHORT
                sl_level = position['entry_px'] * (1 + sl_pct) if sl_pct else None
                tp_level = position['entry_px'] * (1 - tp_pct) if tp_pct else None
                
                # Check if SL or TP hit
                sl_hit = sl_level and current_bar['high'] >= sl_level
                tp_hit = tp_level and current_bar['low'] <= tp_level
                
                if sl_hit and tp_hit:
                    # Both hit - assume worst case (SL first)
                    exit_reason = 'SL'
                    exit_px = sl_level
                elif sl_hit:
                    exit_reason = 'SL'
                    exit_px = sl_level
                elif tp_hit:
                    exit_reason = 'TP'
                    exit_px = tp_level
            
            # Check for opposing signal or close signal
            if exit_reason is None:
                if (position['side'] == 'LONG' and current_signal == -1) or \
                   (position['side'] == 'SHORT' and current_signal == 1):
                    exit_reason = 'OPPOSING_SIGNAL'
                    exit_px = current_bar['open']  # Exit at next open
                elif current_signal == 0 and prev_signal != 0:
                    # Explicit close signal (signal went from 1/-1 to 0)
                    exit_reason = 'CLOSE'
                    exit_px = current_bar['open']
            
            # Execute exit if triggered
            if exit_reason:
                # Apply slippage (unfavorable)
                if position['side'] == 'LONG':
                    exit_px = exit_px * (1 - slippage_bps / 10000)  # Worse price for long exit
                else:
                    exit_px = exit_px * (1 + slippage_bps / 10000)  # Worse price for short exit
                
                # Calculate P&L
                if position['side'] == 'LONG':
                    pnl_gross = (exit_px - position['entry_px']) * position['qty']
                else:  # SHORT
                    pnl_gross = (position['entry_px'] - exit_px) * position['qty']
                
                # Calculate fees (entry + exit)
                entry_notional = position['entry_px'] * position['qty']
                exit_notional = exit_px * position['qty']
                fees_usd = (entry_notional + exit_notional) * commission_pct
                
                pnl_net = pnl_gross - fees_usd
                
                # Calculate R-multiple (if SL defined)
                r_multiple = None
                if sl_pct:
                    risk_usd = position['entry_px'] * position['qty'] * sl_pct
                    r_multiple = pnl_net / risk_usd if risk_usd > 0 else 0
                
                # Update equity
                equity += pnl_net
                
                # Record trade
                trades.append({
                    'decision_id': position['decision_id'],
                    'ts_open': df.index[position['entry_idx']],
                    'ts_close': timestamp,
                    'side': position['side'],
                    'qty': position['qty'],
                    'entry_px': position['entry_px'],
                    'exit_px': exit_px,
                    'pnl_usd': pnl_net,
                    'r_multiple': r_multiple,
                    'slippage_bps': slippage_bps,
                    'fees_usd': fees_usd,
                    'exit_reason': exit_reason,
                    'oi_change_pct': None,  # Placeholder for future enhancement
                    'funding_rate': None,    # Placeholder
                    'cluster_count': None,   # Placeholder
                    'expected_price': position['entry_px']
                })
                
                logger.debug(f"Trade closed: {position['side']} @ {exit_px:.2f}, "
                            f"PnL=${pnl_net:.2f}, reason={exit_reason}")
                
                # Clear position
                position = None
        
        # Check for new entry signal (change from 0 to 1 or -1)
        if position is None and current_signal != 0 and prev_signal == 0:
            # Determine entry price
            if enter_on == 'next_open' and idx + 1 < len(df):
                entry_px = df.iloc[idx + 1]['open']
                entry_idx = idx + 1
            elif enter_on == 'same_bar':
                entry_px = current_bar['close']
                entry_idx = idx
            else:
                # Last bar or invalid config - skip entry
                prev_signal = current_signal
                continue
            
            # Apply slippage (unfavorable)
            if current_signal == 1:  # LONG
                entry_px = entry_px * (1 + slippage_bps / 10000)
                side = 'LONG'
            else:  # SHORT
                entry_px = entry_px * (1 - slippage_bps / 10000)
                side = 'SHORT'
            
            # Calculate position size
            if strategy.size_usd is not None:
                # Fixed USD sizing
                qty = strategy.size_usd / entry_px
            else:
                # Risk-based sizing
                risk_usd = equity * strategy.risk_pct
                price_risk_pct = sl_pct  # Distance to stop loss
                qty = risk_usd / (entry_px * price_risk_pct)
            
            # Check if we have enough capital
            notional = entry_px * qty
            if notional > equity:
                logger.warning(f"Insufficient capital for entry: need ${notional:.2f}, have ${equity:.2f}")
                prev_signal = current_signal
                continue
            
            # Open position
            decision_id = f"{timestamp.isoformat()}-{uuid4()}"
            position = {
                'side': side,
                'qty': qty,
                'entry_px': entry_px,
                'entry_idx': entry_idx,
                'decision_id': decision_id
            }
            
            logger.debug(f"Position opened: {side} {qty:.6f} @ {entry_px:.2f}")
        
        prev_signal = current_signal
    
    # Close any remaining open position at last bar
    if position is not None:
        final_bar = df.iloc[-1]
        exit_px = final_bar['close']
        
        # Apply slippage
        if position['side'] == 'LONG':
            exit_px = exit_px * (1 - slippage_bps / 10000)
        else:
            exit_px = exit_px * (1 + slippage_bps / 10000)
        
        # Calculate P&L
        if position['side'] == 'LONG':
            pnl_gross = (exit_px - position['entry_px']) * position['qty']
        else:
            pnl_gross = (position['entry_px'] - exit_px) * position['qty']
        
        # Fees
        entry_notional = position['entry_px'] * position['qty']
        exit_notional = exit_px * position['qty']
        fees_usd = (entry_notional + exit_notional) * commission_pct
        pnl_net = pnl_gross - fees_usd
        
        # R-multiple
        r_multiple = None
        if sl_pct:
            risk_usd = position['entry_px'] * position['qty'] * sl_pct
            r_multiple = pnl_net / risk_usd if risk_usd > 0 else 0
        
        equity += pnl_net
        
        trades.append({
            'decision_id': position['decision_id'],
            'ts_open': df.index[position['entry_idx']],
            'ts_close': df.index[-1],
            'side': position['side'],
            'qty': position['qty'],
            'entry_px': position['entry_px'],
            'exit_px': exit_px,
            'pnl_usd': pnl_net,
            'r_multiple': r_multiple,
            'slippage_bps': slippage_bps,
            'fees_usd': fees_usd,
            'exit_reason': 'END_OF_DATA',
            'oi_change_pct': None,
            'funding_rate': None,
            'cluster_count': None,
            'expected_price': position['entry_px']
        })
        
        logger.info(f"Final position closed at end of data: PnL=${pnl_net:.2f}")
    
    # Add final equity point
    equity_curve.append({
        'timestamp': df.index[-1],
        'equity': equity
    })
    
    # Convert to DataFrames
    trades_df = pd.DataFrame(trades)
    equity_df = pd.DataFrame(equity_curve)
    equity_df.set_index('timestamp', inplace=True)
    
    logger.info(f"Backtest complete: {len(trades)} trades, final equity=${equity:.2f}")
    
    return trades_df, equity_df
