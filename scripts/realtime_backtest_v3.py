#!/usr/bin/env python3
"""
realtime_backtest_v3.py  —  ADX Regime Filter + Path to Profitability
======================================================================

Adds on top of v2:
  - ADX(14) regime filter: only trade when market is trending (ADX > threshold)
  - ADX threshold sweep: 0 (no filter), 15, 20, 25, 30 — find profitability breakeven
  - 1D timeframe support with Binance data download fallback
  - Multi-symbol run (ETHUSDT + BTCUSDT) for side-by-side comparison
  - Paper sim winners pull (strategies with PF > 1.3 in paper sim)

Run:
    python scripts/realtime_backtest_v3.py                  # ETH 4h ADX sweep
    python scripts/realtime_backtest_v3.py --symbol BTCUSDT
    python scripts/realtime_backtest_v3.py --symbol ETHUSDT --tf 1d
    python scripts/realtime_backtest_v3.py --both           # ETH + BTC side-by-side
    python scripts/realtime_backtest_v3.py --paper-winners  # pull paper sim leaders
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

UTC = timezone.utc

# ── Live params from env ───────────────────────────────────────────────────────
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

LIVE_SL_PCT        = float(_env("STOP_LOSS_PCT",    "2.0")) / 100.0
LIVE_TP_PCT        = float(_env("TAKE_PROFIT_PCT",  "4.0")) / 100.0   # updated default
LIVE_LEVERAGE      = float(_env("LEVERAGE", "2"))
FIXED_NOTIONAL_USD = 500.0
COMMISSION_SIDE    = 0.0006
MAX_POSITION_USD   = 50_000.0
MIN_OOS_TRADES     = 15
LATENCY_ATR_FRACTION = 0.03

WFA_SL_GRID = [0.010, 0.015, 0.020, 0.025, 0.030]
WFA_TP_GRID = [0.030, 0.040, 0.050, 0.060, 0.080, 0.100]

ADX_THRESHOLDS = [0, 15, 20, 25, 30]   # 0 = no filter

SLIPPAGE_BASE: dict[str, float] = {
    "ETHUSDT":  0.0008,
    "BTCUSDT":  0.0006,
    "SOLUSDT":  0.0010,
    "XRPUSDT":  0.0012,
    "LINKUSDT": 0.0015,
    "DEFAULT":  0.0018,
}

TF_MAP = {
    "4h": "4h", "4H": "4h",
    "1h": "1h", "1H": "1h",
    "15m": "15m", "15": "15m",
    "1d": "1d", "1D": "1d", "daily": "1d",
}
BINANCE_INTERVAL = {"4h": "4h", "1h": "1h", "15m": "15m", "1d": "1d"}

DATA_DIR   = PROJECT_ROOT / "storage" / "backtest_data"
REPORT_DIR = PROJECT_ROOT / "storage" / "reports" / "realtime_backtest"

SEP  = "─" * 72
SEP2 = "═" * 72


# ─── Data loading ─────────────────────────────────────────────────────────────

def load_data(symbol: str, tf_key: str) -> pd.DataFrame:
    data_file = DATA_DIR / f"{symbol}_3y_{tf_key}.csv"
    if data_file.exists():
        df = pd.read_csv(data_file)
        df.columns = [c.lower() for c in df.columns]
        print(f"Loaded {len(df)} bars  |  {df['timestamp'].iloc[0]} → {df['timestamp'].iloc[-1]}")
        return df

    # Download from Binance public API (no key needed for historical OHLCV)
    print(f"  {data_file.name} not found — downloading from Binance...")
    try:
        import urllib.request, time
        interval = BINANCE_INTERVAL.get(tf_key, "4h")
        limit    = 1000
        end_ms   = int(time.time() * 1000)
        rows     = []
        while True:
            url = (f"https://api.binance.com/api/v3/klines"
                   f"?symbol={symbol}&interval={interval}&limit={limit}&endTime={end_ms}")
            with urllib.request.urlopen(url, timeout=15) as r:
                batch = json.loads(r.read())
            if not batch:
                break
            rows = batch + rows
            end_ms = batch[0][0] - 1
            if len(batch) < limit:
                break
            # stop at ~3 years
            if len(rows) >= 6000:
                break

        df = pd.DataFrame(rows, columns=[
            "timestamp","open","high","low","close","volume",
            "close_time","qav","num_trades","tbbav","tbqav","ignore"])
        df = df[["timestamp","open","high","low","close","volume"]].copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        for c in ["open","high","low","close","volume"]:
            df[c] = df[c].astype(float)
        df = df.sort_values("timestamp").reset_index(drop=True)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        df.to_csv(data_file, index=False)
        print(f"  Downloaded {len(df)} bars → saved to {data_file.name}")
        return df
    except Exception as e:
        print(f"ERROR: Cannot load or download {symbol} {tf_key}: {e}")
        sys.exit(1)


# ─── Indicator helpers ────────────────────────────────────────────────────────

def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()

def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(n).mean()
    loss  = (-delta.clip(upper=0)).rolling(n).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100.0 - 100.0 / (1.0 + rs)

def _cci(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 20) -> pd.Series:
    tp = (high + low + close) / 3.0
    ma = tp.rolling(n).mean()
    md = tp.rolling(n).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    return (tp - ma) / (0.015 * md)

def _atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=n, adjust=False).mean()

def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    ADX(period) — Wilder smoothing.
    Returns a Series indexed like df.
    ADX > 25 = trending market; ADX < 20 = choppy/ranging.
    """
    high  = df["high"].astype(float)
    low   = df["low"].astype(float)
    close = df["close"].astype(float)

    prev_high  = high.shift(1)
    prev_low   = low.shift(1)
    prev_close = close.shift(1)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)

    up_move   = high - prev_high
    down_move = prev_low - low

    plus_dm  = np.where((up_move > down_move) & (up_move   > 0), up_move,   0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    alpha = 1.0 / period
    atr_s     = tr.ewm(alpha=alpha, adjust=False).mean()
    plus_di   = 100 * pd.Series(plus_dm,  index=df.index).ewm(alpha=alpha, adjust=False).mean() / atr_s.replace(0, np.nan)
    minus_di  = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=alpha, adjust=False).mean() / atr_s.replace(0, np.nan)

    denom = (plus_di + minus_di).replace(0, np.nan)
    dx    = 100 * (plus_di - minus_di).abs() / denom
    adx   = dx.ewm(alpha=alpha, adjust=False).mean()
    return adx.fillna(0).rename("adx")


# ─── Step 3: Volatility-adjusted slippage ────────────────────────────────────

def _vol_slippage(base_slip, current_atr, avg_atr, is_breakout):
    if avg_atr <= 0:
        return base_slip
    ratio = current_atr / avg_atr
    vol_mult     = 2.0 if ratio > 1.5 else 1.5 if ratio > 1.2 else 1.0
    breakout_mult = 1.3 if is_breakout else 1.0
    return base_slip * vol_mult * breakout_mult

def _latency_slip(atr_val, entry_price):
    if entry_price <= 0:
        return 0.0
    return (LATENCY_ATR_FRACTION * atr_val) / entry_price

def _vol_guard(notional, bar_volume_usd):
    if bar_volume_usd <= 0:
        return True
    daily_vol_estimate = bar_volume_usd * 6
    return notional <= daily_vol_estimate * 0.01


# ─── Signal generators ────────────────────────────────────────────────────────

def signals_cci_trend(df: pd.DataFrame) -> pd.Series:
    cci    = _cci(df["high"], df["low"], df["close"], 20)
    ema200 = _ema(df["close"], 200)
    cci_p  = cci.shift(1)
    long_x  = (cci > 0) & (cci_p <= 0) & (df["close"] > ema200)
    short_x = (cci < 0) & (cci_p >= 0) & (df["close"] < ema200)
    sig = np.zeros(len(df), dtype=int)
    sig = np.where(long_x,  1,  sig)
    sig = np.where(short_x, -1, sig)
    return pd.Series(sig, index=df.index, name="sig")

def signals_donchian_trend(df: pd.DataFrame) -> pd.Series:
    dc_h = df["close"].rolling(20).max().shift(1)
    dc_l = df["close"].rolling(20).min().shift(1)
    rsi  = _rsi(df["close"], 14)
    long_x  = (df["close"] > dc_h) & (df["close"].shift(1) <= dc_h.shift(1)) & (rsi < 70)
    short_x = (df["close"] < dc_l) & (df["close"].shift(1) >= dc_l.shift(1)) & (rsi > 30)
    sig = np.zeros(len(df), dtype=int)
    sig = np.where(long_x,  1,  sig)
    sig = np.where(short_x, -1, sig)
    return pd.Series(sig, index=df.index, name="sig")

def signals_cci_pure(df: pd.DataFrame) -> pd.Series:
    cci   = _cci(df["high"], df["low"], df["close"], 20)
    cci_p = cci.shift(1)
    sig = np.zeros(len(df), dtype=int)
    sig = np.where((cci > 0) & (cci_p <= 0),  1,  sig)
    sig = np.where((cci < 0) & (cci_p >= 0), -1,  sig)
    return pd.Series(sig, index=df.index, name="sig")

def signals_donchian_pure(df: pd.DataFrame) -> pd.Series:
    dc_h = df["close"].rolling(20).max().shift(1)
    dc_l = df["close"].rolling(20).min().shift(1)
    long_x  = (df["close"] > dc_h) & (df["close"].shift(1) <= dc_h.shift(1))
    short_x = (df["close"] < dc_l) & (df["close"].shift(1) >= dc_l.shift(1))
    sig = np.zeros(len(df), dtype=int)
    sig = np.where(long_x,  1,  sig)
    sig = np.where(short_x, -1, sig)
    return pd.Series(sig, index=df.index, name="sig")

def make_adx_filtered(base_fn, adx_threshold: float):
    """Wrap any signal function with an ADX regime filter."""
    def _fn(df: pd.DataFrame) -> pd.Series:
        base = base_fn(df)
        if adx_threshold <= 0:
            return base
        adx = _adx(df, 14)
        # Only enter when ADX indicates trending market
        trend_ok = adx > adx_threshold
        result = base.copy()
        result[~trend_ok] = 0
        return result
    _fn.__name__ = f"{getattr(base_fn, '__name__', 'fn')}_adx{int(adx_threshold)}"
    return _fn

BASE_STRATEGIES = {
    "CCI Trend (filtered)":      signals_cci_trend,
    "Donchian Trend (filtered)": signals_donchian_trend,
}


# ─── Core simulation ──────────────────────────────────────────────────────────

def simulate(
    df: pd.DataFrame,
    sig: pd.Series,
    symbol: str      = "ETHUSDT",
    sl_pct: float    = LIVE_SL_PCT,
    tp_pct: float    = LIVE_TP_PCT,
    leverage: float  = LIVE_LEVERAGE,
    notional: float  = FIXED_NOTIONAL_USD,
    min_gap_bars: int = 2,
    label: str       = "",
) -> dict:
    base_slip  = SLIPPAGE_BASE.get(symbol.upper(), SLIPPAGE_BASE["DEFAULT"])
    comm       = COMMISSION_SIDE

    close_arr = df["close"].values.astype(float)
    open_arr  = df["open"].values.astype(float)
    high_arr  = df["high"].values.astype(float)
    low_arr   = df["low"].values.astype(float)
    sig_arr   = sig.values.astype(int)
    vol_arr   = df["volume"].values.astype(float) if "volume" in df.columns else None
    n         = len(df)

    atr_series = _atr(df["high"], df["low"], df["close"], 14).values.astype(float)
    avg_atr    = float(pd.Series(atr_series).rolling(50).mean().ffill().bfill().values[-1])

    dates = None
    if "timestamp" in df.columns:
        try:
            dates = pd.to_datetime(df["timestamp"]).dt.date.values
        except Exception:
            pass

    position      = 0
    entry_price   = 0.0
    entry_bar     = -1
    last_exit_bar = -min_gap_bars - 1
    trades        = []
    daily_pnl     = {}
    vol_skipped   = 0

    for i in range(1, n - 1):
        hi    = high_arr[i]
        lo    = low_arr[i]
        sig_i = sig_arr[i]
        atr_i = atr_series[i] if i < len(atr_series) else avg_atr
        local_avg_atr = float(np.mean(atr_series[max(0, i - 50):i + 1])) or avg_atr

        if position != 0:
            exit_px = None
            if position == 1:
                sl_lvl = entry_price * (1.0 - sl_pct)
                tp_lvl = entry_price * (1.0 + tp_pct)
                if lo <= sl_lvl:
                    exit_px = sl_lvl
                elif hi >= tp_lvl:
                    exit_px = tp_lvl
                elif sig_i == -1:
                    exit_px = open_arr[i + 1]
            elif position == -1:
                sl_lvl = entry_price * (1.0 + sl_pct)
                tp_lvl = entry_price * (1.0 - tp_pct)
                if hi >= sl_lvl:
                    exit_px = sl_lvl
                elif lo <= tp_lvl:
                    exit_px = tp_lvl
                elif sig_i == 1:
                    exit_px = open_arr[i + 1]

            if exit_px is not None:
                ret  = ((exit_px - entry_price) / entry_price if position == 1
                        else (entry_price - exit_px) / entry_price)
                ret *= leverage
                cost = (comm * 2) * leverage
                pnl  = notional * (ret - cost)
                trades.append({
                    "entry_bar": entry_bar, "exit_bar": i,
                    "entry_price": entry_price, "exit_price": exit_px,
                    "side": "long" if position == 1 else "short",
                    "ret_pct": ret, "pnl_usd": pnl,
                })
                if dates is not None:
                    d = str(dates[i])
                    daily_pnl[d] = daily_pnl.get(d, 0.0) + pnl
                position = 0
                last_exit_bar = i

        if position == 0 and sig_i != 0 and (i - last_exit_bar) > min_gap_bars:
            eff_notional = min(notional, MAX_POSITION_USD)
            if vol_arr is not None:
                bar_vol_usd = vol_arr[i] * close_arr[i]
                if not _vol_guard(eff_notional, bar_vol_usd):
                    vol_skipped += 1
                    continue

            entry_slip = _vol_slippage(base_slip, atr_i, local_avg_atr, True)
            lat_cost   = _latency_slip(atr_i, open_arr[i + 1])
            if sig_i == 1:
                entry_price = open_arr[i + 1] * (1.0 + lat_cost)
            else:
                entry_price = open_arr[i + 1] * (1.0 - lat_cost)

            position  = sig_i
            entry_bar = i

    if len(trades) < 2:
        return {"total_trades": 0, "error": "insufficient_trades",
                "vol_skipped": vol_skipped}

    pnl_arr  = np.array([t["pnl_usd"] for t in trades])
    wins     = pnl_arr > 0
    losses   = pnl_arr < 0
    total_t  = len(trades)
    win_rate = float(wins.sum()) / total_t * 100.0
    gp       = float(pnl_arr[wins].sum())  if wins.any()   else 0.0
    gl       = float(abs(pnl_arr[losses].sum())) if losses.any() else 1e-9
    pf       = gp / gl
    total_pnl = float(pnl_arr.sum())
    expect   = float(pnl_arr.mean())

    equity = np.cumsum(np.concatenate([[0], pnl_arr]))
    peak   = np.maximum.accumulate(equity)
    max_dd = float((equity - peak).min())

    sharpe = 0.0
    if daily_pnl and len(daily_pnl) >= 10:
        dp  = pd.Series(daily_pnl)
        std = dp.std()
        if std > 0:
            sharpe = float(dp.mean() / std * (252 ** 0.5))

    return {
        "label":          label,
        "total_trades":   total_t,
        "vol_skipped":    vol_skipped,
        "win_rate_pct":   round(win_rate,  2),
        "profit_factor":  round(pf,        3),
        "total_pnl_usd":  round(total_pnl, 2),
        "max_dd_usd":     round(max_dd,    2),
        "sharpe_ratio":   round(sharpe,    3),
        "expectancy_usd": round(expect,    2),
        "sl_pct":         round(sl_pct * 100, 2),
        "tp_pct":         round(tp_pct * 100, 2),
    }


# ─── WFA with IS optimisation ─────────────────────────────────────────────────

def run_wfa_optimized(df, signal_fn, symbol, n_folds=3, oos_frac=0.20):
    results = []
    total   = len(df)
    oos_len = int(total * oos_frac)
    is_len  = total - n_folds * oos_len

    for fold in range(n_folds):
        oos_start = is_len + fold * oos_len
        oos_end   = oos_start + oos_len
        if oos_end > total:
            break
        df_train = df.iloc[:oos_start].reset_index(drop=True)
        df_oos   = df.iloc[oos_start:oos_end].reset_index(drop=True)

        best_pf, best_sl, best_tp = -1, WFA_SL_GRID[0], WFA_TP_GRID[0]
        for sl, tp in product(WFA_SL_GRID, WFA_TP_GRID):
            sig_train = signal_fn(df_train)
            r = simulate(df_train, sig_train, symbol=symbol, sl_pct=sl, tp_pct=tp)
            if r.get("total_trades", 0) >= MIN_OOS_TRADES and r.get("profit_factor", 0) > best_pf:
                best_pf = r["profit_factor"]
                best_sl, best_tp = sl, tp

        sig_oos = signal_fn(df_oos)
        oos_r   = simulate(df_oos, sig_oos, symbol=symbol, sl_pct=best_sl, tp_pct=best_tp)

        oos_trades = oos_r.get("total_trades", 0)
        oos_pf     = oos_r.get("profit_factor", 0)

        if oos_trades < MIN_OOS_TRADES:
            verdict = "SKIP"
        elif oos_pf >= 1.0:
            verdict = "PASS"
        else:
            verdict = "FAIL"

        oos_ts = df_oos["timestamp"] if "timestamp" in df_oos.columns else pd.Series(["?", "?"])
        results.append({
            "fold":         fold + 1,
            "oos_start":    str(oos_ts.iloc[0])[:10]  if len(oos_ts) else "?",
            "oos_end":      str(oos_ts.iloc[-1])[:10] if len(oos_ts) else "?",
            "best_sl_pct":  round(best_sl * 100, 1),
            "best_tp_pct":  round(best_tp * 100, 1),
            "is_pf":        round(best_pf, 3),
            "oos_pf":       round(oos_pf,  3),
            "oos_trades":   oos_trades,
            "verdict":      verdict,
        })

    return results


# ─── ADX sweep ────────────────────────────────────────────────────────────────

def adx_sweep(df, signal_fn, symbol, sl_pct, tp_pct, thresholds=None):
    """Test multiple ADX thresholds on the same dataset."""
    if thresholds is None:
        thresholds = ADX_THRESHOLDS
    results = []
    for thresh in thresholds:
        fn  = make_adx_filtered(signal_fn, thresh)
        sig = fn(df)
        r   = simulate(df, sig, symbol=symbol, sl_pct=sl_pct, tp_pct=tp_pct)
        results.append({
            "adx_threshold":  thresh,
            "total_trades":   r.get("total_trades", 0),
            "win_rate_pct":   r.get("win_rate_pct", 0),
            "profit_factor":  r.get("profit_factor", 0),
            "total_pnl_usd":  r.get("total_pnl_usd", 0),
            "expectancy_usd": r.get("expectancy_usd", 0),
            "sharpe_ratio":   r.get("sharpe_ratio", 0),
        })
    return results


# ─── Paper sim winners ────────────────────────────────────────────────────────

def pull_paper_sim_winners(min_pf: float = 1.3, min_trades: int = 20):
    """Read paper_sim_results.json and return strategies beating the thresholds."""
    candidates = [
        PROJECT_ROOT / "storage" / "paper_sim_results.json",
        PROJECT_ROOT / "tradingview_webhook_bot" / "storage" / "paper_sim_results.json",
    ]
    for p in candidates:
        if p.exists():
            data = json.loads(p.read_text())
            break
    else:
        return []

    strategies = data if isinstance(data, list) else data.get("strategies", [])
    winners = []
    for s in strategies:
        pf = s.get("profit_factor", s.get("pf", 0)) or 0
        trades = s.get("total_trades", s.get("trades", 0)) or 0
        if pf >= min_pf and trades >= min_trades:
            winners.append(s)

    winners.sort(key=lambda x: x.get("profit_factor", x.get("pf", 0)), reverse=True)
    return winners


# ─── Report printing ──────────────────────────────────────────────────────────

def print_adx_sweep_table(sweep_results, strategy_name):
    print(f"\n  ── {strategy_name} ──")
    print(f"  {'ADX≥':>6}  {'Trades':>7}  {'WR%':>7}  {'PF':>7}  {'PnL':>10}  {'Expect':>8}  Note")
    print(f"  {'─'*6}  {'─'*7}  {'─'*7}  {'─'*7}  {'─'*10}  {'─'*8}  {'─'*12}")
    profitable_found = False
    for r in sweep_results:
        thresh = r["adx_threshold"]
        label  = "no filter" if thresh == 0 else f"ADX>{thresh}"
        pf     = r["profit_factor"]
        note   = ""
        if pf >= 1.2 and not profitable_found:
            note = " ← PROFITABLE"
            profitable_found = True
        elif pf >= 1.0 and not profitable_found:
            note = " ← BREAKEVEN"
            profitable_found = True
        pf_str = f"{pf:.3f}"
        print(f"  {label:>6}  {r['total_trades']:>7}  {r['win_rate_pct']:>7.1f}"
              f"  {pf_str:>7}  ${r['total_pnl_usd']:>9.2f}  ${r['expectancy_usd']:>7.2f}{note}")


def print_wfa_table(wfa_results, strategy_name, adx_threshold):
    label = f"no ADX filter" if adx_threshold == 0 else f"ADX>{adx_threshold}"
    print(f"\n  WFA — {strategy_name} ({label})")
    print(f"  {'Fold':>4}  {'OOS Period':>23}  {'SL':>5}  {'TP':>5}  {'IS PF':>7}  {'OOS PF':>7}  {'OOS Trades':>10}  Verdict")
    print(f"  {'─'*4}  {'─'*23}  {'─'*5}  {'─'*5}  {'─'*7}  {'─'*7}  {'─'*10}  {'─'*10}")
    pass_c = fail_c = skip_c = 0
    for f in wfa_results:
        v = f["verdict"]
        if v == "PASS":   pass_c += 1
        elif v == "FAIL": fail_c += 1
        else:             skip_c += 1
        period = f"{f['oos_start']} → {f['oos_end']}"
        print(f"  {f['fold']:>4}  {period:>23}  {f['best_sl_pct']:>4.1f}%  {f['best_tp_pct']:>4.1f}%"
              f"  {f['is_pf']:>7.3f}  {f['oos_pf']:>7.3f}  {f['oos_trades']:>10}  {v}")
    summary = f"DEPLOY-READY" if pass_c == 3 else f"PARTIAL EDGE" if pass_c >= 2 else f"OVERFITTING RISK"
    print(f"  WFA Verdict: {summary}  ({pass_c} PASS / {fail_c} FAIL / {skip_c} SKIP)")
    return pass_c, fail_c


def run_symbol(symbol: str, tf_key: str, sl_pct: float, tp_pct: float):
    df = load_data(symbol, tf_key)

    print(f"\n{SEP2}")
    print(f"  REALTIME BACKTEST v3  —  ADX Regime Filter")
    print(f"  {datetime.now(UTC).isoformat()}")
    print(SEP2)
    print(f"  Symbol: {symbol}  Timeframe: {tf_key}")
    print(f"  Live SL: {sl_pct*100:.1f}%  |  Live TP: {tp_pct*100:.1f}%  "
          f"|  Notional: ${FIXED_NOTIONAL_USD:.0f}  |  Leverage: {LIVE_LEVERAGE:.0f}x")
    print(f"  ADX thresholds tested: {ADX_THRESHOLDS}  (0 = no filter)")

    print(f"\n{SEP}")
    print("  ADX REGIME FILTER SWEEP")
    print(f"  — Find the threshold where each strategy turns profitable —")
    print(SEP)

    sweep_output = {}
    best_adx_per_strategy = {}

    for sname, sfn in BASE_STRATEGIES.items():
        sweep = adx_sweep(df, sfn, symbol, sl_pct, tp_pct)
        sweep_output[sname] = sweep
        print_adx_sweep_table(sweep, sname)
        # find best threshold (highest PF)
        best = max(sweep, key=lambda r: r["profit_factor"])
        best_adx_per_strategy[sname] = best["adx_threshold"]

    # ── WFA on best ADX threshold per strategy ────────────────────────────────
    print(f"\n{SEP}")
    print("  WALK-FORWARD ON BEST ADX THRESHOLD")
    print(SEP)

    wfa_output = {}
    for sname, sfn in BASE_STRATEGIES.items():
        best_thresh = best_adx_per_strategy[sname]
        fn = make_adx_filtered(sfn, best_thresh)
        print(f"\n  Running WFA for {sname} (ADX>{best_thresh})...")
        wfa = run_wfa_optimized(df, fn, symbol)
        wfa_output[sname] = {"adx_threshold": best_thresh, "folds": wfa}
        print_wfa_table(wfa, sname, best_thresh)

    # ── TP sweep at best ADX threshold ───────────────────────────────────────
    print(f"\n{SEP}")
    print("  TP SWEEP AT BEST ADX THRESHOLD (SL=2% fixed)")
    print(SEP)

    tp_grid = [0.025, 0.030, 0.040, 0.050, 0.060, 0.080, 0.100, 0.120]
    for sname, sfn in BASE_STRATEGIES.items():
        best_thresh = best_adx_per_strategy[sname]
        fn = make_adx_filtered(sfn, best_thresh)
        print(f"\n  {sname}  (ADX>{best_thresh})")
        print(f"  {'TP%':>6}  {'Trades':>7}  {'WR%':>7}  {'PF':>7}  {'PnL':>10}  Note")
        print(f"  {'─'*6}  {'─'*7}  {'─'*7}  {'─'*7}  {'─'*10}  {'─'*6}")
        best_tp_r = None
        rows = []
        for tp in tp_grid:
            sig = fn(df)
            r = simulate(df, sig, symbol=symbol, sl_pct=sl_pct, tp_pct=tp)
            rows.append((tp, r))
        best_tp_r = max(rows, key=lambda x: x[1].get("profit_factor", 0))
        for tp, r in rows:
            note = " ← OPTIMAL" if tp == best_tp_r[0] else ""
            if abs(tp - tp_pct) < 0.001:
                note += " ← LIVE"
            pf = r.get("profit_factor", 0)
            print(f"  {tp*100:>5.1f}%  {r.get('total_trades',0):>7}  "
                  f"{r.get('win_rate_pct',0):>7.1f}  {pf:>7.3f}  "
                  f"${r.get('total_pnl_usd',0):>9.2f}{note}")

    # ── Final verdict ─────────────────────────────────────────────────────────
    print(f"\n{SEP2}")
    print("  FINAL VERDICT")
    print(SEP2)
    for sname, sfn in BASE_STRATEGIES.items():
        best_thresh = best_adx_per_strategy[sname]
        fn = make_adx_filtered(sfn, best_thresh)
        sig = fn(df)
        r = simulate(df, sig, symbol=symbol, sl_pct=sl_pct, tp_pct=tp_pct)
        pf = r.get("profit_factor", 0)
        wfa = wfa_output[sname]["folds"]
        pass_c = sum(1 for f in wfa if f["verdict"] == "PASS")
        fail_c = sum(1 for f in wfa if f["verdict"] == "FAIL")
        v = ("DEPLOY-READY" if pf > 1.2 and fail_c == 0
             else "MONITOR-ONLY" if pf > 1.0 and fail_c <= 1
             else "PAPER-ONLY"   if pf > 1.0
             else "REJECT")
        adx_note = f"(ADX>{best_thresh})" if best_thresh > 0 else "(no filter)"
        print(f"  {sname:<35} {adx_note:>12}  PF={pf:.3f}  WFA={pass_c}P/{fail_c}F  → {v}")
    print(SEP2 + "\n")

    return {"symbol": symbol, "tf": tf_key}


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol",        default="ETHUSDT")
    ap.add_argument("--tf",            default="4h")
    ap.add_argument("--sl",            type=float, default=None)
    ap.add_argument("--tp",            type=float, default=None)
    ap.add_argument("--both",          action="store_true", help="Run ETH + BTC side-by-side")
    ap.add_argument("--paper-winners", action="store_true", help="Show paper sim leaders")
    args = ap.parse_args()

    sl_pct = (args.sl / 100.0) if args.sl else LIVE_SL_PCT
    tp_pct = (args.tp / 100.0) if args.tp else LIVE_TP_PCT
    tf_key = TF_MAP.get(args.tf, "4h")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    if args.paper_winners:
        winners = pull_paper_sim_winners(min_pf=1.3, min_trades=20)
        print(f"\n{SEP2}")
        print("  PAPER SIM WINNERS  (PF ≥ 1.3, trades ≥ 20)")
        print(SEP2)
        if not winners:
            print("  No results found in paper_sim_results.json")
        else:
            print(f"  {'Strategy':<40}  {'Symbol':<12}  {'Trades':>7}  {'WR%':>7}  {'PF':>7}  {'PnL':>10}")
            print(f"  {'─'*40}  {'─'*12}  {'─'*7}  {'─'*7}  {'─'*7}  {'─'*10}")
            for s in winners[:20]:
                name   = s.get("strategy_name", s.get("name", "?"))[:40]
                sym    = s.get("symbol", "?")[:12]
                trades = s.get("total_trades", s.get("trades", 0))
                wr     = s.get("win_rate_pct", s.get("win_rate", 0))
                pf     = s.get("profit_factor", s.get("pf", 0))
                pnl    = s.get("total_pnl_usd", s.get("pnl", 0))
                print(f"  {name:<40}  {sym:<12}  {trades:>7}  {wr:>7.1f}  {pf:>7.3f}  ${pnl:>9.2f}")
        print(SEP2 + "\n")
        return

    if args.both:
        run_symbol("ETHUSDT", tf_key, sl_pct, tp_pct)
        run_symbol("BTCUSDT", tf_key, sl_pct, tp_pct)
    else:
        run_symbol(args.symbol.upper(), tf_key, sl_pct, tp_pct)


if __name__ == "__main__":
    main()
