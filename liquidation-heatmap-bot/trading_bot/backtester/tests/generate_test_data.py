"""
Synthetic Test Data Generator

Creates minimal synthetic TradingView CSV files for testing the backtester.
This is used when real TradingView export data is not available.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from pathlib import Path


def generate_synthetic_csv(
    output_path: str,
    start_date: str = "2024-01-01",
    bars: int = 1000,
    initial_price: float = 40000.0,
    signal_frequency: float = 0.05
) -> pd.DataFrame:
    """
    Generate synthetic OHLCV data with random signals for testing.
    
    Args:
        output_path: Path to save CSV file
        start_date: Start date (YYYY-MM-DD format)
        bars: Number of bars to generate
        initial_price: Starting price
        signal_frequency: Probability of signal per bar (0-1)
    
    Returns:
        DataFrame with generated data
    """
    np.random.seed(42)  # Deterministic for tests
    
    # Generate timestamps (1-hour bars)
    start = pd.to_datetime(start_date).tz_localize(timezone.utc)
    timestamps = [start + timedelta(hours=i) for i in range(bars)]
    
    # Generate price series (random walk)
    returns = np.random.normal(0.0001, 0.02, bars)
    prices = initial_price * np.exp(np.cumsum(returns))
    
    # Generate OHLC from close prices
    highs = prices * (1 + np.abs(np.random.normal(0, 0.005, bars)))
    lows = prices * (1 - np.abs(np.random.normal(0, 0.005, bars)))
    opens = np.roll(prices, 1)
    opens[0] = prices[0]
    closes = prices
    
    # Generate volume
    volumes = np.random.uniform(100, 1000, bars)
    
    # Generate signals (sparse)
    long_signals = np.random.random(bars) < signal_frequency
    short_signals = np.random.random(bars) < signal_frequency
    
    # Don't allow both signals on same bar
    both_signals = long_signals & short_signals
    short_signals[both_signals] = False
    
    # Create DataFrame
    df = pd.DataFrame({
        'timestamp': timestamps,
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
        'volume': volumes,
        'longSig': long_signals.astype(int),
        'shortSig': short_signals.astype(int)
    })
    
    # Save to CSV
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    
    print(f"Generated {bars} bars with {long_signals.sum()} long and {short_signals.sum()} short signals")
    print(f"Saved to: {output_path}")
    
    return df


if __name__ == '__main__':
    # Generate sample file for testing
    generate_synthetic_csv(
        'backtester/tests/fixtures/test_signals.csv',
        bars=1000,
        signal_frequency=0.05
    )
