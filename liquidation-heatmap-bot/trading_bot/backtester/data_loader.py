"""
TradingView CSV Data Loader

Loads and normalizes TradingView-exported CSV files with OHLCV data and signal columns.
Handles various column name formats and ensures timezone-aware timestamps.
"""

import pandas as pd
import logging
from datetime import timezone
from typing import Optional

logger = logging.getLogger(__name__)


def load_tradingview_csv(path: str) -> pd.DataFrame:
    """
    Load TradingView-exported CSV with signals and normalize to standard format.
    
    Expected columns (case-insensitive):
        - timestamp: datetime column (will be converted to UTC timezone-aware)
        - open, high, low, close: price columns
        - volume: volume column
        - longSig/LongSig: long entry signal (1 or True for entry, else 0)
        - shortSig/ShortSig: short entry signal (1 or True for entry, else 0)
    
    Returns:
        DataFrame with:
            - Index: timezone-aware datetime (UTC)
            - Columns: open, high, low, close, volume, signal
            - signal: 1 (long), -1 (short), 0 (no signal)
            - Sorted ascending by timestamp
    
    Raises:
        ValueError: If required columns are missing or data is invalid
        FileNotFoundError: If CSV file doesn't exist
    
    Example:
        >>> df = load_tradingview_csv('data/btc_signals.csv')
        >>> df.head()
                                 open      high       low     close    volume  signal
        2024-01-01 00:00:00+00:00  42000.0  42500.0  41800.0  42300.0  1000.0       1
    """
    try:
        # Read CSV
        df = pd.read_csv(path)
        logger.info(f"Loaded CSV from {path}: {len(df)} rows")
        
    except FileNotFoundError:
        raise FileNotFoundError(f"CSV file not found: {path}")
    except Exception as e:
        raise ValueError(f"Error reading CSV file {path}: {e}")
    
    if df.empty:
        raise ValueError(f"CSV file is empty: {path}")
    
    # Normalize column names to lowercase for flexible matching
    df.columns = df.columns.str.lower().str.strip()
    
    # Check required columns
    required_base = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
    missing_base = [col for col in required_base if col not in df.columns]
    
    if missing_base:
        raise ValueError(
            f"Missing required columns: {missing_base}\n"
            f"Found columns: {list(df.columns)}\n"
            f"Required: {required_base} + (longsig/shortsig or longsig/shortsig)"
        )
    
    # Find signal columns (flexible naming)
    long_col = None
    short_col = None
    
    for col in df.columns:
        if col in ['longsig', 'long_sig', 'long']:
            long_col = col
        elif col in ['shortsig', 'short_sig', 'short']:
            short_col = col
    
    if long_col is None or short_col is None:
        raise ValueError(
            f"Missing signal columns. Need longSig and shortSig (or variants).\n"
            f"Found columns: {list(df.columns)}"
        )
    
    logger.info(f"Detected signal columns: {long_col}, {short_col}")
    
    # Parse timestamp to datetime
    try:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
    except Exception as e:
        # Show first few problematic rows
        sample_rows = df['timestamp'].head(3).tolist()
        raise ValueError(
            f"Failed to parse timestamp column: {e}\n"
            f"Sample values: {sample_rows}"
        )
    
    # Make timezone-aware (assume UTC if naive)
    if df['timestamp'].dt.tz is None:
        df['timestamp'] = df['timestamp'].dt.tz_localize(timezone.utc)
        logger.info("Timestamps converted to UTC (were naive)")
    else:
        df['timestamp'] = df['timestamp'].dt.tz_convert(timezone.utc)
        logger.info(f"Timestamps converted to UTC from {df['timestamp'].dt.tz}")
    
    # Normalize signals to single column: 1 (long), -1 (short), 0 (none)
    # Handle boolean or numeric signals
    long_signal = df[long_col].fillna(0).astype(bool).astype(int)
    short_signal = df[short_col].fillna(0).astype(bool).astype(int)
    
    # Create combined signal column
    # If both signals active, prioritize long (conservative choice)
    df['signal'] = 0
    df.loc[short_signal == 1, 'signal'] = -1
    df.loc[long_signal == 1, 'signal'] = 1
    
    signal_counts = df['signal'].value_counts().to_dict()
    logger.info(f"Signal distribution: {signal_counts}")
    
    if df['signal'].abs().sum() == 0:
        logger.warning("WARNING: No signals found in data (all zeros)")
    
    # Select and reorder columns
    output_cols = ['open', 'high', 'low', 'close', 'volume', 'signal']
    df_out = df[['timestamp'] + output_cols].copy()
    
    # Set timestamp as index
    df_out.set_index('timestamp', inplace=True)
    
    # Sort by timestamp
    df_out.sort_index(inplace=True)
    
    # Validate price data
    if (df_out[['open', 'high', 'low', 'close']] <= 0).any().any():
        raise ValueError("Found zero or negative prices in OHLC data")
    
    # Validate high >= low
    invalid_bars = df_out[df_out['high'] < df_out['low']]
    if len(invalid_bars) > 0:
        raise ValueError(
            f"Found {len(invalid_bars)} bars where high < low. "
            f"First invalid: {invalid_bars.index[0]}"
        )
    
    logger.info(f"Data loaded: {len(df_out)} rows, {df_out.index[0]} to {df_out.index[-1]}")
    logger.info(f"Signals: {(df_out['signal'] == 1).sum()} longs, {(df_out['signal'] == -1).sum()} shorts")
    
    return df_out
