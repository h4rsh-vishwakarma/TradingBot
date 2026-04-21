#!/usr/bin/env python3
"""
Real Indicator Strategy Library (v2)
=====================================
A library of proper indicator-based strategies, each implemented as a pure
signal generator. Each strategy function takes an OHLCV DataFrame + params
and returns a signal array (same length as df): 1 = long, -1 = short, 0 = flat.

These are used by strategy_explorer.py to discover candidate strategies
OUTSIDE the existing tournament universe. The tournament uses category-
keyword matching on strategy names; this library uses genuine indicator
logic so it can find winners that don't exist in the current universe.

Every strategy is parametric so strategy_explorer.py can sweep parameter
grids. To add a new strategy:
  1. Add a `def strat_yourname(df, param_a, param_b, ...)` function below
  2. Add its signature to STRATEGY_REGISTRY
  3. Add parameter grid to DEFAULT_PARAM_GRIDS
  4. strategy_explorer.py picks it up automatically
"""
from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd


# ── Indicator helpers ────────────────────────────────────────────────────────
def _sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=1).mean()


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=1).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    avg_gain = up.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = down.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).fillna(50)


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    prev_close = c.shift(1)
    tr = pd.concat([h - l, (h - prev_close).abs(), (l - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period).mean()


def _stoch(df: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> tuple[pd.Series, pd.Series]:
    low_k = df["low"].rolling(k_period, min_periods=1).min()
    high_k = df["high"].rolling(k_period, min_periods=1).max()
    k = 100 * (df["close"] - low_k) / (high_k - low_k).replace(0, np.nan)
    k = k.fillna(50)
    d = k.rolling(d_period, min_periods=1).mean()
    return k, d


def _macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def _bollinger(close: pd.Series, period: int = 20, std_mult: float = 2.0):
    mid = _sma(close, period)
    std = close.rolling(period, min_periods=period).std()
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    return upper, mid, lower


def _williams_r(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"].rolling(period, min_periods=1).max()
    low = df["low"].rolling(period, min_periods=1).min()
    return -100 * (high - df["close"]) / (high - low).replace(0, np.nan)


def _obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["close"].diff().fillna(0))
    return (direction * df["volume"]).fillna(0).cumsum()


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    plus_dm = h.diff()
    minus_dm = -l.diff()
    plus_dm[plus_dm < 0] = 0.0
    minus_dm[minus_dm < 0] = 0.0
    mask = plus_dm > minus_dm
    minus_dm[mask] = 0.0
    plus_dm[~mask] = 0.0
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, min_periods=period).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, min_periods=period).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, min_periods=period).mean() / atr
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan)) * 100
    adx = dx.ewm(alpha=1 / period, min_periods=period).mean()
    return adx.fillna(0)


# ── Strategy signal generators ───────────────────────────────────────────────
# Contract: each returns a signal array (1=long, -1=short, 0=flat), same length as df

def strat_rsi_mean_reversion(df: pd.DataFrame, period: int = 14,
                             oversold: float = 30, overbought: float = 70) -> np.ndarray:
    rsi = _rsi(df["close"], period)
    sig = np.zeros(len(df), dtype=int)
    sig[rsi < oversold] = 1
    sig[rsi > overbought] = -1
    return sig


def strat_bollinger_reversal(df: pd.DataFrame, period: int = 20,
                             std_mult: float = 2.0) -> np.ndarray:
    upper, mid, lower = _bollinger(df["close"], period, std_mult)
    sig = np.zeros(len(df), dtype=int)
    sig[df["close"] < lower] = 1
    sig[df["close"] > upper] = -1
    return sig


def strat_ema_crossover(df: pd.DataFrame, fast: int = 9, slow: int = 21) -> np.ndarray:
    ef = _ema(df["close"], fast)
    es = _ema(df["close"], slow)
    sig = np.zeros(len(df), dtype=int)
    sig[ef > es] = 1
    sig[ef < es] = -1
    return sig


def strat_macd_cross(df: pd.DataFrame, fast: int = 12, slow: int = 26,
                     signal: int = 9) -> np.ndarray:
    macd_line, sig_line, _ = _macd(df["close"], fast, slow, signal)
    s = np.zeros(len(df), dtype=int)
    s[macd_line > sig_line] = 1
    s[macd_line < sig_line] = -1
    return s


def strat_stoch_kd(df: pd.DataFrame, k_period: int = 14,
                   d_period: int = 3, oversold: float = 20,
                   overbought: float = 80) -> np.ndarray:
    k, d = _stoch(df, k_period, d_period)
    sig = np.zeros(len(df), dtype=int)
    sig[(k < oversold) & (k > d)] = 1
    sig[(k > overbought) & (k < d)] = -1
    return sig


def strat_williams_r(df: pd.DataFrame, period: int = 14,
                     oversold: float = -80, overbought: float = -20) -> np.ndarray:
    w = _williams_r(df, period)
    sig = np.zeros(len(df), dtype=int)
    sig[w < oversold] = 1
    sig[w > overbought] = -1
    return sig


def strat_atr_breakout(df: pd.DataFrame, period: int = 20,
                       atr_period: int = 14, atr_mult: float = 1.5) -> np.ndarray:
    atr = _atr(df, atr_period)
    high_n = df["high"].rolling(period, min_periods=1).max()
    low_n = df["low"].rolling(period, min_periods=1).min()
    sig = np.zeros(len(df), dtype=int)
    sig[df["close"] > high_n.shift(1) + atr_mult * atr] = 1
    sig[df["close"] < low_n.shift(1) - atr_mult * atr] = -1
    return sig


def strat_donchian_breakout(df: pd.DataFrame, period: int = 20) -> np.ndarray:
    high_n = df["high"].rolling(period, min_periods=1).max()
    low_n = df["low"].rolling(period, min_periods=1).min()
    sig = np.zeros(len(df), dtype=int)
    sig[df["close"] >= high_n.shift(1)] = 1
    sig[df["close"] <= low_n.shift(1)] = -1
    return sig


def strat_adx_trend(df: pd.DataFrame, adx_period: int = 14,
                    ma_period: int = 50, threshold: float = 25) -> np.ndarray:
    adx = _adx(df, adx_period)
    ma = _sma(df["close"], ma_period)
    sig = np.zeros(len(df), dtype=int)
    long_cond = (adx > threshold) & (df["close"] > ma)
    short_cond = (adx > threshold) & (df["close"] < ma)
    sig[long_cond] = 1
    sig[short_cond] = -1
    return sig


def strat_obv_trend(df: pd.DataFrame, ma_period: int = 30) -> np.ndarray:
    obv = _obv(df)
    obv_ma = obv.rolling(ma_period, min_periods=1).mean()
    sig = np.zeros(len(df), dtype=int)
    sig[obv > obv_ma] = 1
    sig[obv < obv_ma] = -1
    return sig


def strat_triple_ema(df: pd.DataFrame, fast: int = 5, med: int = 13,
                     slow: int = 34) -> np.ndarray:
    ef = _ema(df["close"], fast)
    em = _ema(df["close"], med)
    es = _ema(df["close"], slow)
    sig = np.zeros(len(df), dtype=int)
    sig[(ef > em) & (em > es)] = 1
    sig[(ef < em) & (em < es)] = -1
    return sig


def strat_rsi_divergence(df: pd.DataFrame, rsi_period: int = 14,
                         lookback: int = 20, threshold: float = 40) -> np.ndarray:
    """Price makes new low while RSI makes higher low (bullish divergence)
    and reverse (bearish divergence)."""
    rsi = _rsi(df["close"], rsi_period)
    price = df["close"]
    rolling_low_price = price.rolling(lookback, min_periods=1).min()
    rolling_low_rsi = rsi.rolling(lookback, min_periods=1).min()
    rolling_high_price = price.rolling(lookback, min_periods=1).max()
    rolling_high_rsi = rsi.rolling(lookback, min_periods=1).max()

    sig = np.zeros(len(df), dtype=int)
    # Bullish div: price at new low, RSI not at new low, RSI oversold-ish
    bullish = (price <= rolling_low_price * 1.001) & (rsi > rolling_low_rsi * 1.05) & (rsi < threshold + 10)
    # Bearish div: price at new high, RSI not at new high, RSI overbought-ish
    bearish = (price >= rolling_high_price * 0.999) & (rsi < rolling_high_rsi * 0.95) & (rsi > 100 - threshold - 10)
    sig[bullish] = 1
    sig[bearish] = -1
    return sig


# ── Registry ─────────────────────────────────────────────────────────────────
StrategyFunc = Callable[..., np.ndarray]

STRATEGY_REGISTRY: dict[str, StrategyFunc] = {
    "V2_RSI_MeanRev": strat_rsi_mean_reversion,
    "V2_Bollinger_Reversal": strat_bollinger_reversal,
    "V2_EMA_Cross": strat_ema_crossover,
    "V2_MACD_Cross": strat_macd_cross,
    "V2_Stoch_KD": strat_stoch_kd,
    "V2_Williams_R": strat_williams_r,
    "V2_ATR_Breakout": strat_atr_breakout,
    "V2_Donchian_Breakout": strat_donchian_breakout,
    "V2_ADX_Trend": strat_adx_trend,
    "V2_OBV_Trend": strat_obv_trend,
    "V2_Triple_EMA": strat_triple_ema,
    "V2_RSI_Divergence": strat_rsi_divergence,
}


# ── Parameter grids for sweep ────────────────────────────────────────────────
DEFAULT_PARAM_GRIDS: dict[str, list[dict]] = {
    "V2_RSI_MeanRev": [
        {"period": 14, "oversold": 30, "overbought": 70},
        {"period": 14, "oversold": 25, "overbought": 75},
        {"period": 21, "oversold": 30, "overbought": 70},
        {"period": 7, "oversold": 20, "overbought": 80},
    ],
    "V2_Bollinger_Reversal": [
        {"period": 20, "std_mult": 2.0},
        {"period": 20, "std_mult": 2.5},
        {"period": 30, "std_mult": 2.0},
        {"period": 14, "std_mult": 1.5},
    ],
    "V2_EMA_Cross": [
        {"fast": 9, "slow": 21},
        {"fast": 5, "slow": 13},
        {"fast": 12, "slow": 26},
        {"fast": 20, "slow": 50},
    ],
    "V2_MACD_Cross": [
        {"fast": 12, "slow": 26, "signal": 9},
        {"fast": 8, "slow": 17, "signal": 9},
        {"fast": 5, "slow": 35, "signal": 5},
    ],
    "V2_Stoch_KD": [
        {"k_period": 14, "d_period": 3, "oversold": 20, "overbought": 80},
        {"k_period": 21, "d_period": 5, "oversold": 20, "overbought": 80},
        {"k_period": 9, "d_period": 3, "oversold": 15, "overbought": 85},
    ],
    "V2_Williams_R": [
        {"period": 14, "oversold": -80, "overbought": -20},
        {"period": 21, "oversold": -85, "overbought": -15},
    ],
    "V2_ATR_Breakout": [
        {"period": 20, "atr_period": 14, "atr_mult": 1.5},
        {"period": 20, "atr_period": 14, "atr_mult": 2.0},
        {"period": 40, "atr_period": 14, "atr_mult": 1.5},
    ],
    "V2_Donchian_Breakout": [
        {"period": 20},
        {"period": 30},
        {"period": 55},
    ],
    "V2_ADX_Trend": [
        {"adx_period": 14, "ma_period": 50, "threshold": 25},
        {"adx_period": 14, "ma_period": 50, "threshold": 20},
        {"adx_period": 14, "ma_period": 100, "threshold": 25},
    ],
    "V2_OBV_Trend": [
        {"ma_period": 30},
        {"ma_period": 50},
    ],
    "V2_Triple_EMA": [
        {"fast": 5, "med": 13, "slow": 34},
        {"fast": 8, "med": 21, "slow": 55},
    ],
    "V2_RSI_Divergence": [
        {"rsi_period": 14, "lookback": 20, "threshold": 40},
        {"rsi_period": 14, "lookback": 50, "threshold": 35},
    ],
}


def get_all_strategies() -> list[tuple[str, StrategyFunc, list[dict]]]:
    """Yield (name, func, param_grid) for each strategy × parameter combo."""
    result = []
    for name, func in STRATEGY_REGISTRY.items():
        grids = DEFAULT_PARAM_GRIDS.get(name, [{}])
        for params in grids:
            result.append((name, func, params))
    return result
