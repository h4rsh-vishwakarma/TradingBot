#!/usr/bin/env python3
"""
backtest_mega_all.py — Full strategy scan across Garima + tradingview_webhook_bot
Covers all Pine scripts from both repos. Fixed $500, 0.06% comm, 30% OOS.
Outputs ranked leaderboard: best strategy × best asset.
"""
from __future__ import annotations
import sys, os, json, time, urllib.request, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path("/home/ubuntu/tradingview_webhook_bot")
DATA_DIR     = PROJECT_ROOT / "storage" / "backtest_data"
COMMISSION   = 0.0006
NOTIONAL     = 500.0

ASSETS = ["ETHUSDT", "BTCUSDT", "SOLUSDT", "LDOUSDT", "SUIUSDT",
          "OPUSDT", "AVAXUSDT", "LINKUSDT", "BNBUSDT"]


def load_ohlcv(symbol: str) -> pd.DataFrame:
    for tag in ["5y", "3y"]:
        f = DATA_DIR / f"{symbol}_{tag}_4h.csv"
        if f.exists():
            df = pd.read_csv(f)
            df.columns = [c.lower() for c in df.columns]
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            for c in ["open", "high", "low", "close", "volume"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            return df.dropna(subset=["open","high","low","close","volume"]).sort_values("timestamp").reset_index(drop=True)
    print(f"  Downloading {symbol}...")
    rows, end_ms = [], int(time.time() * 1000)
    for _ in range(20):
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=4h&limit=1000&endTime={end_ms}"
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                batch = json.loads(r.read())
        except Exception: break
        if not batch: break
        rows = batch + rows; end_ms = batch[0][0] - 1
        if len(batch) < 1000: break
        time.sleep(0.15)
    if not rows: return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["timestamp","open","high","low","close","volume","ct","qav","nt","tbbav","tbqav","ign"])
    df = df[["timestamp","open","high","low","close","volume"]].copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    for c in ["open","high","low","close","volume"]: df[c] = df[c].astype(float)
    df = df.sort_values("timestamp").reset_index(drop=True)
    df.to_csv(DATA_DIR / f"{symbol}_3y_4h.csv", index=False)
    return df


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    df["ema8"]   = c.ewm(span=8,  adjust=False).mean()
    df["ema13"]  = c.ewm(span=13, adjust=False).mean()
    df["ema20"]  = c.ewm(span=20, adjust=False).mean()
    df["ema21"]  = c.ewm(span=21, adjust=False).mean()
    df["ema34"]  = c.ewm(span=34, adjust=False).mean()
    df["ema50"]  = c.ewm(span=50, adjust=False).mean()
    df["ema55"]  = c.ewm(span=55, adjust=False).mean()
    df["ema200"] = c.ewm(span=200,adjust=False).mean()
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    df["atr14"]     = tr.rolling(14).mean()
    df["atr22"]     = tr.rolling(22).mean()
    df["atr_sma50"] = df["atr14"].rolling(50).mean()
    df["atr_sma100"]= df["atr14"].rolling(100).mean()
    df["atr_expand"]= df["atr14"] > df["atr_sma50"] * 1.5
    df["atr_compress"]=df["atr14"] < df["atr_sma100"] * 0.75
    up = h.diff(); dn = -l.diff()
    dm_p = np.where((up > dn) & (up > 0), up.values, 0.0)
    dm_m = np.where((dn > up) & (dn > 0), dn.values, 0.0)
    atr_s = tr.rolling(14).sum()
    di_p = 100 * pd.Series(dm_p, index=df.index).rolling(14).sum() / (atr_s + 1e-9)
    di_m = 100 * pd.Series(dm_m, index=df.index).rolling(14).sum() / (atr_s + 1e-9)
    df["di_p"] = di_p; df["di_m"] = di_m
    dx = (100 * (di_p - di_m).abs() / (di_p + di_m + 1e-9)).fillna(0)
    df["adx"] = dx.rolling(14).mean()
    delta = c.diff()
    g = delta.clip(lower=0).rolling(14).mean()
    ls = (-delta).clip(lower=0).rolling(14).mean()
    df["rsi"] = 100 - (100 / (1 + g / (ls + 1e-9)))
    rsi_s = (df["rsi"] - df["rsi"].rolling(14).min()) / (df["rsi"].rolling(14).max() - df["rsi"].rolling(14).min() + 1e-9)
    df["stoch_rsi_k"] = rsi_s.rolling(3).mean() * 100
    df["stoch_rsi_d"] = df["stoch_rsi_k"].rolling(3).mean()
    stk_raw = 100 * (c - l.rolling(14).min()) / (h.rolling(14).max() - l.rolling(14).min() + 1e-9)
    df["stoch_k"] = stk_raw.rolling(3).mean()
    df["stoch_d"] = df["stoch_k"].rolling(3).mean()
    tp_col = (h + l + c) / 3
    df["cci20"] = (tp_col - tp_col.rolling(20).mean()) / (0.015 * tp_col.rolling(20).std() + 1e-9)
    df["don20_hi"] = h.rolling(20).max(); df["don20_lo"] = l.rolling(20).min()
    df["don14_hi"] = h.rolling(14).max(); df["don14_lo"] = l.rolling(14).min()
    df["don10_hi"] = h.rolling(10).max(); df["don10_lo"] = l.rolling(10).min()
    obv = (np.sign(c.diff()) * v).fillna(0).cumsum()
    df["obv"] = obv; df["obv_ema11"] = obv.ewm(span=11, adjust=False).mean()
    df["vol_sma20"] = v.rolling(20).mean()
    df["aroon_up14"] = 100*(14 - h.rolling(15).apply(lambda x:(len(x)-1)-int(np.argmax(x)),raw=True))/14
    df["aroon_dn14"] = 100*(14 - l.rolling(15).apply(lambda x:(len(x)-1)-int(np.argmin(x)),raw=True))/14
    df["aroon_osc14"]= df["aroon_up14"] - df["aroon_dn14"]
    df["aroon_up25"] = 100*(25 - h.rolling(26).apply(lambda x:(len(x)-1)-int(np.argmax(x)),raw=True))/25
    df["aroon_dn25"] = 100*(25 - l.rolling(26).apply(lambda x:(len(x)-1)-int(np.argmin(x)),raw=True))/25
    df["aroon_osc25"]= df["aroon_up25"] - df["aroon_dn25"]
    bb_mid = c.rolling(20).mean(); bb_std = c.rolling(20).std()
    df["bb_upper"] = bb_mid + 2*bb_std; df["bb_lower"] = bb_mid - 2*bb_std
    df["bb_mid"]   = bb_mid
    df["bb_pct_b"] = (c - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"] + 1e-9)
    ema12 = c.ewm(span=12, adjust=False).mean(); ema26 = c.ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26; df["macd_sig"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_sig"]
    e1 = c.ewm(span=14, adjust=False).mean()
    e2 = e1.ewm(span=14, adjust=False).mean()
    e3 = e2.ewm(span=14, adjust=False).mean()
    trix = (e3 - e3.shift(1)) / (e3.shift(1) + 1e-9) * 10000
    df["trix"] = trix; df["trix_sig"] = trix.ewm(span=9, adjust=False).mean()
    wr_hh = h.rolling(14).max(); wr_ll = l.rolling(14).min()
    df["wr14"] = (wr_hh - c) / (wr_hh - wr_ll + 1e-9) * -100
    kc_mid = c.ewm(span=20, adjust=False).mean()
    df["kc_upper"] = kc_mid + 2.0*df["atr14"]; df["kc_lower"] = kc_mid - 2.0*df["atr14"]
    df["kc_upper14"]= kc_mid + 1.4*df["atr14"]; df["kc_lower14"]= kc_mid - 1.4*df["atr14"]
    vwap_w = c.rolling(20).mean()
    vwap_dev = c.rolling(20).std() * 2.0
    df["vwap_upper"] = vwap_w + vwap_dev; df["vwap_lower"] = vwap_w - vwap_dev
    df["vwap_val"]   = vwap_w
    ha_c = (df["open"] + h + l + c) / 4
    ha_o = ha_c.copy()
    for i in range(1, len(df)):
        ha_o.iloc[i] = (ha_o.iloc[i-1] + ha_c.iloc[i-1]) / 2
    df["ha_green"] = ha_c > ha_o; df["ha_red"] = ha_c < ha_o
    psar = c.copy()
    df["psar_bull"] = c > c.shift(1)
    hull_fast_raw = 2 * c.rolling(5).mean() - c.rolling(9).mean()
    hull_slow_raw = 2 * c.rolling(10).mean() - c.rolling(21).mean()
    df["hull_fast"] = hull_fast_raw.rolling(3).mean()
    df["hull_slow"] = hull_slow_raw.rolling(4).mean()
    vm_p = (h - l.shift()).abs(); vm_m = (l - h.shift()).abs()
    df["vi_p14"] = vm_p.rolling(14).sum() / (tr.rolling(14).sum() + 1e-9)
    df["vi_m14"] = vm_m.rolling(14).sum() / (tr.rolling(14).sum() + 1e-9)
    ch_d = c.diff()
    su = ch_d.clip(lower=0).rolling(14).sum(); sd = (-ch_d).clip(lower=0).rolling(14).sum()
    df["cmo14"] = 100 * (su - sd) / (su + sd + 1e-9)
    roc11 = c.pct_change(11)*100; roc14 = c.pct_change(14)*100
    rc = roc11 + roc14
    wts = np.arange(1, 11)
    df["coppock"] = rc.rolling(10).apply(lambda x: np.dot(x, wts)/wts.sum(), raw=True)
    df["swing_hi"] = (h > h.shift(1)) & (h > h.shift(-1))
    df["swing_lo"] = (l < l.shift(1)) & (l < l.shift(-1))
    # Supertrend approximation via ATR bands
    hl2 = (h + l) / 2
    df["st_upper"] = hl2 + 3.0 * df["atr14"]
    df["st_lower"] = hl2 - 3.0 * df["atr14"]
    st_bull = c > df["st_lower"].shift(1)
    df["st_bull"] = st_bull
    df["st_flip_up"] = st_bull & ~st_bull.shift(1).fillna(False)
    df["st_flip_dn"] = ~st_bull & st_bull.shift(1).fillna(True)
    # Ichimoku
    tenkan = (h.rolling(9).max() + l.rolling(9).min()) / 2
    kijun  = (h.rolling(26).max() + l.rolling(26).min()) / 2
    sA = (tenkan + kijun) / 2
    sB = (h.rolling(52).max() + l.rolling(52).min()) / 2
    df["cloud_top"] = pd.concat([sA.shift(26), sB.shift(26)], axis=1).max(axis=1)
    df["cloud_bot"] = pd.concat([sA.shift(26), sB.shift(26)], axis=1).min(axis=1)
    df["tenkan"] = tenkan; df["kijun"] = kijun
    df["chan_cross_bull"] = (tenkan > kijun) & (tenkan.shift(1) <= kijun.shift(1))
    df["chan_cross_bear"] = (tenkan < kijun) & (tenkan.shift(1) >= kijun.shift(1))
    # Chandelier
    df["chandelier_long"]  = h.rolling(22).max() - 3.0 * df["atr22"]
    df["chandelier_short"] = l.rolling(22).min() + 3.0 * df["atr22"]
    return df


def backtest_oos(df, ls, ss, sl_pct, tp_pct, trail_pct, lx=None, sx=None):
    n = len(df); oos_s = int(n * 0.70)
    def _bt(seg):
        trades, eq, pos = [], NOTIONAL, None
        td, cl, cd, de, pd_ = 0, 0, 0, eq, None
        for i in range(len(seg)):
            row = seg.iloc[i]
            o, h2, l2, c2 = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
            day = str(row["timestamp"])[:10]
            if day != pd_:
                td = 0; de = eq; pd_ = day
            if cd > 0: cd -= 1
            dp = (eq - de) / (de + 1e-9)
            can = td < 3 and cd == 0 and dp > -0.03
            oi = seg.index[i]
            if pos:
                side, ep, slp, tpp, tr = pos["s"], pos["e"], pos["sl"], pos["tp"], pos["tr"]
                closed, xp = False, None
                if side == "L":
                    tr = max(tr, h2*(1-trail_pct)); pos["tr"] = tr
                    if l2 <= slp: xp=slp; closed=True
                    elif h2 >= tpp: xp=tpp; closed=True
                    elif l2 <= tr: xp=tr; closed=True
                    elif lx is not None and bool(lx.iloc[oi]): xp=c2; closed=True
                else:
                    tr = min(tr, l2*(1+trail_pct)); pos["tr"] = tr
                    if h2 >= slp: xp=slp; closed=True
                    elif l2 <= tpp: xp=tpp; closed=True
                    elif h2 >= tr: xp=tr; closed=True
                    elif sx is not None and bool(sx.iloc[oi]): xp=c2; closed=True
                if closed and xp:
                    pnl = NOTIONAL*(xp-ep)/ep - NOTIONAL*COMMISSION - xp*COMMISSION if side=="L" else NOTIONAL*(ep-xp)/ep - NOTIONAL*COMMISSION - xp*COMMISSION
                    eq += pnl; td += 1
                    cl = (cl+1) if pnl < 0 else 0
                    if cl >= 3: cd=6; cl=0
                    trades.append(pnl); pos = None; continue
            if pos is None and can:
                dl = bool(ls.iloc[oi]); ds = bool(ss.iloc[oi])
                if dl:
                    pos = {"s":"L","e":o,"sl":o*(1-sl_pct),"tp":o*(1+tp_pct),"tr":o*(1-trail_pct)}
                elif ds:
                    pos = {"s":"S","e":o,"sl":o*(1+sl_pct),"tp":o*(1-tp_pct),"tr":o*(1+trail_pct)}
        if not trades: return {"pf":0,"wr":0,"roi_day":0,"max_dd":0,"trades":0}
        wins = [p for p in trades if p > 0]
        gw = sum(wins) or 0; gl = abs(sum(p for p in trades if p < 0))
        pf = gw / (gl+1e-9); wr = len(wins)/len(trades)*100
        eq2=NOTIONAL; pk=NOTIONAL; mdd=0
        for p in trades:
            eq2+=p; pk=max(pk,eq2); mdd=max(mdd,(pk-eq2)/pk*100)
        days = max((seg["timestamp"].iloc[-1]-seg["timestamp"].iloc[0]).days, 1)
        roi_day = (eq2-NOTIONAL)/NOTIONAL*100/days
        return {"pf":round(pf,2),"wr":round(wr,1),"roi_day":round(roi_day,4),"max_dd":round(mdd,2),"trades":len(trades)}
    is_r  = _bt(df.iloc[:oos_s].copy().reset_index())
    oos_r = _bt(df.iloc[oos_s:].copy().reset_index())
    return is_r, oos_r


# ─────────────────────────────────────────────────────────────────────────────
# SIGNAL FUNCTIONS  (all return: long_entry, short_entry, sl, tp, trail, lx, sx)
# ─────────────────────────────────────────────────────────────────────────────

def _can_trade_filter(df):
    return df["atr14"] < df["atr_sma100"] * 2

def s_donchian_trend(df):
    c = df["close"]
    le = (c > df["don20_hi"].shift(1)) & (c > df["ema50"]) & (df["adx"] > 20) & _can_trade_filter(df)
    se = (c < df["don20_lo"].shift(1)) & (c < df["ema50"]) & (df["adx"] > 20) & _can_trade_filter(df)
    lx = c < df["don10_lo"].shift(1); sx = c > df["don10_hi"].shift(1)
    return le, se, 0.02, 0.12, 0.04, lx, sx

def s_cci_trend(df):
    c = df["close"]; cci = df["cci20"]
    le = (cci > 100) & (cci.shift(1) <= 100) & (c > df["ema50"]) & (df["adx"] > 20)
    se = (cci < -100) & (cci.shift(1) >= -100) & (c < df["ema50"]) & (df["adx"] > 20)
    lx = cci < 0; sx = cci > 0
    return le, se, 0.015, 0.12, 0.04, lx, sx

def s_williams_r(df):
    c = df["close"]; wr = df["wr14"]
    le = (wr > -80) & (wr.shift(1) <= -80) & (c > df["ema50"]) & (df["adx"] > 18)
    se = (wr < -20) & (wr.shift(1) >= -20) & (c < df["ema50"]) & (df["adx"] > 18)
    lx = wr < -70; sx = wr > -30
    return le, se, 0.015, 0.12, 0.04, lx, sx

def s_keltner_breakout(df):
    c = df["close"]
    le = (c > df["kc_upper"]) & (c.shift(1) <= df["kc_upper"].shift(1)) & (c > df["ema50"]) & (df["adx"] > 20)
    se = (c < df["kc_lower"]) & (c.shift(1) >= df["kc_lower"].shift(1)) & (c < df["ema50"]) & (df["adx"] > 20)
    lx = c < df["ema50"]; sx = c > df["ema50"]
    return le, se, 0.015, 0.12, 0.04, lx, sx

def s_trix_signal(df):
    c = df["close"]
    le = (df["trix"] > df["trix_sig"]) & (df["trix"].shift(1) <= df["trix_sig"].shift(1)) & (df["trix"] > 0) & (c > df["ema50"]) & (df["adx"] > 18)
    se = (df["trix"] < df["trix_sig"]) & (df["trix"].shift(1) >= df["trix_sig"].shift(1)) & (df["trix"] < 0) & (c < df["ema50"]) & (df["adx"] > 18)
    lx = df["trix"] < 0; sx = df["trix"] > 0
    return le, se, 0.015, 0.12, 0.04, lx, sx

def s_aroon_trend(df):
    c = df["close"]
    le = (df["aroon_up14"] > df["aroon_dn14"]) & (df["aroon_up14"].shift(1) <= df["aroon_dn14"].shift(1)) & (df["aroon_up14"] > 70) & (c > df["ema50"]) & (df["adx"] > 18)
    se = (df["aroon_up14"] < df["aroon_dn14"]) & (df["aroon_up14"].shift(1) >= df["aroon_dn14"].shift(1)) & (df["aroon_dn14"] > 70) & (c < df["ema50"]) & (df["adx"] > 18)
    lx = df["aroon_up14"] < df["aroon_dn14"]; sx = df["aroon_up14"] > df["aroon_dn14"]
    return le, se, 0.015, 0.12, 0.04, lx, sx

def s_ema_ribbon(df):
    c = df["close"]
    bull = (df["ema8"]>df["ema13"]) & (df["ema13"]>df["ema21"]) & (df["ema21"]>df["ema34"]) & (df["ema34"]>df["ema55"])
    bear = (df["ema8"]<df["ema13"]) & (df["ema13"]<df["ema21"]) & (df["ema21"]<df["ema34"]) & (df["ema34"]<df["ema55"])
    pb_l = bull & (df["low"] <= df["ema8"]*1.002) & (c > df["ema8"]) & (c > df["open"])
    pb_s = bear & (df["high"] >= df["ema8"]*0.998) & (c < df["ema8"]) & (c < df["open"])
    nf_l = bull & ~bull.shift(1).fillna(False)
    nf_s = bear & ~bear.shift(1).fillna(True)
    le = (pb_l | nf_l) & (df["adx"] > 18); se = (pb_s | nf_s) & (df["adx"] > 18)
    lx = ~bull; sx = ~bear
    return le, se, 0.015, 0.12, 0.04, lx, sx

def s_supertrend_cci(df):
    c = df["close"]
    le = (df["st_flip_up"] | (df["st_bull"] & (df["cci20"] > 100) & (df["cci20"].shift(1) <= 100))) & (c > df["ema50"]) & (df["adx"] > 20)
    se = (df["st_flip_dn"] | (~df["st_bull"] & (df["cci20"] < -100) & (df["cci20"].shift(1) >= -100))) & (c < df["ema50"]) & (df["adx"] > 20)
    lx = ~df["st_bull"]; sx = df["st_bull"]
    return le, se, 0.015, 0.12, 0.04, lx, sx

def s_stoch_rsi_trend(df):
    c = df["close"]
    le = (df["stoch_rsi_k"] > df["stoch_rsi_d"]) & (df["stoch_rsi_k"].shift(1) <= df["stoch_rsi_d"].shift(1)) & (df["stoch_rsi_k"] < 30) & (c > df["ema50"]) & (c > df["ema200"]) & (df["adx"] > 18)
    se = (df["stoch_rsi_k"] < df["stoch_rsi_d"]) & (df["stoch_rsi_k"].shift(1) >= df["stoch_rsi_d"].shift(1)) & (df["stoch_rsi_k"] > 70) & (c < df["ema50"]) & (c < df["ema200"]) & (df["adx"] > 18)
    lx = df["stoch_rsi_k"] > 80; sx = df["stoch_rsi_k"] < 20
    return le, se, 0.015, 0.12, 0.04, lx, sx

def s_macd_zero_cross(df):
    c = df["close"]
    le_s = (df["macd"] > 0) & (df["macd"].shift(1) <= 0) & (df["macd_hist"] > df["macd_hist"].shift(1)) & (c > df["ema50"]) & (df["adx"] > 25) & (df["volume"] > df["vol_sma20"]*1.2)
    le_m = (df["macd"] > 0) & (df["macd"].shift(1) <= 0) & (c > df["ema50"]) & (df["adx"] > 18)
    se_s = (df["macd"] < 0) & (df["macd"].shift(1) >= 0) & (df["macd_hist"] < df["macd_hist"].shift(1)) & (c < df["ema50"]) & (df["adx"] > 25) & (df["volume"] > df["vol_sma20"]*1.2)
    se_m = (df["macd"] < 0) & (df["macd"].shift(1) >= 0) & (c < df["ema50"]) & (df["adx"] > 18)
    le = le_s | le_m; se = se_s | se_m
    lx = df["macd"] < 0; sx = df["macd"] > 0
    return le, se, 0.015, 0.12, 0.04, lx, sx

def s_triple_confirm(df):
    c = df["close"]
    dbu = c > df["don20_hi"].shift(1); dbd = c < df["don20_lo"].shift(1)
    le = dbu & (df["cci20"] > 100) & df["st_bull"] & (c > df["ema50"]) & (df["adx"] > 20)
    se = dbd & (df["cci20"] < -100) & ~df["st_bull"] & (c < df["ema50"]) & (df["adx"] > 20)
    lx = ~df["st_bull"] | (df["cci20"] < 0); sx = df["st_bull"] | (df["cci20"] > 0)
    return le, se, 0.015, 0.14, 0.045, lx, sx

def s_ensemble_fusion(df):
    c = df["close"]
    ich_l = df["chan_cross_bull"] & (c > df["cloud_top"])
    ich_s = df["chan_cross_bear"] & (c < df["cloud_bot"])
    squeeze_l = (df["bb_pct_b"] > 0.8) & (df["macd_hist"] > 0) & (c > df["ema50"])
    squeeze_s = (df["bb_pct_b"] < 0.2) & (df["macd_hist"] < 0) & (c < df["ema50"])
    mom_l = (df["ema8"] > df["ema21"]) & (df["ema8"].shift(1) <= df["ema21"].shift(1)) & (df["adx"] > 20)
    mom_s = (df["ema8"] < df["ema21"]) & (df["ema8"].shift(1) >= df["ema21"].shift(1)) & (df["adx"] > 20)
    don_l = c > df["don20_hi"].shift(1); don_s = c < df["don20_lo"].shift(1)
    votes_l = ich_l.astype(int) + squeeze_l.astype(int) + mom_l.astype(int) + don_l.astype(int)
    votes_s = ich_s.astype(int) + squeeze_s.astype(int) + mom_s.astype(int) + don_s.astype(int)
    le = (votes_l >= 2) & (df["adx"] > 18); se = (votes_s >= 2) & (df["adx"] > 18)
    lx = votes_l < 1; sx = votes_s < 1
    return le, se, 0.015, 0.12, 0.04, lx, sx

def s_vwap_reversion(df):
    c = df["close"]
    le = (c < df["vwap_lower"]) & (df["rsi"] < 35) & (df["rsi"] > df["rsi"].shift(1))
    se = (c > df["vwap_upper"]) & (df["rsi"] > 65) & (df["rsi"] < df["rsi"].shift(1))
    lx = c > df["vwap_val"]; sx = c < df["vwap_val"]
    return le, se, 0.015, 0.08, 0.03, lx, sx

def s_breakout_retest(df):
    c, h, l = df["close"], df["high"], df["low"]
    sh = h.rolling(20).max(); sl_l = l.rolling(20).min()
    broke_up = (c > sh.shift(1)) & (c.shift(1) <= sh.shift(2))
    broke_dn = (c < sl_l.shift(1)) & (c.shift(1) >= sl_l.shift(2))
    retest_l = broke_up.shift(1).fillna(False) | broke_up.shift(2).fillna(False) | broke_up.shift(3).fillna(False)
    retest_s = broke_dn.shift(1).fillna(False) | broke_dn.shift(2).fillna(False) | broke_dn.shift(3).fillna(False)
    le = retest_l & (c > sh.shift(1)*0.99) & (df["adx"] > 18)
    se = retest_s & (c < sl_l.shift(1)*1.01) & (df["adx"] > 18)
    lx = c < sl_l.shift(1); sx = c > sh.shift(1)
    return le, se, 0.015, 0.10, 0.035, lx, sx

def s_rsi_divergence(df):
    c = df["close"]; rsi = df["rsi"]
    pll = (c < c.shift(5)) & (rsi > rsi.shift(5)) & (rsi < 40)
    phh = (c > c.shift(5)) & (rsi < rsi.shift(5)) & (rsi > 60)
    le = pll & (df["macd"] > df["macd_sig"]) & (df["adx"] > 15)
    se = phh & (df["macd"] < df["macd_sig"]) & (df["adx"] > 15)
    lx = df["macd"] < df["macd_sig"]; sx = df["macd"] > df["macd_sig"]
    return le, se, 0.015, 0.10, 0.035, lx, sx

def s_ha_trend(df):
    c = df["close"]
    consec_red = df["ha_red"] & df["ha_red"].shift(1) & df["ha_red"].shift(2)
    consec_grn = df["ha_green"] & df["ha_green"].shift(1) & df["ha_green"].shift(2)
    le = df["ha_green"] & consec_red.shift(1) & (c > df["ema50"]) & (df["adx"] > 18)
    se = df["ha_red"]   & consec_grn.shift(1) & (c < df["ema50"]) & (df["adx"] > 18)
    lx = df["ha_red"].rolling(2).sum() >= 2
    sx = df["ha_green"].rolling(2).sum() >= 2
    return le, se, 0.015, 0.10, 0.035, lx, sx

def s_psar_trend(df):
    c = df["close"]
    pb = df["st_flip_up"]  # PSAR approx via ST flip
    pbe = df["st_flip_dn"]
    le = pb & (c > df["ema50"]) & (df["adx"] > 18) & (df["rsi"] < 72)
    se = pbe & (c < df["ema50"]) & (df["adx"] > 18) & (df["rsi"] > 28)
    lx = ~df["st_bull"]; sx = df["st_bull"]
    return le, se, 0.015, 0.12, 0.04, lx, sx

def s_adx_di_cross(df):
    c = df["close"]
    xup = (df["di_p"] > df["di_m"]) & (df["di_p"].shift(1) <= df["di_m"].shift(1))
    xdn = (df["di_p"] < df["di_m"]) & (df["di_p"].shift(1) >= df["di_m"].shift(1))
    adx_rising = (df["adx"] > df["adx"].shift(1)) & (df["adx"] > df["adx"].shift(2))
    le = xup & adx_rising & (df["adx"] > 20) & (c > df["ema200"])
    se = xdn & adx_rising & (df["adx"] > 20) & (c < df["ema200"])
    lx = df["di_p"] < df["di_m"]; sx = df["di_p"] > df["di_m"]
    return le, se, 0.015, 0.12, 0.04, lx, sx

def s_cci_supertrend_donchian(df):
    c = df["close"]
    le = (c > df["don20_hi"].shift(1)) & (df["cci20"] > 100) & df["st_bull"] & (c > df["ema50"]) & (df["adx"] > 20)
    se = (c < df["don20_lo"].shift(1)) & (df["cci20"] < -100) & ~df["st_bull"] & (c < df["ema50"]) & (df["adx"] > 20)
    lx = ~df["st_bull"] | (df["cci20"] < 0); sx = df["st_bull"] | (df["cci20"] > 0)
    return le, se, 0.015, 0.14, 0.045, lx, sx

def s_chandelier_sar(df):
    c = df["close"]; h, l = df["high"], df["low"]
    le = (c > df["chandelier_long"]) & (c.shift(1) <= df["chandelier_long"].shift(1)) & df["st_bull"] & (c > df["ema50"]) & (df["adx"] > 20) & (df["volume"] > df["vol_sma20"]*1.25)
    se = (c < df["chandelier_short"]) & (c.shift(1) >= df["chandelier_short"].shift(1)) & ~df["st_bull"] & (c < df["ema50"]) & (df["adx"] > 20) & (df["volume"] > df["vol_sma20"]*1.25)
    lx = c < df["chandelier_long"]; sx = c > df["chandelier_short"]
    return le, se, 0.025, 0.20, 0.06, lx, sx

def s_ha_donchian(df):
    c = df["close"]
    grn3 = df["ha_green"] & df["ha_green"].shift(1).fillna(False)
    red3 = df["ha_red"]   & df["ha_red"].shift(1).fillna(False)
    le = grn3 & (c > df["don20_hi"].shift(1)) & (c > df["ema50"]) & (df["adx"] > 20)
    se = red3  & (c < df["don20_lo"].shift(1)) & (c < df["ema50"]) & (df["adx"] > 20)
    lx = df["ha_red"].rolling(2).sum() >= 2; sx = df["ha_green"].rolling(2).sum() >= 2
    return le, se, 0.015, 0.12, 0.04, lx, sx

def s_hull_ma(df):
    c = df["close"]
    le = (df["hull_fast"] > df["hull_slow"]) & (df["hull_fast"].shift(1) <= df["hull_slow"].shift(1)) & (df["volume"] > df["vol_sma20"]*1.5) & (df["adx"] > 18) & (df["rsi"] < 70)
    se = (df["hull_fast"] < df["hull_slow"]) & (df["hull_fast"].shift(1) >= df["hull_slow"].shift(1)) & (df["volume"] > df["vol_sma20"]*1.5) & (df["adx"] > 18) & (df["rsi"] > 30)
    lx = df["hull_fast"] < df["hull_slow"]; sx = df["hull_fast"] > df["hull_slow"]
    return le, se, 0.015, 0.12, 0.04, lx, sx

def s_keltner_rsi(df):
    c = df["close"]
    le = (c > df["kc_upper14"]) & (c.shift(1) <= df["kc_upper14"].shift(1)) & (df["rsi"] > 55) & (df["rsi"] < 75) & (c > df["ema50"]) & (df["volume"] > df["vol_sma20"]*1.4) & (df["adx"] > 18)
    se = (c < df["kc_lower14"]) & (c.shift(1) >= df["kc_lower14"].shift(1)) & (df["rsi"] < 45) & (df["rsi"] > 25) & (c < df["ema50"]) & (df["volume"] > df["vol_sma20"]*1.4) & (df["adx"] > 18)
    lx = c < df["kc_upper14"]*0.995; sx = c > df["kc_lower14"]*1.005
    return le, se, 0.015, 0.14, 0.045, lx, sx

def s_momentum_volatility(df):
    c = df["close"]
    le = df["atr_expand"] & (df["ema20"] > df["ema50"]) & (df["ema20"].shift(1) <= df["ema50"].shift(1)) & (c > df["ema200"]) & (df["adx"] > 20) & (df["rsi"] < 72)
    se = df["atr_expand"] & (df["ema20"] < df["ema50"]) & (df["ema20"].shift(1) >= df["ema50"].shift(1)) & (c < df["ema200"]) & (df["adx"] > 20) & (df["rsi"] > 28)
    lx = df["ema20"] < df["ema50"]; sx = df["ema20"] > df["ema50"]
    return le, se, 0.015, 0.14, 0.045, lx, sx

def s_stoch_dmi(df):
    c = df["close"]
    le = (df["stoch_k"] > df["stoch_d"]) & (df["stoch_k"].shift(1) <= df["stoch_d"].shift(1)) & (df["stoch_k"] < 40) & (df["di_p"] > df["di_m"]) & (c > df["ema50"]) & (df["volume"] > df["vol_sma20"]*1.3)
    se = (df["stoch_k"] < df["stoch_d"]) & (df["stoch_k"].shift(1) >= df["stoch_d"].shift(1)) & (df["stoch_k"] > 60) & (df["di_p"] < df["di_m"]) & (c < df["ema50"]) & (df["volume"] > df["vol_sma20"]*1.3)
    lx = df["stoch_k"] > 80; sx = df["stoch_k"] < 20
    return le, se, 0.015, 0.12, 0.04, lx, sx

def s_aroon_donchian(df):   # G15
    c = df["close"]
    le = (c > df["don20_hi"].shift(1)) & (df["aroon_up25"] > 70) & (df["aroon_osc25"] > 30) & (c > df["ema50"]) & (df["adx"] > 20) & (df["rsi"] > 35) & (df["rsi"] < 70) & (df["atr14"] < df["atr_sma100"]*2)
    se = (c < df["don20_lo"].shift(1)) & (df["aroon_dn25"] > 70) & (df["aroon_osc25"] < -30) & (c < df["ema50"]) & (df["adx"] > 20) & (df["rsi"] > 30) & (df["rsi"] < 65) & (df["atr14"] < df["atr_sma100"]*2)
    lx = (df["aroon_up25"] < df["aroon_dn25"]) | (c < df["ema50"]); sx = (df["aroon_up25"] > df["aroon_dn25"]) | (c > df["ema50"])
    return le, se, 0.02, 0.14, 0.045, lx, sx

def s_donchian_cci_confirm(df):  # G27
    c = df["close"]
    le = (c > df["don20_hi"].shift(1)) & (df["cci20"] > 100) & (c > df["ema50"]) & (df["adx"] > 20) & (df["atr14"] < df["atr_sma100"]*2)
    se = (c < df["don20_lo"].shift(1)) & (df["cci20"] < -100) & (c < df["ema50"]) & (df["adx"] > 20) & (df["atr14"] < df["atr_sma100"]*2)
    lx = (c < df["don10_lo"].shift(1)) | (df["cci20"] < 0) | (df["rsi"] > 80)
    sx = (c > df["don10_hi"].shift(1)) | (df["cci20"] > 0) | (df["rsi"] < 20)
    return le, se, 0.015, 0.12, 0.04, lx, sx

def s_donchian_short14(df): # G28
    c = df["close"]
    le = (c > df["don14_hi"].shift(1)) & (c > df["ema50"]) & (df["adx"] > 22) & (df["rsi"] > 40) & (df["rsi"] < 70) & (df["volume"] > df["vol_sma20"]*1.1)
    se = (c < df["don14_lo"].shift(1)) & (c < df["ema50"]) & (df["adx"] > 22) & (df["rsi"] > 30) & (df["rsi"] < 60) & (df["volume"] > df["vol_sma20"]*1.1)
    lx = c < df["don14_lo"].shift(1); sx = c > df["don14_hi"].shift(1)
    return le, se, 0.015, 0.10, 0.035, lx, sx

def s_cci_donchian_fusion(df):  # G45
    c = df["close"]; cci = df["cci20"]
    dbu = c > df["don20_hi"].shift(1); dbd = c < df["don20_lo"].shift(1)
    cb = (cci > 100) & (cci.shift(1) <= 100); cbe = (cci < -100) & (cci.shift(1) >= -100)
    dru = dbu | dbu.shift(1) | dbu.shift(2); drd = dbd | dbd.shift(1) | dbd.shift(2)
    cru = cb | cb.shift(1) | cb.shift(2);   crd = cbe | cbe.shift(1) | cbe.shift(2)
    vo = df["atr14"] < df["atr_sma100"]*2; vc = df["volume"] > df["vol_sma20"]*1.2
    ls = dru & cru & (c > df["ema50"]) & (df["adx"] > 25) & vc
    lm = (dbu & (cci > 0) & (df["adx"] > 20)) | (cb & (c > df["don20_hi"].shift(1)*0.99) & (df["adx"] > 20))
    ss2 = drd & crd & (c < df["ema50"]) & (df["adx"] > 25) & vc
    sm = (dbd & (cci < 0) & (df["adx"] > 20)) | (cbe & (c < df["don20_lo"].shift(1)*1.01) & (df["adx"] > 20))
    le = (ls | (lm & (c > df["ema50"]))) & vo; se = (ss2 | (sm & (c < df["ema50"]))) & vo
    lx = (cci < 0) & (c < df["don10_lo"].shift(1)); sx = (cci > 0) & (c > df["don10_hi"].shift(1))
    return le, se, 0.015, 0.12, 0.04, lx, sx

def s_obv_cci(df):  # G68
    c = df["close"]
    ocu = (df["obv"] > df["obv_ema11"]) & (df["obv"].shift(1) <= df["obv_ema11"].shift(1))
    ocd = (df["obv"] < df["obv_ema11"]) & (df["obv"].shift(1) >= df["obv_ema11"].shift(1))
    cb = (df["cci20"] > 100) & (df["cci20"].shift(1) <= 100); cbe = (df["cci20"] < -100) & (df["cci20"].shift(1) >= -100)
    oru = ocu | ocu.shift(1) | ocu.shift(2); ord2 = ocd | ocd.shift(1) | ocd.shift(2)
    cru = cb | cb.shift(1) | cb.shift(2);   crd = cbe | cbe.shift(1) | cbe.shift(2)
    le = oru & cru & (c > df["ema50"]) & (df["adx"] > 20)
    se = ord2 & crd & (c < df["ema50"]) & (df["adx"] > 20)
    lx = (df["obv"] < df["obv_ema11"]) | (df["cci20"] < 0); sx = (df["obv"] > df["obv_ema11"]) | (df["cci20"] > 0)
    return le, se, 0.015, 0.12, 0.04, lx, sx

def s_vortex_donchian(df):  # G88
    c = df["close"]
    vcu = (df["vi_p14"] > df["vi_m14"]) & (df["vi_p14"].shift(1) <= df["vi_m14"].shift(1))
    vcd = (df["vi_p14"] < df["vi_m14"]) & (df["vi_p14"].shift(1) >= df["vi_m14"].shift(1))
    vru = vcu | vcu.shift(1) | vcu.shift(2); vrd = vcd | vcd.shift(1) | vcd.shift(2)
    le = vru & (c > df["don20_hi"].shift(1)) & (c > df["ema50"]) & (df["adx"] > 20) & (df["rsi"] < 72)
    se = vrd & (c < df["don20_lo"].shift(1)) & (c < df["ema50"]) & (df["adx"] > 20) & (df["rsi"] > 28)
    lx = df["vi_p14"] < df["vi_m14"]; sx = df["vi_p14"] > df["vi_m14"]
    return le, se, 0.015, 0.12, 0.04, lx, sx

def s_coppock_donchian(df):  # G89
    c = df["close"]
    ccu = (df["coppock"] > 0) & (df["coppock"].shift(1) <= 0)
    ccd = (df["coppock"] < 0) & (df["coppock"].shift(1) >= 0)
    cru = ccu | ccu.shift(1) | ccu.shift(2); crd = ccd | ccd.shift(1) | ccd.shift(2)
    le = cru & (c > df["don20_hi"].shift(1)) & (c > df["ema50"]) & (df["adx"] > 18)
    se = crd & (c < df["don20_lo"].shift(1)) & (c < df["ema50"]) & (df["adx"] > 18)
    lx = df["coppock"] < 0; sx = df["coppock"] > 0
    return le, se, 0.015, 0.12, 0.04, lx, sx

def s_atr_compression(df):  # G91
    c = df["close"]
    wc = df["atr_compress"].shift(1) | df["atr_compress"].shift(2) | df["atr_compress"].shift(3)
    le = wc & (c > df["don20_hi"].shift(1)) & (c > df["ema50"]) & (df["adx"] > 18) & (df["rsi"] < 72)
    se = wc & (c < df["don20_lo"].shift(1)) & (c < df["ema50"]) & (df["adx"] > 18) & (df["rsi"] > 28)
    lx = c < df["ema50"]; sx = c > df["ema50"]
    return le, se, 0.015, 0.12, 0.04, lx, sx

def s_pivot_reclaim(df):  # G94
    c, h, l = df["close"], df["high"], df["low"]
    phi = h.rolling(5).max().shift(1); plo = l.rolling(5).min().shift(1)
    rup = (c > phi) & (c.shift(1) <= phi.shift(1)) & (df["volume"] > df["vol_sma20"]*1.3)
    rdn = (c < plo) & (c.shift(1) >= plo.shift(1)) & (df["volume"] > df["vol_sma20"]*1.3)
    le = rup & (df["adx"] > 20) & (df["rsi"] > 45) & (df["rsi"] < 72) & (c > df["ema50"])
    se = rdn & (df["adx"] > 20) & (df["rsi"] < 55) & (df["rsi"] > 28) & (c < df["ema50"])
    lx = c < plo; sx = c > phi
    return le, se, 0.015, 0.12, 0.04, lx, sx

def s_inside_bar(df):  # G95
    c, h, l = df["close"], df["high"], df["low"]
    mhi = h.shift(2); mlo = l.shift(2)
    ib = (h.shift(1) < mhi) & (l.shift(1) > mlo)
    le = ib & (c > mhi) & (df["adx"] > 20) & (c > df["ema50"]) & (df["volume"] > df["vol_sma20"]*1.2) & (df["rsi"] < 75)
    se = ib & (c < mlo) & (df["adx"] > 20) & (c < df["ema50"]) & (df["volume"] > df["vol_sma20"]*1.2) & (df["rsi"] > 25)
    lx = c < mlo; sx = c > mhi
    return le, se, 0.015, 0.12, 0.04, lx, sx

def s_chande_bb(df):  # G99
    c = df["close"]; cmo = df["cmo14"]
    cbu = (cmo > 50) & (cmo.shift(1) <= 50); cbe = (cmo < -50) & (cmo.shift(1) >= -50)
    le = cbu & (c > df["bb_mid"]) & (c > df["ema50"]) & (df["adx"] > 18) & (df["rsi"] < 72)
    se = cbe & (c < df["bb_mid"]) & (c < df["ema50"]) & (df["adx"] > 18) & (df["rsi"] > 28)
    lx = cmo < 0; sx = cmo > 0
    return le, se, 0.015, 0.12, 0.04, lx, sx

def s_hh_structure(df):  # G100
    c, h, l = df["close"], df["high"], df["low"]
    shi = h.where(df["swing_hi"]).ffill(); psh = h.where(df["swing_hi"]).ffill().shift(1)
    slo = l.where(df["swing_lo"]).ffill(); psl = l.where(df["swing_lo"]).ffill().shift(1)
    hh = shi > psh; hl = slo > psl; lh = shi < psh; ll = slo < psl
    up = hh & hl & (c > df["ema50"]) & (df["adx"] > 20)
    dn = lh & ll & (c < df["ema50"]) & (df["adx"] > 20)
    le = up & (c > df["don20_hi"].shift(1)) & (df["rsi"] < 72)
    se = dn & (c < df["don20_lo"].shift(1)) & (df["rsi"] > 28)
    lx = lh | (c < df["ema50"]); sx = hh | (c > df["ema50"])
    return le, se, 0.015, 0.12, 0.04, lx, sx

def s_donchian_volume_surge(df):  # G19
    c = df["close"]
    le = (c > df["don20_hi"].shift(1)) & (df["volume"] > df["vol_sma20"]*2.0) & (c > df["ema50"]) & (df["adx"] > 20) & (df["rsi"] < 75)
    se = (c < df["don20_lo"].shift(1)) & (df["volume"] > df["vol_sma20"]*2.0) & (c < df["ema50"]) & (df["adx"] > 20) & (df["rsi"] > 25)
    lx = (c < df["don10_lo"].shift(1)) | (df["rsi"] > 80); sx = (c > df["don10_hi"].shift(1)) | (df["rsi"] < 20)
    return le, se, 0.015, 0.12, 0.04, lx, sx

def s_bb_percentb_rsi(df):  # G90
    c = df["close"]; pb = df["bb_pct_b"]
    le = (pb > 0.8) & (pb.shift(1) <= 0.8) & (df["rsi"] > 55) & (df["rsi"] < 75) & (c > df["ema50"]) & (df["adx"] > 20)
    se = (pb < 0.2) & (pb.shift(1) >= 0.2) & (df["rsi"] < 45) & (df["rsi"] > 25) & (c < df["ema50"]) & (df["adx"] > 20)
    lx = (pb < 0.5) | (df["rsi"] > 80); sx = (pb > 0.5) | (df["rsi"] < 20)
    return le, se, 0.015, 0.10, 0.035, lx, sx

def s_rsi_div_macd(df):  # G92
    c = df["close"]; rsi = df["rsi"]
    pll = (c < c.shift(5)) & (rsi > rsi.shift(5)) & (rsi < 45)
    phh = (c > c.shift(5)) & (rsi < rsi.shift(5)) & (rsi > 55)
    le = pll & (df["macd"] > df["macd_sig"]) & (df["adx"] > 18) & (c > df["ema200"])
    se = phh & (df["macd"] < df["macd_sig"]) & (df["adx"] > 18) & (c < df["ema200"])
    lx = df["macd"] < df["macd_sig"]; sx = df["macd"] > df["macd_sig"]
    return le, se, 0.02, 0.12, 0.04, lx, sx


# ─── REGISTRY ─────────────────────────────────────────────────────────────────
REGISTRY = {
    # ── Garima pine/tv_first_3x-5x ──
    "35 Donchian Trend":         s_donchian_trend,
    "40 CCI Trend":              s_cci_trend,
    "31 Ensemble Fusion":        s_ensemble_fusion,
    "32 VWAP Reversion":         s_vwap_reversion,
    "33 Breakout Retest":        s_breakout_retest,
    "34 RSI Divergence":         s_rsi_divergence,
    "36 Heikin Ashi Trend":      s_ha_trend,
    "37 PSAR Trend":             s_psar_trend,
    "38 ADX DI Cross":           s_adx_di_cross,
    "41 Williams R":             s_williams_r,
    "42 KC Breakout":            s_keltner_breakout,
    "43 TRIX Signal":            s_trix_signal,
    "44 Aroon Trend":            s_aroon_trend,
    "45 CCI Donchian Fusion":    s_cci_donchian_fusion,
    "46 EMA Ribbon":             s_ema_ribbon,
    "47 Supertrend CCI":         s_supertrend_cci,
    "48 Stoch RSI Trend":        s_stoch_rsi_trend,
    "49 MACD Zero Cross":        s_macd_zero_cross,
    "50 Triple Confirm":         s_triple_confirm,
    # ── Garima pine_new ──
    "PN Aroon Donchian (G15)":   s_aroon_donchian,
    "PN CCI Supertrend Donchian":s_cci_supertrend_donchian,
    "PN Chandelier SAR Fusion":  s_chandelier_sar,
    "PN HA Donchian Fusion":     s_ha_donchian,
    "PN Hull MA Cross Volume":   s_hull_ma,
    "PN KC Breakout RSI":        s_keltner_rsi,
    "PN Momentum Volatility":    s_momentum_volatility,
    "PN Stochastic DMI Fusion":  s_stoch_dmi,
    "PN Donchian CCI Confirm(G27)":s_donchian_cci_confirm,
    # ── Group B (previously tested, now multi-asset) ──
    "GB Donchian Short14 (G28)": s_donchian_short14,
    "GB Donchian Vol Surge (G19)":s_donchian_volume_surge,
    "GB OBV CCI Cross (G68)":    s_obv_cci,
    # ── Group A (G88-G100) ──
    "GA Vortex Donchian (G88)":  s_vortex_donchian,
    "GA Coppock Donchian (G89)": s_coppock_donchian,
    "GA BB PercentB RSI (G90)":  s_bb_percentb_rsi,
    "GA ATR Compress (G91)":     s_atr_compression,
    "GA RSI Div MACD (G92)":     s_rsi_div_macd,
    "GA Pivot Reclaim (G94)":    s_pivot_reclaim,
    "GA Inside Bar (G95)":       s_inside_bar,
    "GA Chande Momentum BB (G99)":s_chande_bb,
    "GA HigherHigh Struct (G100)":s_hh_structure,
}


def main():
    print("\n" + "="*110)
    print("  MEGA BACKTEST — All Strategies × All Assets | $500 | 0.06% | 30% OOS | 4H")
    print("="*110)

    dfs = {}
    print("Loading data...")
    for sym in ASSETS:
        df = load_ohlcv(sym)
        if not df.empty:
            dfs[sym] = add_indicators(df)
            print(f"  {sym}: {len(dfs[sym])} bars")

    all_results = []
    total = len(REGISTRY) * len(ASSETS)
    done  = 0

    for sname, fn in REGISTRY.items():
        for sym, df in dfs.items():
            done += 1
            try:
                ls, ss, sl, tp, trail, lx, sx = fn(df)
                is_r, oos_r = backtest_oos(df, ls, ss, sl, tp, trail, lx, sx)
            except Exception as e:
                continue
            oos_pf = oos_r["pf"]; oos_rd = oos_r["roi_day"]; oos_dd = oos_r["max_dd"]
            oos_t  = oos_r["trades"]; oos_wr = oos_r["wr"]
            if oos_t < 5: continue
            if oos_pf >= 1.20 and oos_rd > 0 and oos_dd < 15:
                verdict = "PASS"
            elif oos_pf >= 1.10:
                verdict = "WATCH"
            elif oos_pf >= 1.0:
                verdict = "BORDERLINE"
            else:
                verdict = "FAIL"
            all_results.append({
                "Strategy": sname, "Asset": sym,
                "OOS PF": oos_pf, "IS PF": is_r["pf"],
                "OOS WR%": oos_wr, "OOS Trades": oos_t,
                "ROI/day%": oos_rd, "Max DD%": oos_dd,
                "Verdict": verdict,
            })
        print(f"  [{done}/{total}] {sname} done", flush=True)

    # best per strategy (by OOS PF)
    best = {}
    for r in all_results:
        k = r["Strategy"]
        if k not in best or r["OOS PF"] > best[k]["OOS PF"]:
            best[k] = r

    ranked = sorted(best.values(), key=lambda x: -x["OOS PF"])

    print("\n" + "="*115)
    print(f"  {'#':<3} {'Strategy':<42} {'Asset':<10} {'OOS PF':>7} {'IS PF':>6} {'WR%':>5} {'Trd':>4} {'ROI/d%':>8} {'DD%':>6}  Verdict")
    print("-"*115)
    for i, r in enumerate(ranked[:50], 1):
        v = {"PASS":"✅ PASS","WATCH":"⚠️ WATCH","BORDERLINE":"〰 BORDERLINE","FAIL":"❌ FAIL"}.get(r["Verdict"], r["Verdict"])
        print(f"  {i:<3} {r['Strategy']:<42} {r['Asset']:<10} {r['OOS PF']:>7.2f} {r['IS PF']:>6.2f} "
              f"{r['OOS WR%']:>5.1f} {r['OOS Trades']:>4} {r['ROI/day%']:>8.4f} {r['Max DD%']:>6.1f}  {v}")

    passes = [r for r in ranked if r["Verdict"]=="PASS"]
    watches = [r for r in ranked if r["Verdict"]=="WATCH"]
    print(f"\n  PASS: {len(passes)}  WATCH: {len(watches)}  Total tested: {len(ranked)}")

    out = PROJECT_ROOT / "scripts" / "backtest_mega_all_results.csv"
    pd.DataFrame(all_results).sort_values("OOS PF", ascending=False).to_csv(out, index=False)
    print(f"  Full results → {out}")
    print("="*115)


if __name__ == "__main__":
    main()
