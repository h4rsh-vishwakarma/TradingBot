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
}

# === SYMBOL + TIMEFRAME CONFIG ===
SYMBOL_TIMEFRAMES = {
    "BNBUSDT":  ["4h"],
    "SOLUSDT":  ["4h", "1h"],
    "ADAUSDT":  ["4h"],
    "BTCUSDT":  ["4h"],
    "LINKUSDT": ["4h"],
    "ETHUSDT":  ["4h"],
}

# === STRATEGY ASSIGNMENT (from the priority table) ===
STRATEGY_ASSIGNMENTS = {
    "BNBUSDT_4h":  ["Golden_Cross_Pro", "EMA_Break_Momentum", "Breakout_Volume_ADX"],
    "SOLUSDT_4h":  ["EMA_Cloud_Strength", "Reversed_BarUpDn"],
    "SOLUSDT_1h":  ["Machine_Learning_Lorentzian", "Mean_Reversion_Scalper"],
    "ADAUSDT_4h":  ["Volume_Stochastic_MACD"],
    "BTCUSDT_4h":  ["Ultimate_Entry", "EMA_Break_Momentum"],
    "LINKUSDT_4h": ["Breakout_Volume_ADX"],
    "ETHUSDT_4h":  ["EMA_Cloud_Strength"],
}


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


STRATEGY_FUNCTIONS = {
    "golden_cross": strategy_golden_cross,
    "ultimate_entry": strategy_ultimate_entry,
    "ema_break": strategy_ema_break,
    "volume_stoch_macd": strategy_volume_stoch_macd,
    "breakout_vol_adx": strategy_breakout_vol_adx,
    "ema_cloud": strategy_ema_cloud,
    "lookback_momentum": strategy_lookback_momentum,
    "bollinger_reversion": strategy_bollinger_reversion,
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
                 capital=10000, commission_pct=0.1, sl_pct=3.0, tp_pct=5.0):
    """Run backtest and return trade list."""
    logic_name = strategy_config['logic']
    params = strategy_config['params']
    func = STRATEGY_FUNCTIONS.get(logic_name)

    if func is None:
        logger.error(f"Unknown strategy logic: {logic_name}")
        return None

    signals = func(df, params)

    trades = []
    position = 0  # 0=flat, 1=long, -1=short
    entry_price = 0
    entry_time = None
    entry_idx = 0
    equity = capital

    for i in range(1, len(df)):
        sig = signals.iloc[i]
        price = df['close'].iloc[i]
        ts = df['timestamp'].iloc[i]
        high = df['high'].iloc[i]
        low = df['low'].iloc[i]

        # Check SL/TP if in position
        if position != 0:
            if position == 1:  # Long
                sl_hit = low <= entry_price * (1 - sl_pct / 100)
                tp_hit = high >= entry_price * (1 + tp_pct / 100)
            else:  # Short
                sl_hit = high >= entry_price * (1 + sl_pct / 100)
                tp_hit = low <= entry_price * (1 - tp_pct / 100)

            if sl_hit or tp_hit:
                if sl_hit:
                    exit_price = entry_price * (1 - sl_pct / 100) if position == 1 else entry_price * (1 + sl_pct / 100)
                    exit_reason = "Stop-Loss"
                else:
                    exit_price = entry_price * (1 + tp_pct / 100) if position == 1 else entry_price * (1 - tp_pct / 100)
                    exit_reason = "Take-Profit"

                pnl_pct = ((exit_price - entry_price) / entry_price * 100) * position
                qty = equity * 0.95 / entry_price
                pnl_usd = qty * (exit_price - entry_price) * position
                commission = qty * exit_price * commission_pct / 100 * 2  # entry + exit
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
                    'qty': round(qty, 6),
                    'pnl_pct': round(pnl_pct, 2),
                    'pnl_usd': round(net_pnl, 2),
                    'equity': round(equity, 2),
                    'exit_reason': exit_reason,
                    'bars_held': i - entry_idx
                })
                position = 0
                continue

        # New signal
        if sig != 0 and sig != position:
            # Close existing position first
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
                    'qty': round(qty, 6),
                    'pnl_pct': round(pnl_pct, 2),
                    'pnl_usd': round(net_pnl, 2),
                    'equity': round(equity, 2),
                    'exit_reason': 'Signal Flip',
                    'bars_held': i - entry_idx
                })

            # Open new position
            position = int(sig)
            entry_price = price
            entry_time = ts
            entry_idx = i

    return trades


# ================= MAIN =================

def main():
    parser = argparse.ArgumentParser(description="Batch Backtest Engine")
    parser.add_argument("--strategies", type=str, default="", help="Comma-separated strategy names (empty=all)")
    parser.add_argument("--symbols", type=str, default="", help="Comma-separated symbols (empty=all from assignment)")
    parser.add_argument("--timeframe", type=str, default="", help="Override timeframe (e.g., 4h)")
    parser.add_argument("--capital", type=float, default=10000, help="Starting capital (default: $10,000)")
    parser.add_argument("--sl", type=float, default=3.0, help="Stop-loss % (default: 3.0)")
    parser.add_argument("--tp", type=float, default=5.0, help="Take-profit % (default: 5.0)")
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
    print(f"  Capital: ${args.capital:,.0f} | SL: {args.sl}% | TP: {args.tp}%")
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

            trades = run_backtest(df, strat_name, config, symbol, tf,
                                  capital=args.capital, sl_pct=args.sl, tp_pct=args.tp)

            if not trades:
                logger.warning(f"  No trades generated for {strat_name} {symbol} {tf}")
                continue

            # Save individual CSV
            trades_df = pd.DataFrame(trades)
            csv_name = f"{strat_name}_{symbol}_{tf}_trades.csv"
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
        print(f"\n  Individual CSVs:")
        for row in summary_rows:
            print(f"    {row['CSV File']}")
    else:
        print("\n  No trades generated. Check data availability and strategy parameters.")


if __name__ == "__main__":
    main()
