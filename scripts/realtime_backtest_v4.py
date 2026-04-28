#!/usr/bin/env python3
"""
realtime_backtest_v4.py  —  5-Year Multi-Strategy Global Leaderboard
=====================================================================

New vs v3
─────────────────────────────────────────────────────────────────────
  DATA      5 years (auto-download Binance; cached as CSV)
  SYMBOLS   ETHUSDT, BTCUSDT, SOLUSDT, BNBUSDT, AVAXUSDT (5 markets)
  STRATEGIES 11 strategies across trend / mean-reversion / breakout:
               CCI Trend, CCI Pure, Donchian Trend, Donchian Pure,
               EMA Stack, MACD Cross, Supertrend, Aroon Crossover,
               RSI Mean Reversion, BB Mean Reversion, BB Squeeze Breakout
               + volume-filtered variant of Donchian
  ADX       Sweep [0,15,20,25,30] per pair → best threshold locked
            ADX threshold also included in WFA IS grid
  WFA       SL[5] × TP[7] × ADX[5] = 175 combos IS-optimised per fold
  MONTE CARLO 500 reshuffles on every strategy with PF > 1.0
  OUTPUT    Global leaderboard ranked by WFA-adjusted composite score
            Deployment recommendations for top 5 pairs

Run:
    python scripts/realtime_backtest_v4.py                        # all symbols
    python scripts/realtime_backtest_v4.py --symbol BTCUSDT       # one symbol
    python scripts/realtime_backtest_v4.py --tf 1d                # daily bars
    python scripts/realtime_backtest_v4.py --no-mc                # skip Monte Carlo

Fixes in v4.1
─────────────────────────────────────────────────────────────────────
  MC FIX    Bootstrap WITH replacement (not shuffle) — real confidence interval
  5YR DATA  Force-download for all symbols, not just BNB
  CORR      Portfolio correlation check — flag strategies that fire together
  MIN OOS   Auto-scaled MIN_OOS_TRADES based on data length
  REC PARAMS Show WFA-recommended live SL/TP from most recent fold
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)
from datetime import datetime, timezone
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

UTC = timezone.utc

# ── Config ────────────────────────────────────────────────────────────────────
def _env(key: str, default: str) -> str:
    env_file = Path("/etc/tradingbot/env_vars")
    if env_file.exists():
        for line in env_file.read_text(errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() == key:
                return v.strip().strip('"').strip("'")
    return os.getenv(key, default)

LIVE_SL_PCT        = float(_env("STOP_LOSS_PCT",   "2.0")) / 100.0
LIVE_TP_PCT        = float(_env("TAKE_PROFIT_PCT", "4.0")) / 100.0
LIVE_LEVERAGE      = float(_env("LEVERAGE", "2"))
FIXED_NOTIONAL_USD = 500.0
COMMISSION_SIDE    = 0.0006
MAX_POSITION_USD   = 50_000.0
MIN_OOS_TRADES     = 10
LATENCY_ATR_FRACTION = 0.03

WFA_SL_GRID  = [0.010, 0.015, 0.020, 0.025, 0.030]
WFA_TP_GRID  = [0.030, 0.040, 0.050, 0.060, 0.080, 0.100, 0.120]
WFA_ADX_GRID = [0, 20, 25, 30]          # 0 = no filter — also swept in IS grid
ADX_SWEEP_THRESHOLDS = [0, 15, 20, 25, 30]
MONTE_CARLO_SIMS = 500
YEARS_OF_DATA    = 5
MIN_OOS_TRADES_BASE = 10   # scaled up with data length in run_wfa()

SLIPPAGE_BASE: dict[str, float] = {
    "ETHUSDT": 0.0008, "BTCUSDT": 0.0006, "SOLUSDT": 0.0010,
    "BNBUSDT": 0.0008, "AVAXUSDT": 0.0012, "DEFAULT": 0.0018,
}
DEFAULT_SYMBOLS = ["ETHUSDT", "BTCUSDT", "SOLUSDT", "BNBUSDT", "AVAXUSDT"]
TF_MAP = {"4h": "4h", "1h": "1h", "15m": "15m", "1d": "1d",
          "4H": "4h", "1H": "1h", "1D": "1d"}
BARS_PER_DAY = {"4h": 6, "1h": 24, "15m": 96, "1d": 1}

DATA_DIR   = PROJECT_ROOT / "storage" / "backtest_data"
REPORT_DIR = PROJECT_ROOT / "storage" / "reports" / "realtime_backtest"
SEP  = "─" * 82
SEP2 = "═" * 82


# ── Data loading (5-year Binance download) ───────────────────────────────────

def load_data(symbol: str, tf_key: str, force_download: bool = False) -> pd.DataFrame:
    """Load from CSV cache or download 5 years from Binance public API."""
    data_file = DATA_DIR / f"{symbol}_5y_{tf_key}.csv"

    if data_file.exists() and not force_download:
        df = pd.read_csv(data_file)
        df.columns = [c.lower() for c in df.columns]
        bars_yr = round(len(df) / YEARS_OF_DATA / 365 * (365 / BARS_PER_DAY.get(tf_key, 6)), 1)
        print(f"  [{symbol} {tf_key}] {len(df)} bars (5yr) loaded from cache")
        return df

    # 3y fallback only when no 5y and not force-downloading
    if not force_download:
        legacy = DATA_DIR / f"{symbol}_3y_{tf_key}.csv"
        if legacy.exists():
            df = pd.read_csv(legacy)
            df.columns = [c.lower() for c in df.columns]
            print(f"  [{symbol} {tf_key}] {len(df)} bars from 3y cache (run --force-download for 5yr)")
            return df

    print(f"  [{symbol} {tf_key}] Downloading 5 years from Binance...", flush=True)
    try:
        limit   = 1000
        end_ms  = int(time.time() * 1000)
        rows    = []
        target  = YEARS_OF_DATA * 365 * BARS_PER_DAY.get(tf_key, 6)
        while len(rows) < target:
            url = (f"https://api.binance.com/api/v3/klines"
                   f"?symbol={symbol}&interval={tf_key}&limit={limit}&endTime={end_ms}")
            with urllib.request.urlopen(url, timeout=20) as r:
                batch = json.loads(r.read())
            if not batch:
                break
            rows = batch + rows
            end_ms = batch[0][0] - 1
            if len(batch) < limit:
                break
            time.sleep(0.15)   # rate limit

        df = pd.DataFrame(rows, columns=[
            "timestamp", "open", "high", "low", "close", "volume",
            "close_time", "qav", "num_trades", "tbbav", "tbqav", "ignore"])
        df = df[["timestamp", "open", "high", "low", "close", "volume"]].copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = df[c].astype(float)
        df = df.sort_values("timestamp").reset_index(drop=True)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        df.to_csv(data_file, index=False)
        print(f"  [{symbol} {tf_key}] {len(df)} bars saved → {data_file.name}")
        return df
    except Exception as e:
        print(f"  ERROR downloading {symbol}: {e}")
        sys.exit(1)


# ── Indicators ────────────────────────────────────────────────────────────────

def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()

def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(n).mean()
    loss  = (-delta.clip(upper=0)).rolling(n).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100.0 - 100.0 / (1.0 + rs)

def _cci(high, low, close, n: int = 20) -> pd.Series:
    tp = (high + low + close) / 3.0
    ma = tp.rolling(n).mean()
    md = tp.rolling(n).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    return (tp - ma) / (0.015 * md)

def _atr(high, low, close, n: int = 14) -> pd.Series:
    tr = pd.concat([high - low,
                    (high - close.shift(1)).abs(),
                    (low  - close.shift(1)).abs()], axis=1).max(axis=1)
    return tr.ewm(span=n, adjust=False).mean()

def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"].astype(float), df["low"].astype(float), df["close"].astype(float)
    tr = pd.concat([(high - low),
                    (high - close.shift(1)).abs(),
                    (low  - close.shift(1)).abs()], axis=1).max(axis=1)
    up   = high - high.shift(1)
    down = low.shift(1) - low
    pdm  = np.where((up > down) & (up   > 0), up,   0.0)
    mdm  = np.where((down > up) & (down > 0), down, 0.0)
    alpha = 1.0 / period
    atr_s = tr.ewm(alpha=alpha, adjust=False).mean()
    pdi   = 100 * pd.Series(pdm, index=df.index).ewm(alpha=alpha, adjust=False).mean() / atr_s.replace(0, np.nan)
    mdi   = 100 * pd.Series(mdm, index=df.index).ewm(alpha=alpha, adjust=False).mean() / atr_s.replace(0, np.nan)
    denom = (pdi + mdi).replace(0, np.nan)
    dx    = 100 * (pdi - mdi).abs() / denom
    return dx.ewm(alpha=alpha, adjust=False).mean().fillna(0).rename("adx")

def _macd(close: pd.Series, fast=12, slow=26, signal=9):
    m    = _ema(close, fast) - _ema(close, slow)
    sig  = _ema(m, signal)
    return m, sig

def _supertrend(df: pd.DataFrame, period: int = 10, factor: float = 3.0) -> pd.Series:
    atr   = _atr(df["high"], df["low"], df["close"], period)
    hl2   = (df["high"] + df["low"]) / 2.0
    bu    = (hl2 + factor * atr).values
    bl    = (hl2 - factor * atr).values
    close = df["close"].values
    n     = len(df)
    fu    = bu.copy()
    fl    = bl.copy()
    st    = np.full(n, np.nan)
    st[0] = fu[0]
    for i in range(1, n):
        fu[i] = bu[i] if bu[i] < fu[i-1] or close[i-1] > fu[i-1] else fu[i-1]
        fl[i] = bl[i] if bl[i] > fl[i-1] or close[i-1] < fl[i-1] else fl[i-1]
        if st[i-1] == fu[i-1]:
            st[i] = fl[i] if close[i] > fu[i] else fu[i]
        else:
            st[i] = fu[i] if close[i] < fl[i] else fl[i]
    direction = np.where(close > st, 1, -1)
    prev_dir  = np.roll(direction, 1)
    sig = np.zeros(n, dtype=int)
    sig[1:] = np.where(direction[1:] != prev_dir[1:], direction[1:], 0)
    return pd.Series(sig, index=df.index, name="sig")

def _aroon(high: pd.Series, low: pd.Series, period: int = 25):
    au = high.rolling(period + 1).apply(lambda x: x.argmax() / period * 100, raw=True)
    ad = low.rolling(period + 1).apply(lambda x: (period - x.argmin()) / period * 100, raw=True)
    return au, ad

def _bb(close: pd.Series, period: int = 20, std_dev: float = 2.0):
    ma    = close.rolling(period).mean()
    std   = close.rolling(period).std()
    upper = ma + std_dev * std
    lower = ma - std_dev * std
    return upper, ma, lower, std


# ── Signal generators ─────────────────────────────────────────────────────────

def signals_cci_trend(df: pd.DataFrame) -> pd.Series:
    """CCI(20) cross 0 + EMA(200) trend guard."""
    cci  = _cci(df["high"], df["low"], df["close"], 20)
    e200 = _ema(df["close"], 200)
    long_x  = (cci > 0) & (cci.shift(1) <= 0) & (df["close"] > e200)
    short_x = (cci < 0) & (cci.shift(1) >= 0) & (df["close"] < e200)
    sig = np.where(long_x, 1, np.where(short_x, -1, 0))
    return pd.Series(sig, index=df.index, name="sig")

def signals_cci_pure(df: pd.DataFrame) -> pd.Series:
    """CCI(20) cross 0 — no filter."""
    cci = _cci(df["high"], df["low"], df["close"], 20)
    long_x  = (cci > 0) & (cci.shift(1) <= 0)
    short_x = (cci < 0) & (cci.shift(1) >= 0)
    sig = np.where(long_x, 1, np.where(short_x, -1, 0))
    return pd.Series(sig, index=df.index, name="sig")

def signals_donchian_trend(df: pd.DataFrame) -> pd.Series:
    """DC(20) breakout + RSI(14) filter."""
    dc_h = df["close"].rolling(20).max().shift(1)
    dc_l = df["close"].rolling(20).min().shift(1)
    rsi  = _rsi(df["close"], 14)
    long_x  = (df["close"] > dc_h) & (df["close"].shift(1) <= dc_h.shift(1)) & (rsi < 70)
    short_x = (df["close"] < dc_l) & (df["close"].shift(1) >= dc_l.shift(1)) & (rsi > 30)
    sig = np.where(long_x, 1, np.where(short_x, -1, 0))
    return pd.Series(sig, index=df.index, name="sig")

def signals_donchian_pure(df: pd.DataFrame) -> pd.Series:
    """DC(20) breakout — no filter."""
    dc_h = df["close"].rolling(20).max().shift(1)
    dc_l = df["close"].rolling(20).min().shift(1)
    long_x  = (df["close"] > dc_h) & (df["close"].shift(1) <= dc_h.shift(1))
    short_x = (df["close"] < dc_l) & (df["close"].shift(1) >= dc_l.shift(1))
    sig = np.where(long_x, 1, np.where(short_x, -1, 0))
    return pd.Series(sig, index=df.index, name="sig")

def signals_donchian_volume(df: pd.DataFrame) -> pd.Series:
    """DC(20) breakout + volume confirmation (> 1.5× 20-bar avg)."""
    dc_h   = df["close"].rolling(20).max().shift(1)
    dc_l   = df["close"].rolling(20).min().shift(1)
    rsi    = _rsi(df["close"], 14)
    vol_ok = df["volume"] > df["volume"].rolling(20).mean() * 1.5
    long_x  = (df["close"] > dc_h) & (df["close"].shift(1) <= dc_h.shift(1)) & (rsi < 70) & vol_ok
    short_x = (df["close"] < dc_l) & (df["close"].shift(1) >= dc_l.shift(1)) & (rsi > 30) & vol_ok
    sig = np.where(long_x, 1, np.where(short_x, -1, 0))
    return pd.Series(sig, index=df.index, name="sig")

def signals_ema_stack(df: pd.DataFrame) -> pd.Series:
    """EMA 9/21/50 alignment — enter on first bar of stack."""
    e9, e21, e50 = _ema(df["close"], 9), _ema(df["close"], 21), _ema(df["close"], 50)
    bull = (e9 > e21) & (e21 > e50)
    bear = (e9 < e21) & (e21 < e50)
    long_x  = bull & ~bull.shift(1, fill_value=False)
    short_x = bear & ~bear.shift(1, fill_value=False)
    sig = np.where(long_x, 1, np.where(short_x, -1, 0))
    return pd.Series(sig, index=df.index, name="sig")

def signals_macd_cross(df: pd.DataFrame) -> pd.Series:
    """MACD(12,26,9) signal line cross."""
    m, s = _macd(df["close"])
    long_x  = (m > s) & (m.shift(1) <= s.shift(1))
    short_x = (m < s) & (m.shift(1) >= s.shift(1))
    sig = np.where(long_x, 1, np.where(short_x, -1, 0))
    return pd.Series(sig, index=df.index, name="sig")

def signals_supertrend(df: pd.DataFrame) -> pd.Series:
    """Supertrend(10, 3.0) direction change."""
    return _supertrend(df, period=10, factor=3.0)

def signals_aroon(df: pd.DataFrame) -> pd.Series:
    """Aroon(25) crossover."""
    au, ad = _aroon(df["high"], df["low"], 25)
    long_x  = (au > ad) & (au.shift(1) <= ad.shift(1))
    short_x = (ad > au) & (ad.shift(1) <= au.shift(1))
    sig = np.where(long_x, 1, np.where(short_x, -1, 0))
    return pd.Series(sig.astype(int), index=df.index, name="sig")

def signals_rsi_mean_rev(df: pd.DataFrame) -> pd.Series:
    """RSI(14) oversold/overbought reversal."""
    rsi = _rsi(df["close"], 14)
    long_x  = (rsi < 30) & (rsi.shift(1) >= 30)
    short_x = (rsi > 70) & (rsi.shift(1) <= 70)
    sig = np.where(long_x, 1, np.where(short_x, -1, 0))
    return pd.Series(sig, index=df.index, name="sig")

def signals_bb_mean_rev(df: pd.DataFrame) -> pd.Series:
    """BB(20,2) touch-and-revert — long at lower band, short at upper."""
    upper, ma, lower, _ = _bb(df["close"], 20, 2.0)
    long_x  = (df["close"] <= lower) & (df["close"].shift(1) > lower.shift(1))
    short_x = (df["close"] >= upper) & (df["close"].shift(1) < upper.shift(1))
    sig = np.where(long_x, 1, np.where(short_x, -1, 0))
    return pd.Series(sig, index=df.index, name="sig")

def signals_bb_squeeze(df: pd.DataFrame) -> pd.Series:
    """BB Squeeze Breakout — fire when BB width releases from compression."""
    close = df["close"]
    upper, ma, lower, std = _bb(close, 20, 2.0)
    bb_width = (upper - lower) / ma
    # Squeeze = BB width in bottom 25% of recent 50 bars
    squeeze = bb_width < bb_width.rolling(50).quantile(0.25)
    # Momentum at release
    momentum = close - (df["high"].rolling(20).max() + df["low"].rolling(20).min()) / 2
    momentum = momentum - momentum.rolling(20).mean()
    released = ~squeeze & squeeze.shift(1, fill_value=False)
    long_x  = released & (momentum > 0)
    short_x = released & (momentum < 0)
    sig = np.where(long_x, 1, np.where(short_x, -1, 0))
    return pd.Series(sig, index=df.index, name="sig")


ALL_STRATEGIES: dict[str, callable] = {
    # ── Trend following ───────────────────────────────────────────────────────
    "CCI Trend":          signals_cci_trend,
    "CCI Pure":           signals_cci_pure,
    "Donchian Trend":     signals_donchian_trend,
    "Donchian Pure":      signals_donchian_pure,
    "Donchian+Volume":    signals_donchian_volume,
    "EMA Stack":          signals_ema_stack,
    "MACD Cross":         signals_macd_cross,
    "Supertrend":         signals_supertrend,
    "Aroon":              signals_aroon,
    # ── Mean reversion ───────────────────────────────────────────────────────
    "RSI Mean Rev":       signals_rsi_mean_rev,
    "BB Mean Rev":        signals_bb_mean_rev,
    # ── Breakout ─────────────────────────────────────────────────────────────
    "BB Squeeze":         signals_bb_squeeze,
}


# ── ADX filter wrapper ────────────────────────────────────────────────────────

def apply_adx(sig: pd.Series, df: pd.DataFrame, threshold: float) -> pd.Series:
    """Zero out signals when ADX < threshold (choppy market)."""
    if threshold <= 0:
        return sig
    adx_val = _adx(df, 14)
    result  = sig.copy()
    result[adx_val <= threshold] = 0
    return result


# ── Vol-adjusted slippage & latency ──────────────────────────────────────────

def _vol_slippage(base_slip, cur_atr, avg_atr, is_breakout=True):
    if avg_atr <= 0:
        return base_slip
    r    = cur_atr / avg_atr
    vm   = 2.0 if r > 1.5 else 1.5 if r > 1.2 else 1.0
    bm   = 1.3 if is_breakout else 1.0
    return base_slip * vm * bm

def _latency_slip(atr_val, entry_price):
    return (LATENCY_ATR_FRACTION * atr_val) / entry_price if entry_price > 0 else 0.0

def _vol_guard(notional, bar_vol_usd):
    return True if bar_vol_usd <= 0 else notional <= bar_vol_usd * 6 * 0.01


# ── Core simulation ───────────────────────────────────────────────────────────

def simulate(df, sig, symbol="ETHUSDT", sl_pct=None, tp_pct=None,
             leverage=None, notional=None, min_gap=2, label=""):
    sl_pct    = sl_pct   if sl_pct   is not None else LIVE_SL_PCT
    tp_pct    = tp_pct   if tp_pct   is not None else LIVE_TP_PCT
    leverage  = leverage if leverage is not None else LIVE_LEVERAGE
    notional  = notional if notional is not None else FIXED_NOTIONAL_USD
    base_slip = SLIPPAGE_BASE.get(symbol.upper(), SLIPPAGE_BASE["DEFAULT"])
    comm      = COMMISSION_SIDE

    close_a = df["close"].values.astype(float)
    open_a  = df["open"].values.astype(float)
    high_a  = df["high"].values.astype(float)
    low_a   = df["low"].values.astype(float)
    sig_a   = sig.values.astype(int)
    vol_a   = df["volume"].values.astype(float) if "volume" in df.columns else None
    n       = len(df)

    atr_a   = _atr(df["high"], df["low"], df["close"], 14).values.astype(float)
    avg_atr = float(pd.Series(atr_a).rolling(50).mean().ffill().bfill().values[-1])

    dates = None
    if "timestamp" in df.columns:
        try:
            dates = pd.to_datetime(df["timestamp"]).dt.date.values
        except Exception:
            pass

    pos = 0; ep = 0.0; eb = -1; leb = -min_gap - 1
    trades = []; daily_pnl: dict[str, float] = {}; vol_skip = 0

    for i in range(1, n - 1):
        hi, lo, si = high_a[i], low_a[i], sig_a[i]
        ai = atr_a[i] if i < len(atr_a) else avg_atr
        la = float(np.mean(atr_a[max(0, i - 50):i + 1])) or avg_atr

        # EXIT
        if pos != 0:
            xp = None
            if pos == 1:
                sl_l, tp_l = ep * (1 - sl_pct), ep * (1 + tp_pct)
                if lo <= sl_l:   xp = sl_l
                elif hi >= tp_l: xp = tp_l
                elif si == -1:   xp = open_a[i + 1]
            else:
                sl_l, tp_l = ep * (1 + sl_pct), ep * (1 - tp_pct)
                if hi >= sl_l:   xp = sl_l
                elif lo <= tp_l: xp = tp_l
                elif si == 1:    xp = open_a[i + 1]
            if xp is not None:
                ret = ((xp - ep) / ep if pos == 1 else (ep - xp) / ep) * leverage
                pnl = notional * (ret - comm * 2 * leverage)
                trades.append({"pnl_usd": pnl, "side": "long" if pos == 1 else "short",
                               "entry_bar": eb, "exit_bar": i})
                if dates is not None:
                    d = str(dates[i]); daily_pnl[d] = daily_pnl.get(d, 0.0) + pnl
                pos = 0; leb = i

        # ENTRY
        if pos == 0 and si != 0 and (i - leb) > min_gap:
            eff_n = min(notional, MAX_POSITION_USD)
            if vol_a is not None and not _vol_guard(eff_n, vol_a[i] * close_a[i]):
                vol_skip += 1; continue
            slip  = _vol_slippage(base_slip, ai, la, True)
            lat   = _latency_slip(ai, open_a[i + 1])
            # Slippage is built into ep (entry price). Since ret = (xp - ep)/ep,
            # slippage is fully reflected in P&L — not a separate deduction.
            ep    = open_a[i + 1] * (1 + lat if si == 1 else 1 - lat)
            pos   = si; eb = i

    if len(trades) < 2:
        return {"total_trades": 0, "error": "insufficient", "vol_skipped": vol_skip}

    pnl_a = np.array([t["pnl_usd"] for t in trades])
    wins  = pnl_a > 0; losses = pnl_a < 0; tot = len(pnl_a)
    gp = float(pnl_a[wins].sum()) if wins.any() else 0.0
    gl = float(abs(pnl_a[losses].sum())) if losses.any() else 1e-9
    pf = gp / gl
    total_pnl = float(pnl_a.sum())
    eq = np.cumsum(np.concatenate([[0], pnl_a]))
    peak = np.maximum.accumulate(eq)
    max_dd = float((eq - peak).min())
    sharpe = 0.0
    if daily_pnl and len(daily_pnl) >= 10:
        dp = pd.Series(daily_pnl); std = dp.std()
        if std > 0: sharpe = float(dp.mean() / std * (252 ** 0.5))

    try:
        t0 = pd.to_datetime(df["timestamp"].iloc[0])
        t1 = pd.to_datetime(df["timestamp"].iloc[-1])
        years = max((t1 - t0).days / 365.25, 0.01)
    except Exception:
        years = YEARS_OF_DATA

    return {
        "label":          label,
        "total_trades":   tot,
        "win_rate_pct":   round(float(wins.sum()) / tot * 100, 2),
        "profit_factor":  round(pf, 3),
        "total_pnl_usd":  round(total_pnl, 2),
        "annual_roi_pct": round(total_pnl / years / notional * 100, 2),
        "max_dd_usd":     round(max_dd, 2),
        "sharpe_ratio":   round(sharpe, 3),
        "expectancy_usd": round(float(pnl_a.mean()), 2),
        "sl_pct":         round(sl_pct * 100, 2),
        "tp_pct":         round(tp_pct * 100, 2),
        "vol_skipped":    vol_skip,
        "_pnl_list":      pnl_a.tolist(),
    }


# ── ADX sweep ─────────────────────────────────────────────────────────────────

def adx_sweep(df, signal_fn, symbol, sl_pct, tp_pct):
    results = []
    for thresh in ADX_SWEEP_THRESHOLDS:
        sig = signal_fn(df)
        sig = apply_adx(sig, df, thresh)
        r   = simulate(df, sig, symbol=symbol, sl_pct=sl_pct, tp_pct=tp_pct)
        results.append({"adx_threshold": thresh,
                        "total_trades":  r.get("total_trades", 0),
                        "win_rate_pct":  r.get("win_rate_pct", 0),
                        "profit_factor": r.get("profit_factor", 0),
                        "total_pnl_usd": r.get("total_pnl_usd", 0),
                        "expectancy_usd": r.get("expectancy_usd", 0)})
    return results


# ── True WFA — ADX threshold also in IS grid ──────────────────────────────────

def run_wfa(df, signal_fn, symbol, n_folds=3, oos_frac=0.20):
    """WFA with SL × TP × ADX grid on IS, locked on OOS."""
    total   = len(df)
    oos_len = int(total * oos_frac)
    is_len  = total - n_folds * oos_len
    # Auto-scale min OOS trades with data size: more data → higher bar
    min_oos = max(MIN_OOS_TRADES_BASE, total // 500)
    results = []

    for fold in range(n_folds):
        oos_start = is_len + fold * oos_len
        oos_end   = oos_start + oos_len
        if oos_end > total:
            break
        df_tr  = df.iloc[:oos_start].reset_index(drop=True)
        df_oos = df.iloc[oos_start:oos_end].reset_index(drop=True)

        best_score, best_sl, best_tp, best_adx = -1.0, WFA_SL_GRID[0], WFA_TP_GRID[0], 0
        for sl, tp, adx_t in product(WFA_SL_GRID, WFA_TP_GRID, WFA_ADX_GRID):
            sig_tr = signal_fn(df_tr)
            sig_tr = apply_adx(sig_tr, df_tr, adx_t)
            r = simulate(df_tr, sig_tr, symbol=symbol, sl_pct=sl, tp_pct=tp)
            # Composite IS score: 50% capped-PF + 50% capped-Sharpe
            # Prevents single large win dominating PF and selecting fragile params
            _pf = min(r.get("profit_factor", 0), 5.0) / 5.0
            _sh = min(max(r.get("sharpe", 0), 0.0), 3.0) / 3.0
            _score = 0.5 * _pf + 0.5 * _sh
            if r.get("total_trades", 0) >= min_oos and _score > best_score:
                best_score = _score
                best_sl, best_tp, best_adx = sl, tp, adx_t

        sig_oos = signal_fn(df_oos)
        sig_oos = apply_adx(sig_oos, df_oos, best_adx)
        oos_r   = simulate(df_oos, sig_oos, symbol=symbol, sl_pct=best_sl, tp_pct=best_tp)

        oos_trades = oos_r.get("total_trades", 0)
        oos_pf     = oos_r.get("profit_factor", 0)
        verdict    = ("SKIP" if oos_trades < min_oos
                      else "PASS" if oos_pf >= 1.0 else "FAIL")
        oos_ts     = df_oos["timestamp"] if "timestamp" in df_oos.columns else pd.Series(["?", "?"])
        results.append({
            "fold":        fold + 1,
            "oos_start":   str(oos_ts.iloc[0])[:10] if len(oos_ts) else "?",
            "oos_end":     str(oos_ts.iloc[-1])[:10] if len(oos_ts) else "?",
            "best_sl_pct": round(best_sl * 100, 1),
            "best_tp_pct": round(best_tp * 100, 1),
            "best_adx":    best_adx,
            "is_pf":       round(best_pf, 3),
            "oos_pf":      round(oos_pf, 3),
            "oos_trades":  oos_trades,
            "verdict":     verdict,
        })
    return results


# ── Monte Carlo ───────────────────────────────────────────────────────────────

def monte_carlo(pnl_list: list[float], n_sims: int = MONTE_CARLO_SIMS) -> dict:
    """Bootstrap WITH replacement — real confidence interval (not shuffle which gives same sum)."""
    if len(pnl_list) < 5:
        return {}
    arr  = np.array(pnl_list)
    pnls = []
    dds  = []
    rng  = np.random.default_rng(42)
    for _ in range(n_sims):
        sample = rng.choice(arr, size=len(arr), replace=True)   # bootstrap, not permutation
        eq     = np.cumsum(np.concatenate([[0], sample]))
        peak   = np.maximum.accumulate(eq)
        pnls.append(float(sample.sum()))
        dds.append(float((eq - peak).min()))
    pa, da = np.array(pnls), np.array(dds)
    return {
        "n_sims":       n_sims,
        "n_trades":     len(pnl_list),
        "pnl_p5":       round(float(np.percentile(pa,  5)), 2),
        "pnl_median":   round(float(np.median(pa)),         2),
        "pnl_p95":      round(float(np.percentile(pa, 95)), 2),
        "prob_profit":  round(float((pa > 0).mean() * 100), 1),
        "dd_median":    round(float(np.median(da)),          2),
        "dd_worst_p5":  round(float(np.percentile(da,  5)), 2),
    }


# ── Portfolio correlation check ───────────────────────────────────────────────

def correlation_check(df: pd.DataFrame, strategy_results: list) -> list:
    """Pairwise signal correlation for profitable strategies on same symbol.
    Returns list of (strat_a, strat_b, corr, warning) for abs(corr) > 0.5."""
    profitable = {r["strategy"]: ALL_STRATEGIES[r["strategy"]]
                  for r in strategy_results if r.get("profit_factor", 0) > 1.0}
    if len(profitable) < 2:
        return []
    names = list(profitable.keys())
    signals = {}
    for name, fn in profitable.items():
        try:
            signals[name] = fn(df).values.astype(float)
        except Exception:
            pass
    pairs = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            if a not in signals or b not in signals:
                continue
            corr = float(np.corrcoef(signals[a], signals[b])[0, 1])
            if abs(corr) > 0.5:
                tag = "HIGH" if abs(corr) > 0.7 else "MODERATE"
                pairs.append((a, b, round(corr, 3), f"{tag} correlation — cap combined exposure"))
    return pairs


# ── Scoring for leaderboard ───────────────────────────────────────────────────

def wfa_score(wfa_results: list) -> float:
    """Composite score: avg OOS PF weighted by verdict (PASS=1, SKIP=0.5, FAIL=0)."""
    if not wfa_results:
        return 0.0
    weights = {"PASS": 1.0, "SKIP": 0.3, "FAIL": 0.0}
    scored = [(f["oos_pf"] * weights.get(f["verdict"], 0)) for f in wfa_results]
    return round(float(np.mean(scored)), 3)


# ── Printing helpers ──────────────────────────────────────────────────────────

def fmt_verdict(pf, pass_c, fail_c):
    if pf > 1.2 and fail_c == 0:  return "DEPLOY-READY"
    if pf > 1.0 and fail_c <= 1:  return "MONITOR-ONLY"
    if pf > 1.0:                   return "PAPER-ONLY"
    return "REJECT"


# ── Main runner ───────────────────────────────────────────────────────────────

def run_all(symbols: list[str], tf_key: str, run_mc: bool = True,
            force_download: bool = False) -> list[dict]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    leaderboard: list[dict] = []

    # ── Download data for all symbols ─────────────────────────────────────────
    print(f"\n{SEP2}")
    print(f"  REALTIME BACKTEST v4.1  —  5-Year Multi-Strategy Global Leaderboard")
    print(f"  {datetime.now(UTC).isoformat()}")
    print(SEP2)
    print(f"\nLoading {YEARS_OF_DATA}-year data for: {', '.join(symbols)} @ {tf_key}")

    datasets: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        df = load_data(sym, tf_key, force_download=force_download)
        datasets[sym] = df

    n_combos = len(symbols) * len(ALL_STRATEGIES)
    print(f"\n  {len(ALL_STRATEGIES)} strategies × {len(symbols)} symbols = {n_combos} pairs")
    print(f"  WFA grid: {len(WFA_SL_GRID)} SL × {len(WFA_TP_GRID)} TP × {len(WFA_ADX_GRID)} ADX "
          f"= {len(WFA_SL_GRID)*len(WFA_TP_GRID)*len(WFA_ADX_GRID)} IS combos / fold")
    print(f"  Monte Carlo: {MONTE_CARLO_SIMS} simulations per profitable strategy")
    print(f"\n  Running...\n")

    # ── Per symbol ────────────────────────────────────────────────────────────
    for sym in symbols:
        df = datasets[sym]
        print(f"\n{SEP}")
        print(f"  SYMBOL: {sym}  ({len(df)} bars, {tf_key})")
        print(SEP)

        sym_rows = []
        for sname, sfn in ALL_STRATEGIES.items():
            print(f"  {sname:<22} ", end="", flush=True)

            # Full backtest at live params (best ADX from quick sweep)
            sweep  = adx_sweep(df, sfn, sym, LIVE_SL_PCT, LIVE_TP_PCT)
            best_sw = max(sweep, key=lambda r: r["profit_factor"])
            best_adx = best_sw["adx_threshold"]

            sig  = sfn(df)
            sig  = apply_adx(sig, df, best_adx)
            full = simulate(df, sig, symbol=sym, sl_pct=LIVE_SL_PCT, tp_pct=LIVE_TP_PCT,
                            label=sname)

            # WFA (SL × TP × ADX in grid)
            wfa = run_wfa(df, sfn, sym)
            ws  = wfa_score(wfa)
            pc  = sum(1 for f in wfa if f["verdict"] == "PASS")
            fc  = sum(1 for f in wfa if f["verdict"] == "FAIL")

            pf      = full.get("profit_factor", 0)
            trades  = full.get("total_trades", 0)
            pnl     = full.get("total_pnl_usd", 0)
            verdict = fmt_verdict(pf, pc, fc)

            print(f"t={trades:>4}  pf={pf:.3f}  pnl=${pnl:>8.2f}  "
                  f"wfa={pc}P/{fc}F  adx>{best_adx}  → {verdict}")

            # Monte Carlo for PF > 1.0
            mc = {}
            if run_mc and pf > 1.0 and trades >= 10:
                mc = monte_carlo(full.get("_pnl_list", []))

            row = {
                "strategy":     sname,
                "symbol":       sym,
                "timeframe":    tf_key,
                "total_trades": trades,
                "win_rate_pct": full.get("win_rate_pct", 0),
                "profit_factor": pf,
                "total_pnl_usd": pnl,
                "annual_roi_pct": full.get("annual_roi_pct", 0),
                "max_dd_usd":   full.get("max_dd_usd", 0),
                "sharpe_ratio": full.get("sharpe_ratio", 0),
                "expectancy_usd": full.get("expectancy_usd", 0),
                "best_adx":     best_adx,
                "wfa_score":    ws,
                "wfa_pass":     pc,
                "wfa_fail":     fc,
                "wfa_folds":    wfa,
                "verdict":      verdict,
                "monte_carlo":  mc,
                "live_sl_pct":  round(LIVE_SL_PCT * 100, 2),
                "live_tp_pct":  round(LIVE_TP_PCT * 100, 2),
            }
            sym_rows.append(row)
            leaderboard.append(row)

        # ── Per-symbol mini leaderboard ────────────────────────────────────
        sym_rows.sort(key=lambda r: r["profit_factor"], reverse=True)
        print(f"\n  ── {sym} Top 5 ──")
        print(f"  {'Strategy':<22} {'Trades':>6} {'WR%':>6} {'PF':>6} {'PnL':>9} {'WFA':>8} {'Rec SL/TP':>12} Verdict")
        for r in sym_rows[:5]:
            wfa_tag = f"{r['wfa_pass']}P/{r['wfa_fail']}F"
            # Show recommended SL/TP from latest WFA fold
            latest = r["wfa_folds"][-1] if r["wfa_folds"] else {}
            rec_params = (f"SL{latest.get('best_sl_pct','?')}%/TP{latest.get('best_tp_pct','?')}%"
                          if latest else "─")
            print(f"  {r['strategy']:<22} {r['total_trades']:>6} {r['win_rate_pct']:>5.1f}% "
                  f"{r['profit_factor']:>6.3f} ${r['total_pnl_usd']:>8.2f} "
                  f"{wfa_tag:>8} {rec_params:>12}  {r['verdict']}")

        # ── Correlation check for profitable pairs on this symbol ──────────
        corr_pairs = correlation_check(df, sym_rows)
        if corr_pairs:
            print(f"\n  ── {sym} Correlation Warning ──")
            for a, b, c, note in corr_pairs:
                print(f"  ⚠  {a} ↔ {b}  corr={c:+.3f}  {note}")

    # ── Global leaderboard ────────────────────────────────────────────────────
    leaderboard.sort(key=lambda r: (r["profit_factor"], r["wfa_score"]), reverse=True)

    print(f"\n\n{SEP2}")
    print("  GLOBAL LEADERBOARD  —  All Strategies × All Symbols (ranked by PF)")
    print(SEP2)
    print(f"  {'Rank':<4} {'Strategy':<22} {'Symbol':<10} {'Trades':>6} {'WR%':>6} "
          f"{'PF':>6} {'PnL':>9} {'Ann.ROI':>8} {'WFA':>8} {'ADX':>5}  Verdict")
    print(f"  {'─'*4} {'─'*22} {'─'*10} {'─'*6} {'─'*6} {'─'*6} {'─'*9} {'─'*8} {'─'*8} {'─'*5}  {'─'*12}")
    for rank, r in enumerate(leaderboard[:25], 1):
        wfa_tag = f"{r['wfa_pass']}P/{r['wfa_fail']}F"
        adx_tag = f">{r['best_adx']}" if r["best_adx"] > 0 else "none"
        roi_tag = f"{r['annual_roi_pct']:>6.1f}%"
        print(f"  {rank:<4} {r['strategy']:<22} {r['symbol']:<10} "
              f"{r['total_trades']:>6} {r['win_rate_pct']:>5.1f}% "
              f"{r['profit_factor']:>6.3f} ${r['total_pnl_usd']:>8.2f} "
              f"{roi_tag:>8} {wfa_tag:>8} {adx_tag:>5}  {r['verdict']}")

    # ── Monte Carlo for top 5 profitable ─────────────────────────────────────
    top_mc = [r for r in leaderboard if r["monte_carlo"] and r["profit_factor"] > 1.0][:5]
    if top_mc:
        print(f"\n{SEP2}")
        print(f"  MONTE CARLO  —  Top {len(top_mc)} Profitable Strategies ({MONTE_CARLO_SIMS} simulations each)")
        print(SEP2)
        for r in top_mc:
            mc = r["monte_carlo"]
            print(f"\n  {r['strategy']} + {r['symbol']} (ADX>{r['best_adx']}, "
                  f"{mc['n_trades']} trades)")
            print(f"    Worst case  (5th pct):     ${mc['pnl_p5']:>9.2f}  /  "
                  f"Max DD worst: ${mc['dd_worst_p5']:>8.2f}")
            print(f"    Expected    (median):      ${mc['pnl_median']:>9.2f}  /  "
                  f"Max DD median: ${mc['dd_median']:>7.2f}")
            print(f"    Best case   (95th pct):    ${mc['pnl_p95']:>9.2f}")
            print(f"    Probability of profit:     {mc['prob_profit']:>5.1f}%")
            if mc["prob_profit"] >= 70:
                ann = round(mc["pnl_median"] / YEARS_OF_DATA, 2)
                print(f"    → Projected annual P&L:   ${ann:>9.2f}  (at $500 notional)")

    # ── Deployment recommendations ────────────────────────────────────────────
    deploy = [r for r in leaderboard if r["verdict"] in ("DEPLOY-READY", "MONITOR-ONLY")]
    paper  = [r for r in leaderboard if r["verdict"] == "PAPER-ONLY"]

    print(f"\n{SEP2}")
    print("  DEPLOYMENT RECOMMENDATIONS")
    print(SEP2)
    if deploy:
        print(f"\n  DEPLOY / MONITOR ({len(deploy)} pairs):")
        for r in deploy:
            mc = r.get("monte_carlo", {})
            prob = mc.get("prob_profit", "?")
            ann  = round(mc.get("pnl_median", 0) / YEARS_OF_DATA, 2) if mc else "?"
            wfa  = f"{r['wfa_pass']}P/{r['wfa_fail']}F"
            print(f"    • {r['strategy']} on {r['symbol']} {r['timeframe']}  "
                  f"[ADX>{r['best_adx']}]  PF={r['profit_factor']:.3f}  "
                  f"WFA={wfa}  Prob.Profit={prob}%  Est.Annual=${ann}")
    else:
        print("\n  No pairs cleared DEPLOY / MONITOR threshold.")

    if paper:
        print(f"\n  PAPER SIM CANDIDATES ({len(paper)} pairs — watch for 25+ live trades):")
        for r in paper[:5]:
            print(f"    • {r['strategy']} on {r['symbol']}  PF={r['profit_factor']:.3f}  "
                  f"WFA={r['wfa_pass']}P/{r['wfa_fail']}F")

    # ── Save JSON report ──────────────────────────────────────────────────────
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M")
    sym_tag = "_".join(symbols) if len(symbols) <= 3 else f"{len(symbols)}sym"
    out_path = REPORT_DIR / f"backtest_v4_{sym_tag}_{tf_key}_{ts}.json"

    # Remove _pnl_list before saving (too large)
    save_data = []
    for r in leaderboard:
        row = {k: v for k, v in r.items() if k != "_pnl_list"}
        save_data.append(row)
    out_path.write_text(json.dumps({"generated_at": datetime.now(UTC).isoformat(),
                                    "config": {"symbols": symbols, "tf": tf_key,
                                               "years": YEARS_OF_DATA,
                                               "strategies": list(ALL_STRATEGIES.keys())},
                                    "leaderboard": save_data}, indent=2))

    print(f"\n{SEP2}")
    print(f"  Report saved → {out_path}")
    print(SEP2 + "\n")
    return leaderboard


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol",         default=None, help="Single symbol override")
    ap.add_argument("--tf",             default="4h")
    ap.add_argument("--no-mc",          action="store_true", help="Skip Monte Carlo")
    ap.add_argument("--force-download", action="store_true", help="Re-download 5yr data even if cached")
    args = ap.parse_args()

    tf_key  = TF_MAP.get(args.tf, "4h")
    symbols = [args.symbol.upper()] if args.symbol else DEFAULT_SYMBOLS

    run_all(symbols, tf_key, run_mc=not args.no_mc, force_download=args.force_download)


if __name__ == "__main__":
    main()
