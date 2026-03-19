import pandas as pd
import numpy as np

def calculate_adx(df, n=14):
    h, l, c = df['high'], df['low'], df['close']
    tr = np.maximum(h - l, np.maximum(abs(h - c.shift(1)), abs(l - c.shift(1))))
    atr = tr.rolling(n).mean()
    upmove = (h - h.shift(1)).clip(lower=0)
    downmove = (l.shift(1) - l).clip(lower=0)
    plus_di = 100 * (upmove.rolling(n).mean() / atr)
    minus_di = 100 * (downmove.rolling(n).mean() / atr)
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    return dx.rolling(n).mean()

def apply_strategy(df, strategy_id, optimize=True):
    close, high, low = df['close'], df['high'], df['low']
    ema200 = close.rolling(200).mean()
    adx = calculate_adx(df)
    
    # --- 🏹 THE ALPHA AGGRESSOR ---
    # Strong trend confirmation
    strong_trend = adx > 25 

    if "SMC" in strategy_id.upper() or "LIQUIDITY" in strategy_id.upper():
        # High-Conviction SMC: Trend + ADX
        raw_sig = np.where(close > close.shift(1), 1, np.where(close < close.shift(1), -1, 0))
        if optimize:
            return np.where((raw_sig == 1) & (close > ema200) & strong_trend, 1,
                    np.where((raw_sig == -1) & (close < ema200) & strong_trend, -1, 0))
        return raw_sig

    elif "SUPERTREND" in strategy_id.upper() or "ATR" in strategy_id.upper():
        atr = (high - low).rolling(10).mean()
        upper = (high + low)/2 + (2.5 * atr) # Tighter bands for more trades
        lower = (high + low)/2 - (2.5 * atr)
        raw_sig = np.where(close > upper.shift(1), 1, np.where(close < lower.shift(1), -1, 0))
        if optimize:
            return np.where(strong_trend, raw_sig, 0)
        return raw_sig

    # Default: EMA Cross for everything else
    ema9, ema21 = close.rolling(9).mean(), close.rolling(21).mean()
    return np.where((ema9 > ema21) & strong_trend, 1, -1)
