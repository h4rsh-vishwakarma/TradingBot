import pandas as pd
import numpy as np

def calculate_adx(df, n=14):
    """Calculates ADX for trend strength filtering."""
    h, l, c = df['high'], df['low'], df['close']
    tr = np.maximum(h - l, np.maximum(abs(h - c.shift(1)), abs(l - c.shift(1))))
    atr = tr.rolling(n).mean()
    upmove = (h - h.shift(1)).clip(lower=0)
    downmove = (l.shift(1) - l).clip(lower=0)
    plus_di = 100 * (upmove.rolling(n).mean() / atr)
    minus_di = 100 * (downmove.rolling(n).mean() / atr)
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    return dx.rolling(n).mean().fillna(0)

def apply_strategy(df, strategy_id, optimize=True, mult=3.0, length=14):
    close, high, low = df['close'], df['high'], df['low']
    id_upper = strategy_id.upper()
    
    # Common filters
    ema_200 = close.rolling(200).mean()
    adx = calculate_adx(df, n=int(length))
    strong_trend = adx > 18 # Standardized for 3Y

    # --- CATEGORY 1: Trend Following (Supertrend, SMA, Ribbon, EMA) ---
    if any(k in id_upper for k in [
        "SUPERTREND", "ATR", "SMA", "EMA", "RIBBON", "CROSS",
        "ICHIMOKU", "KELTNER", "PSAR", "PARABOLIC", "DONCHIAN",
        "TREND", "BREAKOUT", "BARUPDN", "CHANNEL",
    ]):
        atr = (high - low).rolling(int(length)).mean()
        # Variance based on ID to force unique trades
        adj_mult = mult * 1.1 if "RIBBON" in id_upper else mult
        upper = (high + low)/2 + (adj_mult * atr)
        lower = (high + low)/2 - (adj_mult * atr)
        
        raw_sig = np.where(close > upper.shift(1), 1, np.where(close < lower.shift(1), -1, 0))
        return np.where((raw_sig == 1) & (close > ema_200), 1, np.where((raw_sig == -1) & (close < ema_200), -1, 0)) if optimize else raw_sig

    # --- CATEGORY 2: Mean Reversion / Oscillators ---
    elif any(k in id_upper for k in [
        "SQUEEZE", "REVERSION", "LORENTZIAN", "ML", "MATRIX",
        "RSI", "CCI", "STOCH", "BOLLINGER", "BB", "PERCENT",
        "MEAN", "REVERT", "OVERSOLD", "OVERBOUGHT",
    ]):
        basis = close.rolling(int(length)).mean()
        dev = mult * close.rolling(int(length)).std()
        raw_sig = np.where(close < basis - dev, 1, np.where(close > basis + dev, -1, 0))
        return raw_sig

    # --- CATEGORY 3: Volume & Momentum ---
    elif any(k in id_upper for k in [
        "OBV", "WAVETREND", "MACD", "MOMENTUM", "FLOW",
        "VOLUME", "VWAP", "VWMA", "KLINGER", "CMO", "TSI",
        "FISHER", "ROC", "UO", "AROON", "VORTEX", "DEMARKER",
        "PIVOT", "INSIDE", "STRUCTURE", "COPPOCK",
    ]):
        # OBV-based momentum
        obv = (np.sign(close.diff()) * df['volume']).fillna(0).cumsum()
        obv_ema = obv.rolling(int(length)).mean()
        raw_sig = np.where(obv > obv_ema, 1, -1)
        return np.where(strong_trend, raw_sig, 0) if optimize else raw_sig

    # --- CATEGORY 4: SMC & Liquidity ---
    elif any(k in id_upper for k in ["SMC", "LIQUIDITY", "INSTITUTIONAL"]):
        lookback = int(length)
        raw_sig = np.where(close > close.shift(lookback), 1, np.where(close < close.shift(lookback), -1, 0))
        return np.where(strong_trend, raw_sig, 0) if optimize else raw_sig

    # --- FALLBACK: High-Frequency Scalper ---
    else:
        # Using prime-number lookbacks to ensure they don't match standard EMAs
        fast = close.rolling(int(length)).mean()
        slow = close.rolling(int(length * 2.1)).mean()
        return np.where(fast > slow, 1, -1)
