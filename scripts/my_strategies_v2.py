"""
my_strategies.py - V2
======================
Proper per-strategy signal implementations optimised for 4H swing trading.
Each category has a real technical implementation instead of the generic fallback.
"""
import pandas as pd
import numpy as np


def calculate_adx(df, n=14):
    """ADX trend strength."""
    h, l, c = df['high'], df['low'], df['close']
    tr = np.maximum(h - l, np.maximum(abs(h - c.shift(1)), abs(l - c.shift(1))))
    atr = tr.rolling(n).mean()
    upmove   = (h - h.shift(1)).clip(lower=0)
    downmove = (l.shift(1) - l).clip(lower=0)
    plus_di  = 100 * (upmove.rolling(n).mean() / atr.replace(0, np.nan)).fillna(0)
    minus_di = 100 * (downmove.rolling(n).mean() / atr.replace(0, np.nan)).fillna(0)
    denom    = (plus_di + minus_di).replace(0, np.nan)
    dx       = 100 * np.abs(plus_di - minus_di) / denom
    return dx.rolling(n).mean().fillna(0)


def _atr(df, n):
    h, l, c = df['high'], df['low'], df['close']
    tr = np.maximum(h - l, np.maximum(abs(h - c.shift(1)), abs(l - c.shift(1))))
    return tr.rolling(int(n)).mean()


def apply_strategy(df, strategy_id, optimize=True, mult=3.0, length=14):
    close, high, low = df['close'], df['high'], df['low']
    vol   = df.get('volume', pd.Series(np.ones(len(df)), index=df.index))
    n     = max(int(length), 3)
    id_u  = strategy_id.upper()

    ema_200      = close.rolling(200).mean()
    adx_val      = calculate_adx(df, n=14)
    strong_trend = adx_val > 20

    # ── 1. KELTNER CHANNEL BREAKOUT ──────────────────────────────────────────
    # Matches: "24 keltner breakout", "kb 4h", "Keltner_Breakout", "KELTNER"
    if any(k in id_u for k in ["KELTNER", "KB 4H", "KB_4H"]):
        ema   = close.ewm(span=n, adjust=False).mean()
        atr_  = _atr(df, n)
        upper = ema + mult * atr_
        lower = ema - mult * atr_
        long_sig  = (close > upper) & (close.shift(1) <= upper.shift(1))
        short_sig = (close < lower) & (close.shift(1) >= lower.shift(1))
        raw = np.where(long_sig, 1, np.where(short_sig, -1, 0))
        raw = pd.Series(raw, index=df.index).replace(0, np.nan).ffill().fillna(0)
        if optimize:
            raw = np.where((raw == 1) & (close > ema_200), 1,
                           np.where((raw == -1) & (close < ema_200), -1, 0))
        return np.array(raw).astype(int)

    # ── 2. MACD BREAKOUT ─────────────────────────────────────────────────────
    # Matches: "07 macd breakout", "MACD_Breakout", any "MACD"
    elif any(k in id_u for k in ["MACD"]):
        fast_p = max(int(n * 0.5), 3)
        slow_p = n
        sig_p  = max(int(n * 0.33), 3)
        macd   = close.ewm(span=fast_p, adjust=False).mean() - close.ewm(span=slow_p, adjust=False).mean()
        signal = macd.ewm(span=sig_p, adjust=False).mean()
        hist   = macd - signal
        vol_avg = vol.rolling(n).mean()
        vol_ok  = vol > vol_avg * max(mult * 0.5, 0.8)
        long_sig  = (hist > 0) & (hist.shift(1) <= 0)
        short_sig = (hist < 0) & (hist.shift(1) >= 0)
        raw = np.where(long_sig & vol_ok, 1, np.where(short_sig & vol_ok, -1, 0))
        raw = pd.Series(raw, index=df.index).replace(0, np.nan).ffill().fillna(0)
        if optimize:
            raw = np.where((raw == 1) & strong_trend, 1,
                           np.where((raw == -1) & strong_trend, -1, 0))
        return np.array(raw).astype(int)

    # ── 3. AGGRESSIVE ENTRY (Donchian channel breakout) ──────────────────────
    # Matches: "10 aggressive entry", "Aggressive_Entry", "AGGRESSIVE"
    elif any(k in id_u for k in ["AGGRESSIVE"]):
        don_high = high.rolling(n).max()
        don_low  = low.rolling(n).min()
        atr_     = _atr(df, n)
        buf      = mult * atr_ * 0.1
        long_sig  = close > (don_high.shift(1) + buf)
        short_sig = close < (don_low.shift(1)  - buf)
        raw = np.where(long_sig, 1, np.where(short_sig, -1, 0))
        raw = pd.Series(raw, index=df.index).replace(0, np.nan).ffill().fillna(0)
        if optimize:
            raw = np.where((raw == 1) & strong_trend, 1,
                           np.where((raw == -1) & strong_trend, -1, 0))
        return np.array(raw).astype(int)

    # ── 4. ICHIMOKU TREND PRO / ICHIMOKU MACD PRO ────────────────────────────
    # Matches: "22 ichimoku trend pro", "23 ichimoku macd pro", "Ichimoku_Trend_Pro"
    elif any(k in id_u for k in ["ICHIMOKU", "ICHI"]):
        t_n    = max(int(n * 0.35), 3)
        k_n    = n
        tenkan = (high.rolling(t_n).max() + low.rolling(t_n).min()) / 2
        kijun  = (high.rolling(k_n).max() + low.rolling(k_n).min()) / 2
        span_a = ((tenkan + kijun) / 2).shift(k_n)
        span_b = ((high.rolling(k_n * 2).max() + low.rolling(k_n * 2).min()) / 2).shift(k_n)
        cloud_top = np.maximum(span_a, span_b)
        cloud_bot = np.minimum(span_a, span_b)
        tk_bull = (tenkan > kijun) & (tenkan.shift(1) <= kijun.shift(1))
        tk_bear = (tenkan < kijun) & (tenkan.shift(1) >= kijun.shift(1))
        bull    = tk_bull & (close > cloud_top)
        bear    = tk_bear & (close < cloud_bot)
        raw = np.where(bull, 1, np.where(bear, -1, 0))
        raw = pd.Series(raw, index=df.index).replace(0, np.nan).ffill().fillna(0)
        if optimize:
            raw = np.where((raw == 1) & (close > ema_200), 1,
                           np.where((raw == -1) & (close < ema_200), -1, 0))
        return np.array(raw).astype(int)

    # ── 5. FULL MOMENTUM / OBV / WAVETREND ───────────────────────────────────
    elif any(k in id_u for k in ["FULL_MOMENTUM", "FULL MOMENTUM", "OBV", "WAVETREND", "MOMENTUM", "FLOW"]):
        obv     = (np.sign(close.diff()) * vol).fillna(0).cumsum()
        obv_ema = obv.ewm(span=n, adjust=False).mean()
        obv_sig = obv.ewm(span=max(int(n * 0.4), 3), adjust=False).mean()
        cross_up   = (obv_ema > obv_sig) & (obv_ema.shift(1) <= obv_sig.shift(1))
        cross_down = (obv_ema < obv_sig) & (obv_ema.shift(1) >= obv_sig.shift(1))
        raw = np.where(cross_up, 1, np.where(cross_down, -1, 0))
        raw = pd.Series(raw, index=df.index).replace(0, np.nan).ffill().fillna(0)
        if optimize:
            raw = np.where((raw == 1) & strong_trend, 1,
                           np.where((raw == -1) & strong_trend, -1, 0))
        return np.array(raw).astype(int)

    # ── 6. PSAR / PARABOLIC SAR ──────────────────────────────────────────────
    elif any(k in id_u for k in ["PSAR", "PARABOLIC", "44", "56", "57"]):
        af_step = max(mult * 0.005, 0.005)
        af_max  = max(mult * 0.05,  0.05)
        try:
            n_bars    = len(close)
            cv = close.values; hv = high.values; lv = low.values
            bull_vals = np.zeros(n_bars)
            _psar = cv[0]; _bull = True; _af = af_step; _ep = lv[0]
            for i in range(1, n_bars):
                if _bull:
                    _psar = _psar + _af * (_ep - _psar)
                    _psar = min(_psar, lv[i-1], lv[i-2] if i > 1 else lv[i-1])
                    if lv[i] < _psar:
                        _bull = False; _psar = _ep; _af = af_step; _ep = hv[i]
                    else:
                        if hv[i] > _ep:
                            _ep = hv[i]; _af = min(_af + af_step, af_max)
                else:
                    _psar = _psar + _af * (_ep - _psar)
                    _psar = max(_psar, hv[i-1], hv[i-2] if i > 1 else hv[i-1])
                    if hv[i] > _psar:
                        _bull = True; _psar = _ep; _af = af_step; _ep = lv[i]
                    else:
                        if lv[i] < _ep:
                            _ep = lv[i]; _af = min(_af + af_step, af_max)
                bull_vals[i] = 1 if _bull else -1
            vol_ma = vol.rolling(n).mean()
            vol_ok = (vol > vol_ma * max(mult * 0.4, 0.8)).values
            raw = np.where(vol_ok, bull_vals, 0)
        except Exception:
            raw = np.where(close > close.rolling(n).mean(), 1, -1).astype(int)
        if optimize:
            raw = np.where((raw == 1) & strong_trend.values, 1,
                           np.where((raw == -1) & strong_trend.values, -1, 0))
        return raw.astype(int)

    # ── 7. SUPERTREND / ATR / SMA / EMA / RIBBON ─────────────────────────────
    elif any(k in id_u for k in ["SUPERTREND", "ATR", "SMA", "EMA", "RIBBON", "CROSS"]):
        atr_     = _atr(df, n)
        adj_mult = mult * 1.1 if "RIBBON" in id_u else mult
        upper = (high + low) / 2 + adj_mult * atr_
        lower = (high + low) / 2 - adj_mult * atr_
        raw   = np.where(close > upper.shift(1), 1, np.where(close < lower.shift(1), -1, 0))
        raw   = pd.Series(raw, index=df.index).replace(0, np.nan).ffill().fillna(0)
        if optimize:
            raw = np.where((raw == 1) & (close > ema_200), 1,
                           np.where((raw == -1) & (close < ema_200), -1, 0))
        return np.array(raw).astype(int)

    # ── 8. SQUEEZE / MEAN REVERSION / ML ─────────────────────────────────────
    elif any(k in id_u for k in ["SQUEEZE", "REVERSION", "LORENTZIAN", "ML", "MATRIX"]):
        basis = close.rolling(n).mean()
        dev   = mult * close.rolling(n).std()
        raw   = np.where(close < basis - dev, 1, np.where(close > basis + dev, -1, 0))
        return raw.astype(int)

    # ── 9. SMC / LIQUIDITY / INSTITUTIONAL ───────────────────────────────────
    elif any(k in id_u for k in ["SMC", "LIQUIDITY", "INSTITUTIONAL"]):
        raw = np.where(close > close.shift(n), 1, np.where(close < close.shift(n), -1, 0))
        if optimize:
            raw = np.where(strong_trend.values, raw, 0)
        return raw.astype(int)

    # ── 10. VWAP / BREAK / ENTRY ─────────────────────────────────────────────
    elif any(k in id_u for k in ["VWAP", "BREAK", "ENTRY"]):
        vwap  = (close * vol).rolling(n).sum() / vol.rolling(n).sum()
        atr_  = _atr(df, n)
        upper = vwap + mult * atr_
        lower = vwap - mult * atr_
        raw   = np.where(close > upper, 1, np.where(close < lower, -1, 0))
        raw   = pd.Series(raw, index=df.index).replace(0, np.nan).ffill().fillna(0)
        if optimize:
            raw = np.where((raw == 1) & strong_trend, 1,
                           np.where((raw == -1) & strong_trend, -1, 0))
        return np.array(raw).astype(int)

    # ── FALLBACK: dual EMA crossover ─────────────────────────────────────────
    else:
        fast = close.ewm(span=n,          adjust=False).mean()
        slow = close.ewm(span=int(n*2.1), adjust=False).mean()
        cross_up   = (fast > slow) & (fast.shift(1) <= slow.shift(1))
        cross_down = (fast < slow) & (fast.shift(1) >= slow.shift(1))
        raw = np.where(cross_up, 1, np.where(cross_down, -1, 0))
        raw = pd.Series(raw, index=df.index).replace(0, np.nan).ffill().fillna(0)
        return np.array(raw).astype(int)
