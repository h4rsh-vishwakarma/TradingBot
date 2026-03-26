#!/usr/bin/env python3
"""
Batch Backtest Engine — Run ALL strategies across ALL symbols/timeframes in one shot.
Generates individual CSV trade lists per strategy.

Usage:
    python3 scripts/batch_backtest.py
    python3 scripts/batch_backtest.py --strategies "Golden_Cross_Pro,EMA_Break_Momentum"
    python3 scripts/batch_backtest.py --symbols "SOLUSDT,BTCUSDT" --timeframe 4h
"""

import os, sys, json, argparse, logging
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === STRATEGY DEFINITIONS ===
# Each strategy defines: name, logic function, default params
STRATEGIES = {
    "Golden_Cross_Pro": {
        "description": "EMA 50/200 golden cross with ADX filter",
        "logic": "golden_cross",
        "params": {"fast_ema": 50, "slow_ema": 200, "adx_period": 14, "adx_threshold": 25}
    },
    "Ultimate_Entry": {
        "description": "RSI oversold + MACD crossover + EMA trend",
        "logic": "ultimate_entry",
        "params": {"rsi_period": 14, "rsi_oversold": 30, "rsi_overbought": 70, "ema_period": 50}
    },
    "EMA_Break_Momentum": {
        "description": "EMA 8/21 crossover with momentum confirmation",
        "logic": "ema_break",
        "params": {"fast_ema": 8, "slow_ema": 21, "adx_period": 14, "adx_threshold": 25}
    },
    "Volume_Stochastic_MACD": {
        "description": "Volume spike + Stochastic + MACD triple confirm",
        "logic": "volume_stoch_macd",
        "params": {"stoch_k": 14, "stoch_d": 3, "macd_fast": 12, "macd_slow": 26, "macd_signal": 9, "vol_mult": 1.5}
    },
    "Breakout_Volume_ADX": {
        "description": "Bollinger breakout with volume + ADX filter",
        "logic": "breakout_vol_adx",
        "params": {"bb_period": 20, "bb_mult": 2.0, "adx_period": 14, "adx_threshold": 25, "vol_mult": 1.5}
    },
    "EMA_Cloud_Strength": {
        "description": "EMA 8/21/50 cloud with ADX trend strength",
        "logic": "ema_cloud",
        "params": {"ema_fast": 8, "ema_mid": 21, "ema_slow": 50, "adx_period": 14, "adx_threshold": 25}
    },
    # Legacy strategies from tournament
    "Reversed_BarUpDn": {
        "description": "Lookback momentum reversal",
        "logic": "lookback_momentum",
        "params": {"lookback": 21}
    },
    "Reverse_Liquidity_Trap": {
        "description": "Lookback momentum with longer period",
        "logic": "lookback_momentum",
        "params": {"lookback": 19}
    },
    "MVO_Momentum_Variance": {
        "description": "Bollinger band mean reversion",
        "logic": "bollinger_reversion",
        "params": {"period": 22, "mult": 3.6}
    },
    "Machine_Learning_Lorentzian": {
        "description": "Tight Bollinger squeeze",
        "logic": "bollinger_reversion",
        "params": {"period": 9, "mult": 1.61}
    },
    "Mean_Reversion_Scalper": {
        "description": "Ultra-tight Bollinger scalp",
        "logic": "bollinger_reversion",
        "params": {"period": 8, "mult": 1.63}
    },
    "RSI_Divergence": {
        "description": "RSI oversold/overbought reversal with trend filter",
        "logic": "rsi_divergence",
        "params": {"rsi_period": 14, "rsi_oversold": 30, "rsi_overbought": 70, "ema_period": 50}
    },
    "MACD_Histogram_Reversal": {
        "description": "MACD histogram flip with volume confirmation",
        "logic": "macd_histogram",
        "params": {"fast": 12, "slow": 26, "signal": 9, "vol_mult": 1.3}
    },
    "Stochastic_RSI_Cross": {
        "description": "Stochastic RSI crossover in extreme zones",
        "logic": "stoch_rsi_cross",
        "params": {"rsi_period": 14, "stoch_period": 14, "k_smooth": 3, "d_smooth": 3}
    },
    "EMA_Ribbon": {
        "description": "4-EMA ribbon trend direction with momentum",
        "logic": "ema_ribbon",
        "params": {"ema1": 5, "ema2": 13, "ema3": 34, "ema4": 55}
    },
    "Supertrend_ADX": {
        "description": "Supertrend crossover with ADX trend strength",
        "logic": "supertrend_adx",
        "params": {"atr_period": 10, "atr_mult": 3.0, "adx_period": 14, "adx_threshold": 25}
    },
    "Keltner_Channel_Breakout": {
        "description": "Keltner channel breakout with volume spike",
        "logic": "keltner_breakout",
        "params": {"ema_period": 20, "atr_period": 14, "atr_mult": 2.0, "vol_mult": 1.5}
    },
}

# === SYMBOL + TIMEFRAME CONFIG ===
SYMBOL_TIMEFRAMES = {
    "BNBUSDT":  ["4h", "1h"],
    "SOLUSDT":  ["4h", "1h"],
    "ADAUSDT":  ["4h", "1h"],
    "BTCUSDT":  ["4h", "1h"],
    "LINKUSDT": ["4h", "1h"],
    "ETHUSDT":  ["4h", "1h"],
    "DOTUSDT":  ["4h", "1h"],
}

# === STRATEGY ASSIGNMENT (from the priority table) ===
# ALL strategies run on ALL symbol-timeframe combos
ALL_STRATEGIES = list(STRATEGIES.keys())
STRATEGY_ASSIGNMENTS = {}
for sym, tfs in SYMBOL_TIMEFRAMES.items():
    for tf in tfs:
        STRATEGY_ASSIGNMENTS[f"{sym}_{tf}"] = ALL_STRATEGIES


# ================= INDICATOR CALCULATIONS =================

def calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def calc_sma(series, period):
    return series.rolling(period).mean()

def calc_rsi(close, period=14):
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def calc_macd(close, fast=12, slow=26, signal=9):
    ema_fast = calc_ema(close, fast)
    ema_slow = calc_ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, signal)
    return macd_line, signal_line

def calc_adx(high, low, close, period=14):
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()

    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)

    plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.rolling(period).mean()
    return adx

def calc_stochastic(high, low, close, k_period=14, d_period=3):
    lowest_low = low.rolling(k_period).min()
    highest_high = high.rolling(k_period).max()
    k = 100 * (close - lowest_low) / (highest_high - lowest_low).replace(0, np.nan)
    d = k.rolling(d_period).mean()
    return k, d

def calc_bollinger(close, period=20, mult=2.0):
    sma = calc_sma(close, period)
    std = close.rolling(period).std()
    upper = sma + mult * std
    lower = sma - mult * std
    return sma, upper, lower

def calc_vwap(high, low, close, volume):
    """Volume Weighted Average Price — rolling session VWAP."""
    typical_price = (high + low + close) / 3
    cumulative_tp_vol = (typical_price * volume).cumsum()
    cumulative_vol = volume.cumsum()
    vwap = cumulative_tp_vol / cumulative_vol.replace(0, float('nan'))
    return vwap

def calc_obv(close, volume):
    """On Balance Volume — volume direction indicator."""
    direction = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    obv = (volume * direction).cumsum()
    return obv

def calc_obv_trend(close, volume, period=20):
    """OBV trend: True if OBV is rising (bullish volume), False if falling."""
    obv = calc_obv(close, volume)
    obv_ma = obv.rolling(period).mean()
    return obv > obv_ma  # True = bullish volume, False = bearish volume

def calc_atr(high, low, close, period=14):
    """Average True Range — measures volatility."""
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()


# ================= STRATEGY LOGIC =================

def strategy_golden_cross(df, params):
    fast = calc_ema(df['close'], params['fast_ema'])
    slow = calc_ema(df['close'], params['slow_ema'])
    adx = calc_adx(df['high'], df['low'], df['close'], params['adx_period'])

    signals = pd.Series(0, index=df.index)
    signals[(fast > slow) & (fast.shift(1) <= slow.shift(1)) & (adx > params['adx_threshold'])] = 1   # BUY
    signals[(fast < slow) & (fast.shift(1) >= slow.shift(1)) & (adx > params['adx_threshold'])] = -1  # SELL
    return signals

def strategy_ultimate_entry(df, params):
    rsi = calc_rsi(df['close'], params['rsi_period'])
    macd_line, signal_line = calc_macd(df['close'])
    ema = calc_ema(df['close'], params['ema_period'])

    signals = pd.Series(0, index=df.index)
    signals[(rsi < params['rsi_oversold']) & (macd_line > signal_line) & (df['close'] > ema)] = 1
    signals[(rsi > params['rsi_overbought']) & (macd_line < signal_line) & (df['close'] < ema)] = -1
    return signals

def strategy_ema_break(df, params):
    fast = calc_ema(df['close'], params['fast_ema'])
    slow = calc_ema(df['close'], params['slow_ema'])
    adx = calc_adx(df['high'], df['low'], df['close'], params['adx_period'])

    signals = pd.Series(0, index=df.index)
    signals[(fast > slow) & (fast.shift(1) <= slow.shift(1)) & (adx > params['adx_threshold'])] = 1
    signals[(fast < slow) & (fast.shift(1) >= slow.shift(1)) & (adx > params['adx_threshold'])] = -1
    return signals

def strategy_volume_stoch_macd(df, params):
    k, d = calc_stochastic(df['high'], df['low'], df['close'], params['stoch_k'], params['stoch_d'])
    macd_line, signal_line = calc_macd(df['close'], params['macd_fast'], params['macd_slow'], params['macd_signal'])
    vol_ma = df['volume'].rolling(20).mean()
    vol_spike = df['volume'] > vol_ma * params['vol_mult']

    signals = pd.Series(0, index=df.index)
    signals[(k < 20) & (macd_line > signal_line) & vol_spike] = 1
    signals[(k > 80) & (macd_line < signal_line) & vol_spike] = -1
    return signals

def strategy_breakout_vol_adx(df, params):
    sma, upper, lower = calc_bollinger(df['close'], params['bb_period'], params['bb_mult'])
    adx = calc_adx(df['high'], df['low'], df['close'], params['adx_period'])
    vol_ma = df['volume'].rolling(20).mean()
    vol_spike = df['volume'] > vol_ma * params['vol_mult']

    signals = pd.Series(0, index=df.index)
    signals[(df['close'] > upper) & (adx > params['adx_threshold']) & vol_spike] = 1
    signals[(df['close'] < lower) & (adx > params['adx_threshold']) & vol_spike] = -1
    return signals

def strategy_ema_cloud(df, params):
    fast = calc_ema(df['close'], params['ema_fast'])
    mid = calc_ema(df['close'], params['ema_mid'])
    slow = calc_ema(df['close'], params['ema_slow'])
    adx = calc_adx(df['high'], df['low'], df['close'], params['adx_period'])

    signals = pd.Series(0, index=df.index)
    signals[(fast > mid) & (mid > slow) & (adx > params['adx_threshold'])] = 1
    signals[(fast < mid) & (mid < slow) & (adx > params['adx_threshold'])] = -1
    return signals

def strategy_lookback_momentum(df, params):
    lookback = params['lookback']
    signals = pd.Series(0, index=df.index)
    for i in range(lookback, len(df)):
        if df['close'].iloc[i] > df['close'].iloc[i - lookback]:
            signals.iloc[i] = 1
        elif df['close'].iloc[i] < df['close'].iloc[i - lookback]:
            signals.iloc[i] = -1
    return signals

def strategy_bollinger_reversion(df, params):
    sma, upper, lower = calc_bollinger(df['close'], params['period'], params['mult'])
    signals = pd.Series(0, index=df.index)
    signals[df['close'] < lower] = 1   # Buy at lower band
    signals[df['close'] > upper] = -1  # Sell at upper band
    return signals


def strategy_rsi_divergence(df, params):
    rsi = calc_rsi(df['close'], params['rsi_period'])
    ema = calc_ema(df['close'], params['ema_period'])
    signals = pd.Series(0, index=df.index)
    # RSI oversold + price above EMA = buy dip in uptrend
    signals[(rsi < params['rsi_oversold']) & (df['close'] > ema)] = 1
    # RSI overbought + price below EMA = sell rally in downtrend
    signals[(rsi > params['rsi_overbought']) & (df['close'] < ema)] = -1
    return signals

def strategy_macd_histogram(df, params):
    macd_line, signal_line = calc_macd(df['close'], params['fast'], params['slow'], params['signal'])
    histogram = macd_line - signal_line
    vol_ma = df['volume'].rolling(20).mean()
    vol_spike = df['volume'] > vol_ma * params['vol_mult']
    signals = pd.Series(0, index=df.index)
    # Histogram flips positive + volume = buy
    signals[(histogram > 0) & (histogram.shift(1) <= 0) & vol_spike] = 1
    # Histogram flips negative + volume = sell
    signals[(histogram < 0) & (histogram.shift(1) >= 0) & vol_spike] = -1
    return signals

def strategy_stoch_rsi_cross(df, params):
    rsi = calc_rsi(df['close'], params['rsi_period'])
    # Stochastic of RSI
    rsi_low = rsi.rolling(params['stoch_period']).min()
    rsi_high = rsi.rolling(params['stoch_period']).max()
    stoch_rsi = (rsi - rsi_low) / (rsi_high - rsi_low).replace(0, float('nan')) * 100
    k = stoch_rsi.rolling(params['k_smooth']).mean()
    d = k.rolling(params['d_smooth']).mean()
    signals = pd.Series(0, index=df.index)
    # K crosses above D in oversold zone (<20)
    signals[(k > d) & (k.shift(1) <= d.shift(1)) & (k < 30)] = 1
    # K crosses below D in overbought zone (>80)
    signals[(k < d) & (k.shift(1) >= d.shift(1)) & (k > 70)] = -1
    return signals

def strategy_ema_ribbon(df, params):
    e1 = calc_ema(df['close'], params['ema1'])
    e2 = calc_ema(df['close'], params['ema2'])
    e3 = calc_ema(df['close'], params['ema3'])
    e4 = calc_ema(df['close'], params['ema4'])
    signals = pd.Series(0, index=df.index)
    # All EMAs aligned bullish: e1 > e2 > e3 > e4
    signals[(e1 > e2) & (e2 > e3) & (e3 > e4)] = 1
    # All EMAs aligned bearish: e1 < e2 < e3 < e4
    signals[(e1 < e2) & (e2 < e3) & (e3 < e4)] = -1
    return signals

def strategy_supertrend_adx(df, params):
    atr = calc_atr(df['high'], df['low'], df['close'], params['atr_period'])
    adx = calc_adx(df['high'], df['low'], df['close'], params['adx_period'])
    mid = (df['high'] + df['low']) / 2
    upper = mid + params['atr_mult'] * atr
    lower = mid - params['atr_mult'] * atr
    # Simple supertrend: price above lower band = uptrend
    signals = pd.Series(0, index=df.index)
    signals[(df['close'] > upper.shift(1)) & (adx > params['adx_threshold'])] = 1
    signals[(df['close'] < lower.shift(1)) & (adx > params['adx_threshold'])] = -1
    return signals

def strategy_keltner_breakout(df, params):
    ema = calc_ema(df['close'], params['ema_period'])
    atr = calc_atr(df['high'], df['low'], df['close'], params['atr_period'])
    upper = ema + params['atr_mult'] * atr
    lower = ema - params['atr_mult'] * atr
    vol_ma = df['volume'].rolling(20).mean()
    vol_spike = df['volume'] > vol_ma * params['vol_mult']
    signals = pd.Series(0, index=df.index)
    signals[(df['close'] > upper) & vol_spike] = 1
    signals[(df['close'] < lower) & vol_spike] = -1
    return signals

STRATEGY_FUNCTIONS = {
    "golden_cross": strategy_golden_cross,
    "ultimate_entry": strategy_ultimate_entry,
    "ema_break": strategy_ema_break,
    "volume_stoch_macd": strategy_volume_stoch_macd,
    "breakout_vol_adx": strategy_breakout_vol_adx,
    "ema_cloud": strategy_ema_cloud,
    "lookback_momentum": strategy_lookback_momentum,
    "bollinger_reversion": strategy_bollinger_reversion,
    "rsi_divergence": strategy_rsi_divergence,
    "macd_histogram": strategy_macd_histogram,
    "stoch_rsi_cross": strategy_stoch_rsi_cross,
    "ema_ribbon": strategy_ema_ribbon,
    "supertrend_adx": strategy_supertrend_adx,
    "keltner_breakout": strategy_keltner_breakout,
}


# ================= DATA LOADER =================

def fetch_binance_data(symbol, timeframe="4h", days=365*3):
    """Fetch OHLCV data from Binance or load from cache."""
    data_dir = Path("storage/backtest_data")
    data_dir.mkdir(parents=True, exist_ok=True)

    cache_file = data_dir / f"{symbol}_{timeframe}.csv"
    if cache_file.exists():
        df = pd.read_csv(cache_file, parse_dates=['timestamp'])
        logger.info(f"Loaded cached: {cache_file} ({len(df)} rows)")
        return df

    # Try to resample from 15m data if available
    file_15m = data_dir / f"{symbol}_3y_15m.csv"
    if file_15m.exists():
        df = pd.read_csv(file_15m, parse_dates=['timestamp'])
        df = df.set_index('timestamp')

        resample_map = {"1h": "1H", "4h": "4H", "1d": "1D"}
        if timeframe in resample_map:
            df_resampled = df.resample(resample_map[timeframe]).agg({
                'open': 'first', 'high': 'max', 'low': 'min',
                'close': 'last', 'volume': 'sum'
            }).dropna().reset_index()
            df_resampled.to_csv(cache_file, index=False)
            logger.info(f"Resampled {symbol} 15m → {timeframe}: {len(df_resampled)} rows → {cache_file}")
            return df_resampled

    # Fetch from Binance API
    logger.info(f"Fetching {symbol} {timeframe} from Binance API...")
    try:
        import requests
        url = "https://fapi.binance.com/fapi/v1/klines"
        all_data = []
        end_time = int(datetime.now().timestamp() * 1000)

        tf_map = {"1h": "1h", "4h": "4h", "1d": "1d", "15m": "15m"}
        interval = tf_map.get(timeframe, "4h")

        for _ in range(10):  # max 10 batches of 1500
            params = {"symbol": symbol, "interval": interval, "limit": 1500, "endTime": end_time}
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()
            if not data:
                break
            all_data = data + all_data
            end_time = data[0][0] - 1
            if len(data) < 1500:
                break

        df = pd.DataFrame(all_data, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'trades', 'taker_buy_base',
            'taker_buy_quote', 'ignore'
        ])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)
        df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
        df.to_csv(cache_file, index=False)
        logger.info(f"Fetched {symbol} {timeframe}: {len(df)} candles → {cache_file}")
        return df
    except Exception as e:
        logger.error(f"Failed to fetch {symbol} {timeframe}: {e}")
        return None


# ================= BACKTESTER =================

def run_backtest(df, strategy_name, strategy_config, symbol, timeframe,
                 capital=10000, commission_pct=0.1, sl_pct=3.0, tp_pct=5.0,
                 use_atr=True, atr_sl_mult=1.5, atr_tp_mult=2.5, trailing_pct=2.0,
                 max_bars_held=48, use_vwap=True, use_obv=True):
    """
    Run backtest with ATR-based SL/TP and trailing stop.

    Args:
        use_atr: If True, SL/TP based on ATR. If False, use fixed sl_pct/tp_pct.
        atr_sl_mult: SL = entry +/- (ATR * atr_sl_mult)
        atr_tp_mult: TP = entry +/- (ATR * atr_tp_mult)
        trailing_pct: Trail SL at this % behind highest profit point
    """
    logic_name = strategy_config['logic']
    params = strategy_config['params']
    func = STRATEGY_FUNCTIONS.get(logic_name)

    if func is None:
        logger.error(f"Unknown strategy logic: {logic_name}")
        return None

    signals = func(df, params)

    # Pre-compute ATR for dynamic SL/TP
    atr_series = calc_atr(df['high'], df['low'], df['close'], period=14)

    # Pre-compute VWAP and OBV for entry filters
    vwap_series = calc_vwap(df['high'], df['low'], df['close'], df['volume']) if use_vwap else None
    obv_bullish = calc_obv_trend(df['close'], df['volume'], period=20) if use_obv else None

    trades = []
    position = 0  # 0=flat, 1=long, -1=short
    entry_price = 0
    entry_time = None
    entry_idx = 0
    equity = capital
    current_sl = 0      # Dynamic SL (moves with trailing)
    current_tp = 0      # Dynamic TP
    peak_price = 0      # Highest/lowest price since entry (for trailing)

    for i in range(1, len(df)):
        sig = signals.iloc[i]
        price = df['close'].iloc[i]
        ts = df['timestamp'].iloc[i]
        high = df['high'].iloc[i]
        low = df['low'].iloc[i]
        atr_val = atr_series.iloc[i] if not pd.isna(atr_series.iloc[i]) else price * 0.02

        # Check TIME-BASED EXIT first (max holding period)
        if position != 0 and max_bars_held > 0:
            bars_in_trade = i - entry_idx
            if bars_in_trade >= max_bars_held:
                qty = equity * 0.95 / entry_price
                pnl_pct_time = ((price - entry_price) / entry_price * 100) * position
                pnl_usd_time = qty * (price - entry_price) * position
                commission_time = qty * price * commission_pct / 100 * 2
                net_pnl_time = pnl_usd_time - commission_time
                equity += net_pnl_time
                trades.append({
                    'strategy': strategy_name, 'symbol': symbol, 'timeframe': timeframe,
                    'entry_time': entry_time, 'exit_time': ts,
                    'side': 'LONG' if position == 1 else 'SHORT',
                    'entry_price': round(entry_price, 4), 'exit_price': round(price, 4),
                    'sl_price': round(current_sl, 4), 'tp_price': round(current_tp, 4),
                    'qty': round(qty, 6), 'pnl_pct': round(pnl_pct_time, 2),
                    'pnl_usd': round(net_pnl_time, 2), 'equity': round(equity, 2),
                    'exit_reason': 'Time Exit', 'bars_held': bars_in_trade
                })
                position = 0
                continue

        # Check SL/TP/Trailing if in position
        if position != 0:
            # Update trailing stop
            if position == 1:  # Long
                if high > peak_price:
                    peak_price = high
                    # Trail SL: move up when price makes new high
                    trail_sl = peak_price * (1 - trailing_pct / 100)
                    if trail_sl > current_sl:
                        current_sl = trail_sl
                sl_hit = low <= current_sl
                tp_hit = high >= current_tp
            else:  # Short
                if low < peak_price:
                    peak_price = low
                    # Trail SL: move down when price makes new low
                    trail_sl = peak_price * (1 + trailing_pct / 100)
                    if trail_sl < current_sl:
                        current_sl = trail_sl
                sl_hit = high >= current_sl
                tp_hit = low <= current_tp

            if sl_hit or tp_hit:
                if sl_hit:
                    exit_price = current_sl
                    # Check if trailing SL is better than initial SL
                    if position == 1 and current_sl > entry_price:
                        exit_reason = "Trailing-SL (Profit)"
                    elif position == -1 and current_sl < entry_price:
                        exit_reason = "Trailing-SL (Profit)"
                    else:
                        exit_reason = "Stop-Loss"
                else:
                    exit_price = current_tp
                    exit_reason = "Take-Profit"

                pnl_pct = ((exit_price - entry_price) / entry_price * 100) * position
                qty = equity * 0.95 / entry_price
                pnl_usd = qty * (exit_price - entry_price) * position
                commission = qty * exit_price * commission_pct / 100 * 2
                net_pnl = pnl_usd - commission
                equity += net_pnl

                trades.append({
                    'strategy': strategy_name,
                    'symbol': symbol,
                    'timeframe': timeframe,
                    'entry_time': entry_time,
                    'exit_time': ts,
                    'side': 'LONG' if position == 1 else 'SHORT',
                    'entry_price': round(entry_price, 4),
                    'exit_price': round(exit_price, 4),
                    'sl_price': round(current_sl, 4),
                    'tp_price': round(current_tp, 4),
                    'qty': round(qty, 6),
                    'pnl_pct': round(pnl_pct, 2),
                    'pnl_usd': round(net_pnl, 2),
                    'equity': round(equity, 2),
                    'exit_reason': exit_reason,
                    'bars_held': i - entry_idx
                })
                position = 0
                continue

        # New signal — apply VWAP and OBV filters
        if sig != 0 and sig != position:
            # VWAP Filter: only buy below VWAP, sell above VWAP (better entries)
            if use_vwap and vwap_series is not None and not pd.isna(vwap_series.iloc[i]):
                vwap_val = vwap_series.iloc[i]
                if sig == 1 and price > vwap_val * 1.005:  # BUY but price 0.5% above VWAP — skip
                    continue
                if sig == -1 and price < vwap_val * 0.995:  # SELL but price 0.5% below VWAP — skip
                    continue

            # OBV Filter: volume must confirm direction
            if use_obv and obv_bullish is not None and not pd.isna(obv_bullish.iloc[i]):
                if sig == 1 and not obv_bullish.iloc[i]:  # BUY but OBV bearish — skip
                    continue
                if sig == -1 and obv_bullish.iloc[i]:  # SELL but OBV bullish — skip
                    continue

            # Close existing position first (with current SL/TP levels)
            if position != 0:
                pnl_pct = ((price - entry_price) / entry_price * 100) * position
                qty = equity * 0.95 / entry_price
                pnl_usd = qty * (price - entry_price) * position
                commission = qty * price * commission_pct / 100 * 2
                net_pnl = pnl_usd - commission
                equity += net_pnl

                trades.append({
                    'strategy': strategy_name,
                    'symbol': symbol,
                    'timeframe': timeframe,
                    'entry_time': entry_time,
                    'exit_time': ts,
                    'side': 'LONG' if position == 1 else 'SHORT',
                    'entry_price': round(entry_price, 4),
                    'exit_price': round(price, 4),
                    'sl_price': round(current_sl, 4),
                    'tp_price': round(current_tp, 4),
                    'qty': round(qty, 6),
                    'pnl_pct': round(pnl_pct, 2),
                    'pnl_usd': round(net_pnl, 2),
                    'equity': round(equity, 2),
                    'exit_reason': 'Signal Flip',
                    'bars_held': i - entry_idx
                })

            # Open new position with ATR-based SL/TP + trailing
            position = int(sig)
            entry_price = price
            entry_time = ts
            entry_idx = i
            peak_price = price  # Reset trailing tracker

            if use_atr and atr_val > 0:
                if position == 1:  # Long
                    current_sl = entry_price - (atr_val * atr_sl_mult)
                    current_tp = entry_price + (atr_val * atr_tp_mult)
                else:  # Short
                    current_sl = entry_price + (atr_val * atr_sl_mult)
                    current_tp = entry_price - (atr_val * atr_tp_mult)
            else:
                if position == 1:
                    current_sl = entry_price * (1 - sl_pct / 100)
                    current_tp = entry_price * (1 + tp_pct / 100)
                else:
                    current_sl = entry_price * (1 + sl_pct / 100)
                    current_tp = entry_price * (1 - tp_pct / 100)

    return trades


# ================= MAIN =================

def main():
    parser = argparse.ArgumentParser(description="Batch Backtest Engine")
    parser.add_argument("--strategies", type=str, default="", help="Comma-separated strategy names (empty=all)")
    parser.add_argument("--symbols", type=str, default="", help="Comma-separated symbols (empty=all from assignment)")
    parser.add_argument("--timeframe", type=str, default="", help="Override timeframe (e.g., 4h)")
    parser.add_argument("--capital", type=float, default=10000, help="Starting capital (default: $10,000)")
    parser.add_argument("--sl", type=float, default=3.0, help="Stop-loss % (default: 3.0)")
    parser.add_argument("--tp", type=float, default=5.0, help="Take-profit % fallback (default: 5.0)")
    parser.add_argument("--use-atr", action="store_true", default=True, help="Use ATR-based SL/TP")
    parser.add_argument("--no-atr", action="store_true", help="Disable ATR, use fixed SL/TP")
    parser.add_argument("--atr-sl-mult", type=float, default=1.5, help="ATR multiplier for SL (default: 1.5)")
    parser.add_argument("--atr-tp-mult", type=float, default=2.5, help="ATR multiplier for TP (default: 2.5)")
    parser.add_argument("--trail", type=float, default=2.0, help="Trailing stop %% (default: 2.0)")
    parser.add_argument("--max-bars", type=int, default=48, help="Max bars to hold (0=disabled, default: 48)")
    parser.add_argument("--no-vwap", action="store_true", help="Disable VWAP entry filter")
    parser.add_argument("--no-obv", action="store_true", help="Disable OBV entry filter")
    parser.add_argument("--output", type=str, default="storage/backtest_results", help="Output directory")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Determine what to run
    if args.strategies:
        strat_filter = [s.strip() for s in args.strategies.split(",")]
    else:
        strat_filter = None

    summary_rows = []
    total_strategies = 0
    total_trades = 0

    print("=" * 80)
    print("  BATCH BACKTEST ENGINE")
    atr_mode = "ATR" if not getattr(args, 'no_atr', False) else "Fixed"
    vwap_on = "ON" if not getattr(args, 'no_vwap', False) else "OFF"
    obv_on = "ON" if not getattr(args, 'no_obv', False) else "OFF"
    max_b = getattr(args, 'max_bars', 48)
    print(f"  Capital: ${args.capital:,.0f} | SL: {atr_mode} ({getattr(args, 'atr_sl_mult', 1.5)}x ATR) | Trail: {getattr(args, 'trail', 2.0)}%")
    print(f"  VWAP Filter: {vwap_on} | OBV Filter: {obv_on} | Max Hold: {max_b} bars")
    print("=" * 80)

    for assignment_key, strategy_list in STRATEGY_ASSIGNMENTS.items():
        symbol, tf = assignment_key.rsplit("_", 1)

        if args.symbols:
            if symbol not in args.symbols.upper():
                continue
        if args.timeframe:
            tf = args.timeframe

        # Fetch data
        df = fetch_binance_data(symbol, tf)
        if df is None or len(df) < 100:
            logger.warning(f"Insufficient data for {symbol} {tf}, skipping")
            continue

        for strat_name in strategy_list:
            if strat_filter and strat_name not in strat_filter:
                continue

            if strat_name not in STRATEGIES:
                logger.warning(f"Strategy {strat_name} not defined, skipping")
                continue

            config = STRATEGIES[strat_name]
            logger.info(f"Running: {strat_name} on {symbol} {tf}...")

            use_atr = not getattr(args, "no_atr", False)
            trades = run_backtest(df, strat_name, config, symbol, tf,
                                  capital=args.capital, sl_pct=args.sl, tp_pct=args.tp, use_atr=use_atr, atr_sl_mult=getattr(args, "atr_sl_mult", 1.5), atr_tp_mult=getattr(args, "atr_tp_mult", 2.5), trailing_pct=getattr(args, "trail", 2.0), max_bars_held=getattr(args, "max_bars", 48), use_vwap=not getattr(args, "no_vwap", False), use_obv=not getattr(args, "no_obv", False))

            if not trades:
                logger.warning(f"  No trades generated for {strat_name} {symbol} {tf}")
                continue

            # Save individual CSV in TradingView format
            tv_rows = []
            cumulative_pnl = 0
            for idx, t in enumerate(trades, 1):
                cumulative_pnl += t['pnl_usd']
                cum_pct = (cumulative_pnl / args.capital) * 100
                pos_value = t['qty'] * t['entry_price']

                # Entry row (Open Long / Open Short)
                entry_type = f"Open {'Long' if t['side'] == 'LONG' else 'Short'}"
                signal = "Long" if t['side'] == 'LONG' else "Short"
                sl_price = t.get('sl_price', 0)
                tp_price = t.get('tp_price', 0)
                tv_rows.append({
                    'Trade #': idx,
                    'Type': entry_type,
                    'Date and time': t['entry_time'],
                    'Signal': signal,
                    'Price USDT': t['entry_price'],
                    'SL Price': sl_price,
                    'TP Price': tp_price,
                    'Position size (qty)': round(t['qty'], 6),
                    'Position size (value)': round(pos_value, 2),
                    'Net P&L USDT': round(t['pnl_usd'], 2),
                    'Net P&L %': round(t['pnl_pct'], 2),
                    'Favorable excursion USDT': round(abs(t['pnl_usd']) if t['pnl_usd'] > 0 else 0, 2),
                    'Favorable excursion %': round(abs(t['pnl_pct']) if t['pnl_pct'] > 0 else 0, 2),
                    'Adverse excursion USDT': round(abs(t['pnl_usd']) if t['pnl_usd'] < 0 else 0, 2),
                    'Adverse excursion %': round(abs(t['pnl_pct']) if t['pnl_pct'] < 0 else 0, 2),
                    'Cumulative P&L USDT': round(cumulative_pnl, 2),
                    'Cumulative P&L %': round(cum_pct, 2),
                })

                # Exit row (Close Long / Close Short)
                exit_type = f"Close {'Long' if t['side'] == 'LONG' else 'Short'}"
                tv_rows.append({
                    'Trade #': idx,
                    'Type': exit_type,
                    'Date and time': t['exit_time'],
                    'Signal': t['exit_reason'],
                    'Price USDT': t['exit_price'],
                    'SL Price': sl_price,
                    'TP Price': tp_price,
                    'Position size (qty)': round(t['qty'], 6),
                    'Position size (value)': round(pos_value, 2),
                    'Net P&L USDT': round(t['pnl_usd'], 2),
                    'Net P&L %': round(t['pnl_pct'], 2),
                    'Favorable excursion USDT': round(abs(t['pnl_usd']) if t['pnl_usd'] > 0 else 0, 2),
                    'Favorable excursion %': round(abs(t['pnl_pct']) if t['pnl_pct'] > 0 else 0, 2),
                    'Adverse excursion USDT': round(abs(t['pnl_usd']) if t['pnl_usd'] < 0 else 0, 2),
                    'Adverse excursion %': round(abs(t['pnl_pct']) if t['pnl_pct'] < 0 else 0, 2),
                    'Cumulative P&L USDT': round(cumulative_pnl, 2),
                    'Cumulative P&L %': round(cum_pct, 2),
                })

            trades_df = pd.DataFrame(tv_rows)
            from datetime import datetime as dt
            date_str = dt.now().strftime("%Y-%m-%d")
            csv_name = f"{strat_name}_{tf}_BINANCE_{symbol}_{date_str}.csv"
            csv_path = output_dir / csv_name
            trades_df.to_csv(csv_path, index=False)

            # Calculate summary
            wins = len([t for t in trades if t['pnl_usd'] > 0])
            losses = len([t for t in trades if t['pnl_usd'] <= 0])
            total_pnl = sum(t['pnl_usd'] for t in trades)
            final_equity = trades[-1]['equity']
            roi = (final_equity - args.capital) / args.capital * 100
            win_rate = wins / max(len(trades), 1) * 100

            # Max drawdown
            peak = args.capital
            max_dd = 0
            for t in trades:
                if t['equity'] > peak:
                    peak = t['equity']
                dd = (peak - t['equity']) / peak * 100
                if dd > max_dd:
                    max_dd = dd

            summary_rows.append({
                'Strategy': strat_name,
                'Symbol': symbol,
                'Timeframe': tf,
                'Total Trades': len(trades),
                'Wins': wins,
                'Losses': losses,
                'Win Rate %': round(win_rate, 1),
                'Total PnL': round(total_pnl, 2),
                'ROI %': round(roi, 2),
                'Max DD %': round(max_dd, 2),
                'Final Capital': round(final_equity, 2),
                'CSV File': csv_name
            })

            total_strategies += 1
            total_trades += len(trades)

            print(f"  ✅ {strat_name} | {symbol} {tf} | {len(trades)} trades | "
                  f"WR: {win_rate:.0f}% | PnL: ${total_pnl:,.2f} | ROI: {roi:.1f}% | DD: {max_dd:.1f}%")

    # Save summary
    if summary_rows:
        summary_df = pd.DataFrame(summary_rows)
        summary_path = output_dir / "SUMMARY.csv"
        summary_df.to_csv(summary_path, index=False)

        print("\n" + "=" * 80)
        print(f"  BATCH COMPLETE: {total_strategies} strategies | {total_trades} total trades")
        print(f"  Output: {output_dir}/")
        print(f"  Summary: {summary_path}")
        print("=" * 80)

    # Auto-merge results into tournament_winners.csv
    try:
        from merge_to_tournament import merge_results
        summary_file = str(output_dir / "SUMMARY.csv")
        winners_file = str(Path("storage/reports/tournament_winners.csv"))
        merge_results(summary_file, winners_file)
        print("\n  📊 Tournament leaderboard auto-updated!")
    except Exception as e:
        print(f"\n  ⚠️ Tournament merge skipped: {e}")
        print(f"\n  Individual CSVs:")
        for row in summary_rows:
            print(f"    {row['CSV File']}")
    else:
        print("\n  No trades generated. Check data availability and strategy parameters.")


if __name__ == "__main__":
    main()
