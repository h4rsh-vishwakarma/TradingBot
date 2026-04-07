"""
my_strategies.py - V3
======================
Proper per-strategy signal implementations optimised for 4H swing trading.
V2 strategies preserved exactly. V3 adds 20 premium indicator strategies (70-89).
Each strategy returns np.array of int (1=long, -1=short, 0=flat).
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


def _wma(series, n):
    """Weighted Moving Average (linearly weighted)."""
    weights = np.arange(1, n + 1, dtype=float)
    return series.rolling(n).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)


def _supertrend_direction(close, high, low, atr_n, m):
    """Return a +1/-1 Series for supertrend direction."""
    upper = (high + low) / 2 + m * atr_n
    lower = (high + low) / 2 - m * atr_n
    n_bars = len(close)
    cv = close.values
    uv = upper.values
    lv_band = lower.values
    direction = np.zeros(n_bars, dtype=int)
    final_upper = uv.copy()
    final_lower = lv_band.copy()
    for i in range(1, n_bars):
        if np.isnan(uv[i]) or np.isnan(lv_band[i]):
            direction[i] = direction[i - 1]
            continue
        final_upper[i] = uv[i] if (uv[i] < final_upper[i - 1] or cv[i - 1] > final_upper[i - 1]) else final_upper[i - 1]
        final_lower[i] = lv_band[i] if (lv_band[i] > final_lower[i - 1] or cv[i - 1] < final_lower[i - 1]) else final_lower[i - 1]
        if direction[i - 1] == 1:
            direction[i] = 1 if cv[i] > final_lower[i] else -1
        else:
            direction[i] = -1 if cv[i] < final_upper[i] else 1
    return pd.Series(direction, index=close.index)


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
    elif any(k in id_u for k in ["FULL_MOMENTUM", "FULL MOMENTUM", "OBV", "MOMENTUM", "FLOW"]):
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

    # ═══════════════════════════════════════════════════════════════════════════
    # V3 PREMIUM STRATEGIES (70-89)
    # ═══════════════════════════════════════════════════════════════════════════

    # ── 70. WILLIAMS %R MOMENTUM ─────────────────────────────────────────────
    # Keyword: "WILLIAMS" or "WR_MOM"
    elif any(k in id_u for k in ["WILLIAMS", "WR_MOM"]):
        hh = high.rolling(n).max()
        ll = low.rolling(n).min()
        wr = -100 * (hh - close) / (hh - ll).replace(0, np.nan)
        wr = wr.fillna(-50)
        # Oversold exit: WR crosses up through -80 (was <= -80, now > -80)
        long_sig  = (wr > -80) & (wr.shift(1) <= -80)
        # Overbought exit: WR crosses down through -20 (was >= -20, now < -20)
        short_sig = (wr < -20) & (wr.shift(1) >= -20)
        vol_ok    = vol > vol.rolling(n).mean() * mult * 0.5
        raw = np.where(long_sig & vol_ok, 1, np.where(short_sig & vol_ok, -1, 0))
        raw = pd.Series(raw, index=df.index).replace(0, np.nan).ffill().fillna(0)
        if optimize:
            raw = np.where((raw == 1) & strong_trend, 1,
                           np.where((raw == -1) & strong_trend, -1, 0))
        return np.array(raw).astype(int)

    # ── 71. STOCHASTIC RSI POWER ──────────────────────────────────────────────
    # Keyword: "STOCHRSI" or "STOCH_RSI" or "STOCHASTIC"
    elif any(k in id_u for k in ["STOCHRSI", "STOCH_RSI", "STOCHASTIC"]):
        # Classic RSI
        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(n).mean()
        loss  = (-delta.clip(upper=0)).rolling(n).mean()
        rs    = gain / loss.replace(0, np.nan)
        rsi   = 100 - (100 / (1 + rs))
        rsi   = rsi.fillna(50)
        # Stochastic RSI
        rsi_min = rsi.rolling(n).min()
        rsi_max = rsi.rolling(n).max()
        stoch_rsi = (rsi - rsi_min) / (rsi_max - rsi_min).replace(0, np.nan)
        stoch_rsi = stoch_rsi.fillna(0.5)
        # K and D lines
        k_line = stoch_rsi.rolling(3).mean()
        d_line = k_line.rolling(3).mean()
        # BUY: K crosses above D when both < 0.2
        long_sig  = (k_line > d_line) & (k_line.shift(1) <= d_line.shift(1)) & (k_line < 0.2) & (d_line < 0.2)
        # SELL: K crosses below D when both > 0.8
        short_sig = (k_line < d_line) & (k_line.shift(1) >= d_line.shift(1)) & (k_line > 0.8) & (d_line > 0.8)
        raw = np.where(long_sig, 1, np.where(short_sig, -1, 0))
        raw = pd.Series(raw, index=df.index).replace(0, np.nan).ffill().fillna(0)
        if optimize:
            raw = np.where((raw == 1) & (close > ema_200), 1,
                           np.where((raw == -1) & (close < ema_200), -1, 0))
        return np.array(raw).astype(int)

    # ── 72. HULL MA TREND ─────────────────────────────────────────────────────
    # Keyword: "HULL" or "HMA"
    elif any(k in id_u for k in ["HULL", "HMA"]):
        half_n  = max(int(n / 2), 2)
        sqrt_n  = max(int(np.sqrt(n)), 2)
        wma_n   = _wma(close, n)
        wma_h   = _wma(close, half_n)
        raw_hma = 2 * wma_h - wma_n
        hma     = _wma(raw_hma, sqrt_n)
        # BUY: HMA turns up (HMA > HMA.shift(1) and HMA.shift(1) <= HMA.shift(2))
        long_sig  = (hma > hma.shift(1)) & (hma.shift(1) <= hma.shift(2))
        # SELL: HMA turns down (HMA < HMA.shift(1) and HMA.shift(1) >= HMA.shift(2))
        short_sig = (hma < hma.shift(1)) & (hma.shift(1) >= hma.shift(2))
        raw = np.where(long_sig, 1, np.where(short_sig, -1, 0))
        raw = pd.Series(raw, index=df.index).replace(0, np.nan).ffill().fillna(0)
        if optimize:
            raw = np.where((raw == 1) & strong_trend, 1,
                           np.where((raw == -1) & strong_trend, -1, 0))
        return np.array(raw).astype(int)

    # ── 73. SQUEEZE MOMENTUM (LazyBear) ──────────────────────────────────────
    # Keyword: "SQUEEZE_MOM" or "LAZYBEAR" or "SQZ"
    elif any(k in id_u for k in ["SQUEEZE_MOM", "LAZYBEAR", "SQZ"]):
        sma_n   = close.rolling(n).mean()
        std_n   = close.rolling(n).std()
        bb_up   = sma_n + mult * std_n
        bb_lo   = sma_n - mult * std_n
        ema_n   = close.ewm(span=n, adjust=False).mean()
        atr_n   = _atr(df, n)
        kc_up   = ema_n + 1.5 * atr_n
        kc_lo   = ema_n - 1.5 * atr_n
        # Squeeze: BB inside KC
        squeeze_on  = (bb_up < kc_up) & (bb_lo > kc_lo)
        squeeze_off = ~squeeze_on
        was_squeeze = squeeze_on.shift(1).fillna(False)
        # Momentum value: close relative to mid-range + EMA
        hh_n = high.rolling(n).max()
        ll_n = low.rolling(n).min()
        mom_val = close - ((hh_n + ll_n) / 2 + ema_n) / 2
        mom_ema = mom_val.ewm(span=n, adjust=False).mean()
        # Signal: squeeze OFF after being ON
        released = squeeze_off & was_squeeze
        long_sig  = released & (mom_ema > 0)
        short_sig = released & (mom_ema < 0)
        raw = np.where(long_sig, 1, np.where(short_sig, -1, 0))
        raw = pd.Series(raw, index=df.index).replace(0, np.nan).ffill().fillna(0)
        if optimize:
            raw = np.where((raw == 1) & (close > ema_200), 1,
                           np.where((raw == -1) & (close < ema_200), -1, 0))
        return np.array(raw).astype(int)

    # ── 74. CCI BREAKOUT ──────────────────────────────────────────────────────
    # Keyword: "CCI"
    elif "CCI" in id_u:
        tp     = (high + low + close) / 3
        sma_tp = tp.rolling(n).mean()
        mad    = (tp - sma_tp).abs().rolling(n).mean()
        cci    = (tp - sma_tp) / (0.015 * mad.replace(0, np.nan))
        cci    = cci.fillna(0)
        # BUY: CCI crosses above +100
        long_sig  = (cci > 100) & (cci.shift(1) <= 100)
        # SELL: CCI crosses below -100
        short_sig = (cci < -100) & (cci.shift(1) >= -100)
        raw = np.where(long_sig, 1, np.where(short_sig, -1, 0))
        raw = pd.Series(raw, index=df.index).replace(0, np.nan).ffill().fillna(0)
        if optimize:
            ema_n = close.ewm(span=n, adjust=False).mean()
            raw = np.where((raw == 1) & (close > ema_n), 1,
                           np.where((raw == -1) & (close < ema_n), -1, 0))
        return np.array(raw).astype(int)

    # ── 75. MFI REVERSAL ──────────────────────────────────────────────────────
    # Keyword: "MFI" or "MONEY_FLOW"
    elif any(k in id_u for k in ["MFI", "MONEY_FLOW"]):
        tp  = (high + low + close) / 3
        mf  = tp * vol
        pos_mf = mf.where(tp > tp.shift(1), 0.0).rolling(n).sum()
        neg_mf = mf.where(tp < tp.shift(1), 0.0).rolling(n).sum()
        mfi = 100 - (100 / (1 + pos_mf / neg_mf.replace(0, np.nan)))
        mfi = mfi.fillna(50)
        # BUY: MFI rises above 20 from below (oversold recovery)
        long_sig  = (mfi > 20) & (mfi.shift(1) <= 20)
        # SELL: MFI falls below 80 from above (overbought exit)
        short_sig = (mfi < 80) & (mfi.shift(1) >= 80)
        raw = np.where(long_sig, 1, np.where(short_sig, -1, 0))
        raw = pd.Series(raw, index=df.index).replace(0, np.nan).ffill().fillna(0)
        if optimize:
            raw = np.where((raw == 1) & strong_trend, 1,
                           np.where((raw == -1) & strong_trend, -1, 0))
        return np.array(raw).astype(int)

    # ── 76. VORTEX TREND ──────────────────────────────────────────────────────
    # Keyword: "VORTEX" or "VI"
    elif any(k in id_u for k in ["VORTEX", "VI_"]):
        atr_n  = _atr(df, n)
        atr_sum = atr_n.rolling(n).sum().replace(0, np.nan)
        vi_pos = (high - low.shift(1)).abs().rolling(n).sum() / atr_sum
        vi_neg = (low - high.shift(1)).abs().rolling(n).sum() / atr_sum
        vi_pos = vi_pos.fillna(1)
        vi_neg = vi_neg.fillna(1)
        # BUY: VI+ crosses above VI-
        long_sig  = (vi_pos > vi_neg) & (vi_pos.shift(1) <= vi_neg.shift(1))
        # SELL: VI- crosses above VI+
        short_sig = (vi_neg > vi_pos) & (vi_neg.shift(1) <= vi_pos.shift(1))
        raw = np.where(long_sig, 1, np.where(short_sig, -1, 0))
        raw = pd.Series(raw, index=df.index).replace(0, np.nan).ffill().fillna(0)
        if optimize:
            raw = np.where((raw == 1) & (close > ema_200), 1,
                           np.where((raw == -1) & (close < ema_200), -1, 0))
        return np.array(raw).astype(int)

    # ── 77. DEMA RIBBON ───────────────────────────────────────────────────────
    # Keyword: "DEMA" or "RIBBON_FAST"
    elif any(k in id_u for k in ["DEMA", "RIBBON_FAST"]):
        ema_fast       = close.ewm(span=n, adjust=False).mean()
        ema_fast2      = ema_fast.ewm(span=n, adjust=False).mean()
        dema_fast      = 2 * ema_fast - ema_fast2
        ema_slow       = close.ewm(span=n * 2, adjust=False).mean()
        ema_slow2      = ema_slow.ewm(span=n * 2, adjust=False).mean()
        dema_slow      = 2 * ema_slow - ema_slow2
        # BUY: fast DEMA crosses above slow DEMA
        long_sig  = (dema_fast > dema_slow) & (dema_fast.shift(1) <= dema_slow.shift(1))
        short_sig = (dema_fast < dema_slow) & (dema_fast.shift(1) >= dema_slow.shift(1))
        raw = np.where(long_sig, 1, np.where(short_sig, -1, 0))
        raw = pd.Series(raw, index=df.index).replace(0, np.nan).ffill().fillna(0)
        if optimize:
            raw = np.where((raw == 1) & strong_trend & (close > ema_200), 1,
                           np.where((raw == -1) & strong_trend & (close < ema_200), -1, 0))
        return np.array(raw).astype(int)

    # ── 78. HEIKIN ASHI TREND ─────────────────────────────────────────────────
    # Keyword: "HEIKIN" or "HA_TREND"
    elif any(k in id_u for k in ["HEIKIN", "HA_TREND"]):
        n_bars = len(close)
        oc = df['open'].values if 'open' in df.columns else close.values
        hv = high.values; lv = low.values; cv = close.values
        ha_open  = np.zeros(n_bars)
        ha_close = (oc + hv + lv + cv) / 4
        ha_open[0] = (oc[0] + cv[0]) / 2
        for i in range(1, n_bars):
            ha_open[i] = (ha_open[i - 1] + ha_close[i - 1]) / 2
        ha_high = np.maximum(hv, np.maximum(ha_open, ha_close))
        ha_low  = np.minimum(lv, np.minimum(ha_open, ha_close))
        ha_bull = ha_close > ha_open
        result  = np.zeros(n_bars, dtype=int)
        ema_trend = close > ema_200
        for i in range(2, n_bars):
            if ha_bull[i] and ha_bull[i - 1] and ha_bull[i - 2]:
                # Check that previous candle was bearish (reversal)
                if not ha_bull[i - 3] if i >= 3 else True:
                    result[i] = 1
            if not ha_bull[i] and not ha_bull[i - 1] and not ha_bull[i - 2]:
                if ha_bull[i - 3] if i >= 3 else True:
                    result[i] = -1
        raw = pd.Series(result, index=df.index).replace(0, np.nan).ffill().fillna(0)
        if optimize:
            raw = np.where((raw == 1) & (close > ema_200), 1,
                           np.where((raw == -1) & (close < ema_200), -1, 0))
        return np.array(raw).astype(int)

    # ── 79. WAVETREND OSCILLATOR ──────────────────────────────────────────────
    # Keyword: "WAVETREND" or "WT_OSC" or "WAVE_TREND"
    # NOTE: "WAVETREND" was in the v2 OBV block — moved here first in v3.
    # The v2 OBV block now only matches FULL_MOMENTUM, OBV, MOMENTUM, FLOW (WAVETREND removed).
    elif any(k in id_u for k in ["WAVETREND", "WT_OSC", "WAVE_TREND"]):
        esa  = close.ewm(span=10, adjust=False).mean()
        d    = (close - esa).abs().ewm(span=10, adjust=False).mean()
        ci   = (close - esa) / (0.015 * d.replace(0, np.nan))
        ci   = ci.fillna(0)
        wt1  = ci.ewm(span=21, adjust=False).mean()
        wt2  = wt1.rolling(4).mean()
        # BUY: wt1 crosses above wt2 in oversold zone
        long_sig  = (wt1 > wt2) & (wt1.shift(1) <= wt2.shift(1)) & (wt1 < -53)
        # SELL: wt1 crosses below wt2 in overbought zone
        short_sig = (wt1 < wt2) & (wt1.shift(1) >= wt2.shift(1)) & (wt1 > 53)
        raw = np.where(long_sig, 1, np.where(short_sig, -1, 0))
        raw = pd.Series(raw, index=df.index).replace(0, np.nan).ffill().fillna(0)
        return np.array(raw).astype(int)

    # ── 80. LAGUERRE RSI ──────────────────────────────────────────────────────
    # Keyword: "LAGUERRE" or "LAGRSI"
    elif any(k in id_u for k in ["LAGUERRE", "LAGRSI"]):
        gamma = min(max(mult / 4.0, 0.1), 0.99) if optimize else 0.8
        cv    = close.values
        n_bars = len(cv)
        L0 = np.zeros(n_bars)
        L1 = np.zeros(n_bars)
        L2 = np.zeros(n_bars)
        L3 = np.zeros(n_bars)
        lrsi = np.zeros(n_bars)
        for i in range(1, n_bars):
            L0[i] = (1 - gamma) * cv[i] + gamma * L0[i - 1]
            L1[i] = -gamma * L0[i] + L0[i - 1] + gamma * L1[i - 1]
            L2[i] = -gamma * L1[i] + L1[i - 1] + gamma * L2[i - 1]
            L3[i] = -gamma * L2[i] + L2[i - 1] + gamma * L3[i - 1]
            cu = max(L0[i] - L1[i], 0) + max(L1[i] - L2[i], 0) + max(L2[i] - L3[i], 0)
            cd = max(L1[i] - L0[i], 0) + max(L2[i] - L1[i], 0) + max(L3[i] - L2[i], 0)
            denom = cu + cd
            lrsi[i] = cu / denom if denom > 0 else 0.5
        lrsi_s = pd.Series(lrsi, index=df.index)
        # BUY: LRSI crosses above 0.2 from below
        long_sig  = (lrsi_s > 0.2) & (lrsi_s.shift(1) <= 0.2)
        # SELL: LRSI crosses below 0.8 from above
        short_sig = (lrsi_s < 0.8) & (lrsi_s.shift(1) >= 0.8)
        raw = np.where(long_sig, 1, np.where(short_sig, -1, 0))
        raw = pd.Series(raw, index=df.index).replace(0, np.nan).ffill().fillna(0)
        return np.array(raw).astype(int)

    # ── 81. ELDER RAY TREND ───────────────────────────────────────────────────
    # Keyword: "ELDER" or "ELDER_RAY"
    elif any(k in id_u for k in ["ELDER", "ELDER_RAY"]):
        ema_n       = close.ewm(span=n, adjust=False).mean()
        bulls_power = high - ema_n
        bears_power = low - ema_n
        # EMA rising
        ema_rising  = ema_n > ema_n.shift(1)
        ema_falling = ema_n < ema_n.shift(1)
        # BUY: EMA rising AND bulls > 0 AND bears crosses above 0
        long_sig  = ema_rising & (bulls_power > 0) & (bears_power > 0) & (bears_power.shift(1) <= 0)
        # SELL: EMA falling AND bears < 0 AND bulls crosses below 0
        short_sig = ema_falling & (bears_power < 0) & (bulls_power < 0) & (bulls_power.shift(1) >= 0)
        raw = np.where(long_sig, 1, np.where(short_sig, -1, 0))
        raw = pd.Series(raw, index=df.index).replace(0, np.nan).ffill().fillna(0)
        if optimize:
            raw = np.where((raw == 1) & strong_trend, 1,
                           np.where((raw == -1) & strong_trend, -1, 0))
        return np.array(raw).astype(int)

    # ── 82. CHANDELIER EXIT ───────────────────────────────────────────────────
    # Keyword: "CHANDELIER" or "CHAN_EXIT"
    elif any(k in id_u for k in ["CHANDELIER", "CHAN_EXIT"]):
        atr_n  = _atr(df, n)
        hh_n   = high.rolling(n).max()
        ll_n   = low.rolling(n).min()
        chan_long  = hh_n - mult * atr_n   # long stop (trail below highest high)
        chan_short = ll_n + mult * atr_n   # short stop (trail above lowest low)
        # BUY: close crosses above the short-side chandelier stop
        long_sig  = (close > chan_short) & (close.shift(1) <= chan_short.shift(1))
        # SELL: close crosses below the long-side chandelier stop
        short_sig = (close < chan_long) & (close.shift(1) >= chan_long.shift(1))
        raw = np.where(long_sig, 1, np.where(short_sig, -1, 0))
        raw = pd.Series(raw, index=df.index).replace(0, np.nan).ffill().fillna(0)
        if optimize:
            vol_ok = vol > vol.rolling(n).mean()
            raw = np.where((raw == 1) & vol_ok, 1,
                           np.where((raw == -1) & vol_ok, -1, 0))
        return np.array(raw).astype(int)

    # ── 83. TRIPLE EMA CROSS (TEMA) ───────────────────────────────────────────
    # Keyword: "TEMA" or "TRIPLE_EMA"
    elif any(k in id_u for k in ["TEMA", "TRIPLE_EMA"]):
        e1_f = close.ewm(span=n, adjust=False).mean()
        e2_f = e1_f.ewm(span=n, adjust=False).mean()
        e3_f = e2_f.ewm(span=n, adjust=False).mean()
        tema_fast = 3 * e1_f - 3 * e2_f + e3_f
        e1_s = close.ewm(span=n * 2, adjust=False).mean()
        e2_s = e1_s.ewm(span=n * 2, adjust=False).mean()
        e3_s = e2_s.ewm(span=n * 2, adjust=False).mean()
        tema_slow = 3 * e1_s - 3 * e2_s + e3_s
        long_sig  = (tema_fast > tema_slow) & (tema_fast.shift(1) <= tema_slow.shift(1))
        short_sig = (tema_fast < tema_slow) & (tema_fast.shift(1) >= tema_slow.shift(1))
        raw = np.where(long_sig, 1, np.where(short_sig, -1, 0))
        raw = pd.Series(raw, index=df.index).replace(0, np.nan).ffill().fillna(0)
        if optimize:
            adx_strong = adx_val > 20
            raw = np.where((raw == 1) & adx_strong & (close > ema_200), 1,
                           np.where((raw == -1) & adx_strong & (close < ema_200), -1, 0))
        return np.array(raw).astype(int)

    # ── 84. RSI MOMENTUM ──────────────────────────────────────────────────────
    # Keyword: "RSI_MOM" or "RSI_TREND"  (NOT plain "RSI" to avoid conflicts)
    elif any(k in id_u for k in ["RSI_MOM", "RSI_TREND"]):
        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(n).mean()
        loss  = (-delta.clip(upper=0)).rolling(n).mean()
        rs    = gain / loss.replace(0, np.nan)
        rsi   = (100 - (100 / (1 + rs))).fillna(50)
        ema_fast = close.ewm(span=n, adjust=False).mean()
        ema_slow = close.ewm(span=n * 2, adjust=False).mean()
        # BUY: RSI crosses above 50 AND ema_fast > ema_slow
        long_sig  = (rsi > 50) & (rsi.shift(1) <= 50) & (ema_fast > ema_slow)
        # SELL: RSI crosses below 50 AND ema_fast < ema_slow
        short_sig = (rsi < 50) & (rsi.shift(1) >= 50) & (ema_fast < ema_slow)
        raw = np.where(long_sig, 1, np.where(short_sig, -1, 0))
        raw = pd.Series(raw, index=df.index).replace(0, np.nan).ffill().fillna(0)
        if optimize:
            adx_strong = adx_val > 25
            raw = np.where((raw == 1) & adx_strong, 1,
                           np.where((raw == -1) & adx_strong, -1, 0))
        return np.array(raw).astype(int)

    # ── 85. SUPERTREND MULTI ──────────────────────────────────────────────────
    # Keyword: "SUPERTREND_MULTI" or "ST_MULTI"
    elif any(k in id_u for k in ["SUPERTREND_MULTI", "ST_MULTI"]):
        atr_n  = _atr(df, n)
        dir1   = _supertrend_direction(close, high, low, atr_n, mult)
        dir2   = _supertrend_direction(close, high, low, atr_n, mult * 1.5)
        dir3   = _supertrend_direction(close, high, low, atr_n, mult * 2.0)
        bull_votes = (dir1 == 1).astype(int) + (dir2 == 1).astype(int) + (dir3 == 1).astype(int)
        bear_votes = (dir1 == -1).astype(int) + (dir2 == -1).astype(int) + (dir3 == -1).astype(int)
        # Signal on majority vote change
        majority_bull = bull_votes >= 2
        majority_bear = bear_votes >= 2
        long_sig  = majority_bull & ~majority_bull.shift(1).fillna(False)
        short_sig = majority_bear & ~majority_bear.shift(1).fillna(False)
        raw = np.where(long_sig, 1, np.where(short_sig, -1, 0))
        raw = pd.Series(raw, index=df.index).replace(0, np.nan).ffill().fillna(0)
        return np.array(raw).astype(int)

    # ── 86. BB SQUEEZE BREAK ──────────────────────────────────────────────────
    # Keyword: "BB_SQUEEZE" or "BBAND_BREAK" or "BB_BREAK"
    elif any(k in id_u for k in ["BB_SQUEEZE", "BBAND_BREAK", "BB_BREAK"]):
        sma_n  = close.rolling(n).mean()
        std_n  = close.rolling(n).std()
        bb_up  = sma_n + mult * std_n
        bb_lo  = sma_n - mult * std_n
        bb_w   = ((bb_up - bb_lo) / sma_n.replace(0, np.nan)).fillna(0)
        # Squeeze: width near n*3 period minimum
        min_w  = bb_w.rolling(n * 3).min()
        in_squeeze = bb_w < min_w * 1.1
        # Breakout after squeeze
        long_sig  = (close > bb_up) & in_squeeze.shift(1).fillna(False)
        short_sig = (close < bb_lo) & in_squeeze.shift(1).fillna(False)
        raw = np.where(long_sig, 1, np.where(short_sig, -1, 0))
        raw = pd.Series(raw, index=df.index).replace(0, np.nan).ffill().fillna(0)
        if optimize:
            adx_rising = adx_val > adx_val.shift(1)
            raw = np.where((raw == 1) & adx_rising, 1,
                           np.where((raw == -1) & adx_rising, -1, 0))
        return np.array(raw).astype(int)

    # ── 87. VOLUME WEIGHTED BREAKOUT ──────────────────────────────────────────
    # Keyword: "VOL_WEIGHTED" or "VWB" or "VOLBREAK"
    elif any(k in id_u for k in ["VOL_WEIGHTED", "VWB", "VOLBREAK"]):
        vol_sum = vol.rolling(n).sum().replace(0, np.nan)
        vwap_r  = (close * vol).rolling(n).sum() / vol_sum
        vol_ma  = vol.rolling(n).mean()
        strong_vol = vol > vol_ma * mult
        # Price at n-period high/low (shifted by 1 to avoid lookahead)
        at_high = close >= high.rolling(n).max().shift(1)
        at_low  = close <= low.rolling(n).min().shift(1)
        long_sig  = strong_vol & at_high
        short_sig = strong_vol & at_low
        raw = np.where(long_sig, 1, np.where(short_sig, -1, 0))
        raw = pd.Series(raw, index=df.index).replace(0, np.nan).ffill().fillna(0)
        if optimize:
            raw = np.where((raw == 1) & (close > ema_200), 1,
                           np.where((raw == -1) & (close < ema_200), -1, 0))
        return np.array(raw).astype(int)

    # ── 88. MARKET CIPHER B (WaveTrend + MFI combo) ───────────────────────────
    # Keyword: "CIPHER" or "MARKET_CIPHER" or "MCB"
    elif any(k in id_u for k in ["CIPHER", "MARKET_CIPHER", "MCB"]):
        # WaveTrend
        esa  = close.ewm(span=10, adjust=False).mean()
        d_wt = (close - esa).abs().ewm(span=10, adjust=False).mean()
        ci   = (close - esa) / (0.015 * d_wt.replace(0, np.nan))
        ci   = ci.fillna(0)
        wt1  = ci.ewm(span=21, adjust=False).mean()
        wt2  = wt1.rolling(4).mean()
        # MFI
        tp    = (high + low + close) / 3
        mf    = tp * vol
        pos_mf = mf.where(tp > tp.shift(1), 0.0).rolling(n).sum()
        neg_mf = mf.where(tp < tp.shift(1), 0.0).rolling(n).sum()
        mfi   = (100 - (100 / (1 + pos_mf / neg_mf.replace(0, np.nan)))).fillna(50)
        mfi_positive = mfi > mfi.shift(1)   # MFI turning up
        mfi_negative = mfi < mfi.shift(1)   # MFI turning down
        # Diamond BUY: wt oversold AND MFI turning positive
        long_sig  = (wt1 < -53) & (wt1 > wt2) & (wt1.shift(1) <= wt2.shift(1)) & mfi_positive
        # Diamond SELL: wt overbought AND MFI turning negative
        short_sig = (wt1 > 53) & (wt1 < wt2) & (wt1.shift(1) >= wt2.shift(1)) & mfi_negative
        raw = np.where(long_sig, 1, np.where(short_sig, -1, 0))
        raw = pd.Series(raw, index=df.index).replace(0, np.nan).ffill().fillna(0)
        return np.array(raw).astype(int)

    # ── 89. CHANDE MOMENTUM ───────────────────────────────────────────────────
    # Keyword: "CHANDE" or "CMO"
    elif any(k in id_u for k in ["CHANDE", "CMO"]):
        diff     = close.diff()
        sum_up   = diff.clip(lower=0).rolling(n).sum()
        sum_down = (-diff.clip(upper=0)).rolling(n).sum()
        denom    = (sum_up + sum_down).replace(0, np.nan)
        cmo      = (100 * (sum_up - sum_down) / denom).fillna(0)
        # BUY: CMO crosses above 0 from below (moderate, more trades)
        long_sig  = (cmo > 0) & (cmo.shift(1) <= 0)
        # SELL: CMO crosses below 0 from above
        short_sig = (cmo < 0) & (cmo.shift(1) >= 0)
        raw = np.where(long_sig, 1, np.where(short_sig, -1, 0))
        raw = pd.Series(raw, index=df.index).replace(0, np.nan).ffill().fillna(0)
        if optimize:
            vol_ok = vol > vol.rolling(n).mean()
            raw = np.where((raw == 1) & vol_ok, 1,
                           np.where((raw == -1) & vol_ok, -1, 0))
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
