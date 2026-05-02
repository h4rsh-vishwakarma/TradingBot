#!/usr/bin/env python3
"""
backtest_r04_groups.py — Group B (G15,G19,G27,G28,G45,G68) + Group A (G88-G100) Python OOS
R-03 style: fixed $500 notional, 0.06% commission, 30% OOS, no lookahead.
can_trade gate: 3/day cap, 6-bar cooldown after 3 consec losses, -3% daily circuit breaker.
SL/TP: intrabar (high/low). Trail: peak tracking.
"""
from __future__ import annotations
import sys, os, json, time, urllib.request, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path("/home/ubuntu/tradingview_webhook_bot")
DATA_DIR     = PROJECT_ROOT / "storage" / "backtest_data"
OUTPUT_DIR   = PROJECT_ROOT / "scripts"

COMMISSION = 0.0006
NOTIONAL   = 500.0
OOS_RATIO  = 0.30


def load_ohlcv(symbol: str) -> pd.DataFrame:
    for tag in ["5y", "3y"]:
        f = DATA_DIR / f"{symbol}_{tag}_4h.csv"
        if f.exists():
            df = pd.read_csv(f)
            df.columns = [c.lower() for c in df.columns]
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            for c in ["open", "high", "low", "close", "volume"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            df = df.dropna(subset=["open", "high", "low", "close", "volume"])
            df = df.sort_values("timestamp").reset_index(drop=True)
            print(f"  [{symbol}] {len(df)} bars from {tag} cache")
            return df
    print(f"  [{symbol}] downloading 3y from Binance...")
    limit, rows = 1000, []
    end_ms = int(time.time() * 1000)
    target = 3 * 365 * 6
    while len(rows) < target:
        url = (f"https://api.binance.com/api/v3/klines"
               f"?symbol={symbol}&interval=4h&limit={limit}&endTime={end_ms}")
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                batch = json.loads(r.read())
        except Exception as e:
            print(f"  ERROR: {e}"); break
        if not batch:
            break
        rows = batch + rows
        end_ms = batch[0][0] - 1
        if len(batch) < limit:
            break
        time.sleep(0.15)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "qav", "num_trades", "tbbav", "tbqav", "ignore"])
    df = df[["timestamp", "open", "high", "low", "close", "volume"]].copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df = df.sort_values("timestamp").reset_index(drop=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(DATA_DIR / f"{symbol}_3y_4h.csv", index=False)
    print(f"  [{symbol}] {len(df)} bars downloaded")
    return df


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    df["ema50"]  = c.ewm(span=50, adjust=False).mean()
    df["ema200"] = c.ewm(span=200, adjust=False).mean()
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    df["atr14"]     = tr.rolling(14).mean()
    df["atr_sma100"] = df["atr14"].rolling(100).mean()
    up = h.diff(); dn = -l.diff()
    dm_p = np.where((up > dn) & (up > 0), up, 0.0)
    dm_m = np.where((dn > up) & (dn > 0), dn, 0.0)
    atr_s = tr.rolling(14).sum()
    di_p = 100 * pd.Series(dm_p, index=df.index).rolling(14).sum() / atr_s
    di_m = 100 * pd.Series(dm_m, index=df.index).rolling(14).sum() / atr_s
    dx   = (100 * (di_p - di_m).abs() / (di_p + di_m + 1e-9)).fillna(0)
    df["adx"] = dx.rolling(14).mean()
    delta = c.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta).clip(lower=0).rolling(14).mean()
    df["rsi"] = 100 - (100 / (1 + gain / (loss + 1e-9)))
    tp_col = (h + l + c) / 3
    df["cci20"] = (tp_col - tp_col.rolling(20).mean()) / (0.015 * tp_col.rolling(20).std() + 1e-9)
    df["don20_hi"] = h.rolling(20).max()
    df["don20_lo"] = l.rolling(20).min()
    df["don14_hi"] = h.rolling(14).max()
    df["don14_lo"] = l.rolling(14).min()
    df["don10_hi"] = h.rolling(10).max()
    df["don10_lo"] = l.rolling(10).min()
    obv = (np.sign(c.diff()) * v).fillna(0).cumsum()
    df["obv"]      = obv
    df["obv_ema11"] = obv.ewm(span=11, adjust=False).mean()
    df["vol_sma20"] = v.rolling(20).mean()
    df["aroon_up25"]  = 100 * (25 - h.rolling(26).apply(
        lambda x: (len(x) - 1) - int(np.argmax(x)), raw=True)) / 25
    df["aroon_dn25"]  = 100 * (25 - l.rolling(26).apply(
        lambda x: (len(x) - 1) - int(np.argmin(x)), raw=True)) / 25
    df["aroon_osc25"] = df["aroon_up25"] - df["aroon_dn25"]
    vm_p = (h - l.shift()).abs()
    vm_m = (l - h.shift()).abs()
    tr14s = tr.rolling(14).sum()
    df["vi_p14"] = vm_p.rolling(14).sum() / (tr14s + 1e-9)
    df["vi_m14"] = vm_m.rolling(14).sum() / (tr14s + 1e-9)
    bb_mid = c.rolling(20).mean()
    bb_std = c.rolling(20).std()
    df["bb_upper"] = bb_mid + 2 * bb_std
    df["bb_lower"] = bb_mid - 2 * bb_std
    df["bb_mid"]   = bb_mid
    df["bb_pct_b"] = (c - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"] + 1e-9)
    ch_delta = c.diff()
    su = ch_delta.clip(lower=0).rolling(14).sum()
    sd = (-ch_delta).clip(lower=0).rolling(14).sum()
    df["cmo14"] = 100 * (su - sd) / (su + sd + 1e-9)
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    df["macd"]     = ema12 - ema26
    df["macd_sig"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["swing_hi"] = (h > h.shift(1)) & (h > h.shift(-1))
    df["swing_lo"] = (l < l.shift(1)) & (l < l.shift(-1))
    df["atr_compressed"] = df["atr14"] < df["atr_sma100"] * 0.75
    roc11 = c.pct_change(11) * 100
    roc14 = c.pct_change(14) * 100
    rc = roc11 + roc14
    weights = np.arange(1, 11)
    df["coppock"] = rc.rolling(10).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)
    # DeMarker 14-period (EMA of dem_max / (dem_max + dem_min))
    dem_max = h.diff().clip(lower=0)
    dem_min = (-l.diff()).clip(lower=0)
    dema_p  = dem_max.ewm(span=14, adjust=False).mean()
    dema_m  = dem_min.ewm(span=14, adjust=False).mean()
    df["demarker14"] = dema_p / (dema_p + dema_m + 1e-9)
    # Supertrend ATR-10 Factor-3.0 (Wilder RMA, iterative)
    atr10  = tr.ewm(alpha=1/10, adjust=False).mean()
    hl2    = (h + l) / 2
    bu_raw = (hl2 + 3.0 * atr10).values
    bl_raw = (hl2 - 3.0 * atr10).values
    c_arr  = c.values
    n2 = len(df)
    st_up = np.zeros(n2); st_lo = np.zeros(n2); st_d = np.ones(n2, dtype=int)
    for i in range(n2):
        if i == 0:
            st_up[i] = bu_raw[i]; st_lo[i] = bl_raw[i]; st_d[i] = 1; continue
        st_up[i] = bu_raw[i] if (bu_raw[i] < st_up[i-1] or c_arr[i-1] > st_up[i-1]) else st_up[i-1]
        st_lo[i] = bl_raw[i] if (bl_raw[i] > st_lo[i-1] or c_arr[i-1] < st_lo[i-1]) else st_lo[i-1]
        st_d[i]  = (-1 if c_arr[i] > st_up[i] else 1) if st_d[i-1] == 1 else (1 if c_arr[i] < st_lo[i] else -1)
    df["st10_3_dir"] = pd.Series(st_d, index=df.index)
    return df


def run_oos(df: pd.DataFrame, long_sig: pd.Series, short_sig: pd.Series,
            sl_pct: float, tp_pct: float, trail_pct: float,
            long_exit: pd.Series = None, short_exit: pd.Series = None) -> dict:
    n = len(df)
    oos_start = int(n * 0.70)

    def _bt(seg: pd.DataFrame, label: str) -> dict:
        trades = []
        equity = NOTIONAL
        pos = None
        trades_today = 0
        consec_loss  = 0
        cooldown_cnt = 0
        day_open_eq  = equity
        prev_day     = None

        for i in range(len(seg)):
            row = seg.iloc[i]
            o, h2, l2, c2 = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
            ts = row["timestamp"]
            day = str(ts)[:10]
            if day != prev_day:
                trades_today = 0
                day_open_eq  = equity
                prev_day     = day
            if cooldown_cnt > 0:
                cooldown_cnt -= 1

            daily_pnl_pct = (equity - day_open_eq) / (day_open_eq + 1e-9)
            can_trade = (trades_today < 3 and cooldown_cnt == 0 and daily_pnl_pct > -0.03)
            orig_idx  = seg.index[i]

            if pos is not None:
                side   = pos["side"]
                sl_p   = pos["sl"]
                tp_p   = pos["tp"]
                trail  = pos["trail"]
                entry  = pos["entry"]
                closed = False
                exit_p = None

                if side == "long":
                    trail = max(trail, h2 * (1 - trail_pct))
                    pos["trail"] = trail
                    if l2 <= sl_p:
                        exit_p = sl_p; closed = True
                    elif h2 >= tp_p:
                        exit_p = tp_p; closed = True
                    elif l2 <= trail:
                        exit_p = trail; closed = True
                    elif long_exit is not None and bool(long_exit.iloc[orig_idx]):
                        exit_p = c2; closed = True
                else:
                    trail = min(trail, l2 * (1 + trail_pct))
                    pos["trail"] = trail
                    if h2 >= sl_p:
                        exit_p = sl_p; closed = True
                    elif l2 <= tp_p:
                        exit_p = tp_p; closed = True
                    elif h2 >= trail:
                        exit_p = trail; closed = True
                    elif short_exit is not None and bool(short_exit.iloc[orig_idx]):
                        exit_p = c2; closed = True

                if closed and exit_p:
                    fee_out = exit_p * COMMISSION
                    if side == "long":
                        pnl = NOTIONAL * (exit_p - entry) / entry - NOTIONAL * COMMISSION - fee_out
                    else:
                        pnl = NOTIONAL * (entry - exit_p) / entry - NOTIONAL * COMMISSION - fee_out
                    equity += pnl
                    trades_today += 1
                    if pnl < 0:
                        consec_loss += 1
                        if consec_loss >= 3:
                            cooldown_cnt = 6; consec_loss = 0
                    else:
                        consec_loss = 0
                    trades.append(pnl)
                    pos = None
                    continue

            if pos is None and can_trade:
                do_long  = bool(long_sig.iloc[orig_idx])
                do_short = bool(short_sig.iloc[orig_idx])
                if do_long:
                    ep = o
                    pos = {"side": "long",  "entry": ep,
                           "sl": ep * (1 - sl_pct), "tp": ep * (1 + tp_pct),
                           "trail": ep * (1 - trail_pct)}
                elif do_short:
                    ep = o
                    pos = {"side": "short", "entry": ep,
                           "sl": ep * (1 + sl_pct), "tp": ep * (1 - tp_pct),
                           "trail": ep * (1 + trail_pct)}

        if not trades:
            return {"pf": 0.0, "wr": 0.0, "roi_day": 0.0, "max_dd": 0.0, "trades": 0, "label": label}
        wins      = [p for p in trades if p > 0]
        gross_win = sum(wins) if wins else 0.0
        gross_los = abs(sum(p for p in trades if p < 0))
        pf  = gross_win / (gross_los + 1e-9)
        wr  = len(wins) / len(trades) * 100
        eq2 = NOTIONAL; pk = NOTIONAL; mdd = 0.0
        for p in trades:
            eq2 += p; pk = max(pk, eq2)
            dd = (pk - eq2) / pk * 100; mdd = max(mdd, dd)
        if len(seg) > 1:
            days = max((seg["timestamp"].iloc[-1] - seg["timestamp"].iloc[0]).days, 1)
        else:
            days = 1
        roi_day = ((eq2 - NOTIONAL) / NOTIONAL * 100) / days
        return {"pf": round(pf, 2), "wr": round(wr, 1), "roi_day": round(roi_day, 4),
                "max_dd": round(mdd, 2), "trades": len(trades), "label": label}

    is_seg  = df.iloc[:oos_start].copy().reset_index()
    oos_seg = df.iloc[oos_start:].copy().reset_index()
    return {"is": _bt(is_seg, "IS"), "oos": _bt(oos_seg, "OOS")}


# ── signal functions ──────────────────────────────────────────────────────────

def sig_g15(df):
    c = df["close"]
    bu = c > df["don20_hi"].shift(1); bd = c < df["don20_lo"].shift(1)
    sb = (df["aroon_up25"] > 70) & (df["aroon_osc25"] > 30)
    se = (df["aroon_dn25"] > 70) & (df["aroon_osc25"] < -30)
    vo = df["atr14"] < df["atr_sma100"] * 2
    vc = df["volume"] > df["vol_sma20"] * 1.2
    le = bu & sb & (c > df["ema50"]) & (df["adx"] > 20) & (df["rsi"] > 35) & (df["rsi"] < 70) & vo
    se2 = bd & se & (c < df["ema50"]) & (df["adx"] > 20) & (df["rsi"] > 30) & (df["rsi"] < 65) & vo
    lx = (df["aroon_up25"] < df["aroon_dn25"]) | (c < df["ema50"]) | (df["rsi"] > 75)
    sx = (df["aroon_up25"] > df["aroon_dn25"]) | (c > df["ema50"]) | (df["rsi"] < 25)
    return le, se2, 0.02, 0.14, 0.045, lx, sx


def sig_g19(df):
    c = df["close"]
    bu = c > df["don20_hi"].shift(1); bd = c < df["don20_lo"].shift(1)
    vs = df["volume"] > df["vol_sma20"] * 2.0
    le = bu & vs & (c > df["ema50"]) & (df["adx"] > 20) & (df["rsi"] < 75)
    se = bd & vs & (c < df["ema50"]) & (df["adx"] > 20) & (df["rsi"] > 25)
    lx = (c < df["don10_lo"].shift(1)) | (df["rsi"] > 80)
    sx = (c > df["don10_hi"].shift(1)) | (df["rsi"] < 20)
    return le, se, 0.015, 0.12, 0.04, lx, sx


def sig_g27(df):
    c = df["close"]
    bu = c > df["don20_hi"].shift(1); bd = c < df["don20_lo"].shift(1)
    vo = df["atr14"] < df["atr_sma100"] * 2
    le = bu & (df["cci20"] > 100) & (c > df["ema50"]) & (df["adx"] > 20) & vo
    se = bd & (df["cci20"] < -100) & (c < df["ema50"]) & (df["adx"] > 20) & vo
    lx = (c < df["don10_lo"].shift(1)) | (df["cci20"] < 0) | (df["rsi"] > 80)
    sx = (c > df["don10_hi"].shift(1)) | (df["cci20"] > 0) | (df["rsi"] < 20)
    return le, se, 0.015, 0.12, 0.04, lx, sx


def sig_g28(df):
    c = df["close"]
    bu = c > df["don14_hi"].shift(1); bd = c < df["don14_lo"].shift(1)
    tu = (c > df["ema50"]) & (df["adx"] > 22)
    td = (c < df["ema50"]) & (df["adx"] > 22)
    vc = df["volume"] > df["vol_sma20"] * 1.1
    le = bu & tu & (df["rsi"] > 40) & (df["rsi"] < 70) & vc
    se = bd & td & (df["rsi"] > 30) & (df["rsi"] < 60) & vc
    lx = c < df["don14_lo"].shift(1)
    sx = c > df["don14_hi"].shift(1)
    return le, se, 0.015, 0.10, 0.035, lx, sx


def sig_g45(df):
    c = df["close"]
    cci = df["cci20"]
    dhu = df["don20_hi"]; dlo = df["don20_lo"]
    dbu = c > dhu.shift(1); dbd = c < dlo.shift(1)
    cb  = (cci > 100) & (cci.shift(1) <= 100)
    cbe = (cci < -100) & (cci.shift(1) >= -100)
    dru = dbu | dbu.shift(1) | dbu.shift(2)
    drd = dbd | dbd.shift(1) | dbd.shift(2)
    cru = cb | cb.shift(1) | cb.shift(2)
    crd = cbe | cbe.shift(1) | cbe.shift(2)
    vo  = df["atr14"] < df["atr_sma100"] * 2
    vc  = df["volume"] > df["vol_sma20"] * 1.2
    ls  = dru & cru & (c > df["ema50"]) & (df["adx"] > 25) & vc
    lm  = (dbu & (cci > 0) & (df["adx"] > 20)) | (cb & (c > dhu.shift(1) * 0.99) & (df["adx"] > 20))
    ss  = drd & crd & (c < df["ema50"]) & (df["adx"] > 25) & vc
    sm  = (dbd & (cci < 0) & (df["adx"] > 20)) | (cbe & (c < dlo.shift(1) * 1.01) & (df["adx"] > 20))
    le  = (ls | (lm & (c > df["ema50"]))) & vo
    se  = (ss | (sm & (c < df["ema50"]))) & vo
    lx  = (cci < 0) & (c < df["don10_lo"].shift(1))
    sx  = (cci > 0) & (c > df["don10_hi"].shift(1))
    return le, se, 0.015, 0.12, 0.04, lx, sx


def sig_g68(df):
    c = df["close"]
    ocu = (df["obv"] > df["obv_ema11"]) & (df["obv"].shift(1) <= df["obv_ema11"].shift(1))
    ocd = (df["obv"] < df["obv_ema11"]) & (df["obv"].shift(1) >= df["obv_ema11"].shift(1))
    cb  = (df["cci20"] > 100) & (df["cci20"].shift(1) <= 100)
    cbe = (df["cci20"] < -100) & (df["cci20"].shift(1) >= -100)
    oru = ocu | ocu.shift(1) | ocu.shift(2)
    cru = cb  | cb.shift(1)  | cb.shift(2)
    ord2 = ocd | ocd.shift(1) | ocd.shift(2)
    crd = cbe | cbe.shift(1) | cbe.shift(2)
    le = oru & cru & (c > df["ema50"]) & (df["adx"] > 20)
    se = ord2 & crd & (c < df["ema50"]) & (df["adx"] > 20)
    lx = (df["obv"] < df["obv_ema11"]) | (df["cci20"] < 0)
    sx = (df["obv"] > df["obv_ema11"]) | (df["cci20"] > 0)
    return le, se, 0.015, 0.12, 0.04, lx, sx


def sig_g88(df):
    c = df["close"]
    vcu = (df["vi_p14"] > df["vi_m14"]) & (df["vi_p14"].shift(1) <= df["vi_m14"].shift(1))
    vcd = (df["vi_p14"] < df["vi_m14"]) & (df["vi_p14"].shift(1) >= df["vi_m14"].shift(1))
    dbu = c > df["don20_hi"].shift(1); dbd = c < df["don20_lo"].shift(1)
    vru = vcu | vcu.shift(1) | vcu.shift(2)
    vrd = vcd | vcd.shift(1) | vcd.shift(2)
    le = vru & dbu & (c > df["ema50"]) & (df["adx"] > 20) & (df["rsi"] < 72)
    se = vrd & dbd & (c < df["ema50"]) & (df["adx"] > 20) & (df["rsi"] > 28)
    lx = df["vi_p14"] < df["vi_m14"]
    sx = df["vi_p14"] > df["vi_m14"]
    return le, se, 0.015, 0.12, 0.04, lx, sx


def sig_g89(df):
    c = df["close"]
    ccu = (df["coppock"] > 0) & (df["coppock"].shift(1) <= 0)
    ccd = (df["coppock"] < 0) & (df["coppock"].shift(1) >= 0)
    dbu = c > df["don20_hi"].shift(1); dbd = c < df["don20_lo"].shift(1)
    cru = ccu | ccu.shift(1) | ccu.shift(2)
    crd = ccd | ccd.shift(1) | ccd.shift(2)
    le = cru & dbu & (c > df["ema50"]) & (df["adx"] > 18)
    se = crd & dbd & (c < df["ema50"]) & (df["adx"] > 18)
    lx = df["coppock"] < 0
    sx = df["coppock"] > 0
    return le, se, 0.015, 0.12, 0.04, lx, sx


def sig_g90(df):
    c = df["close"]; pb = df["bb_pct_b"]; rsi = df["rsi"]
    le = (pb > 0.8) & (pb.shift(1) <= 0.8) & (rsi > 55) & (rsi < 75) & (c > df["ema50"]) & (df["adx"] > 20)
    se = (pb < 0.2) & (pb.shift(1) >= 0.2) & (rsi < 45) & (rsi > 25) & (c < df["ema50"]) & (df["adx"] > 20)
    lx = (pb < 0.5) | (rsi > 80)
    sx = (pb > 0.5) | (rsi < 20)
    return le, se, 0.015, 0.10, 0.035, lx, sx


def sig_g91(df):
    c = df["close"]
    wc = df["atr_compressed"].shift(1) | df["atr_compressed"].shift(2) | df["atr_compressed"].shift(3)
    dbu = c > df["don20_hi"].shift(1); dbd = c < df["don20_lo"].shift(1)
    le = wc & dbu & (c > df["ema50"]) & (df["adx"] > 18) & (df["rsi"] < 72)
    se = wc & dbd & (c < df["ema50"]) & (df["adx"] > 18) & (df["rsi"] > 28)
    lx = (c < df["ema50"]) | (df["rsi"] > 78)
    sx = (c > df["ema50"]) | (df["rsi"] < 22)
    return le, se, 0.015, 0.12, 0.04, lx, sx


def sig_g92(df):
    c = df["close"]; rsi = df["rsi"]
    pll = (c < c.shift(5)) & (c.shift(1) > c.shift(2))
    rhl = (rsi > rsi.shift(5)) & (rsi.shift(1) < rsi.shift(2))
    bdiv = pll & rhl & (rsi < 45)
    phh = (c > c.shift(5)) & (c.shift(1) < c.shift(2))
    rlh = (rsi < rsi.shift(5)) & (rsi.shift(1) > rsi.shift(2))
    bediv = phh & rlh & (rsi > 55)
    mb = (df["macd"] > df["macd_sig"]) & (df["adx"] > 18)
    mbe = (df["macd"] < df["macd_sig"]) & (df["adx"] > 18)
    le = bdiv & mb & (c > df["ema200"])
    se = bediv & mbe & (c < df["ema200"])
    lx = df["macd"] < df["macd_sig"]
    sx = df["macd"] > df["macd_sig"]
    return le, se, 0.02, 0.12, 0.04, lx, sx


def sig_g94(df):
    c, h, l = df["close"], df["high"], df["low"]
    phi = h.rolling(5).max().shift(1)
    plo = l.rolling(5).min().shift(1)
    rup = (c > phi) & (c.shift(1) <= phi.shift(1)) & (df["volume"] > df["vol_sma20"] * 1.3)
    rdn = (c < plo) & (c.shift(1) >= plo.shift(1)) & (df["volume"] > df["vol_sma20"] * 1.3)
    le = rup & (df["adx"] > 20) & (df["rsi"] > 45) & (df["rsi"] < 72) & (c > df["ema50"])
    se = rdn & (df["adx"] > 20) & (df["rsi"] < 55) & (df["rsi"] > 28) & (c < df["ema50"])
    lx = c < plo
    sx = c > phi
    return le, se, 0.015, 0.12, 0.04, lx, sx


def sig_g95(df):
    c, h, l = df["close"], df["high"], df["low"]
    mhi = h.shift(2); mlo = l.shift(2)
    ib  = (h.shift(1) < mhi) & (l.shift(1) > mlo)
    le  = ib & (c > mhi) & (df["adx"] > 20) & (c > df["ema50"]) & (df["volume"] > df["vol_sma20"] * 1.2) & (df["rsi"] < 75)
    se  = ib & (c < mlo) & (df["adx"] > 20) & (c < df["ema50"]) & (df["volume"] > df["vol_sma20"] * 1.2) & (df["rsi"] > 25)
    lx  = c < mlo; sx = c > mhi
    return le, se, 0.015, 0.12, 0.04, lx, sx


def sig_g99(df):
    c = df["close"]; cmo = df["cmo14"]
    cbu = (cmo > 50) & (cmo.shift(1) <= 50)
    cbe = (cmo < -50) & (cmo.shift(1) >= -50)
    le  = cbu & (c > df["bb_mid"]) & (c > df["ema50"]) & (df["adx"] > 18) & (df["rsi"] < 72)
    se  = cbe & (c < df["bb_mid"]) & (c < df["ema50"]) & (df["adx"] > 18) & (df["rsi"] > 28)
    lx  = cmo < 0; sx = cmo > 0
    return le, se, 0.015, 0.12, 0.04, lx, sx


def sig_g100(df):
    c, h, l = df["close"], df["high"], df["low"]
    shi = h.where(df["swing_hi"]).ffill()
    psh = h.where(df["swing_hi"]).ffill().shift(1)
    slo = l.where(df["swing_lo"]).ffill()
    psl = l.where(df["swing_lo"]).ffill().shift(1)
    hh  = shi > psh; hl = slo > psl
    lh  = shi < psh; ll = slo < psl
    up  = hh & hl & (c > df["ema50"]) & (df["adx"] > 20)
    dn  = lh & ll & (c < df["ema50"]) & (df["adx"] > 20)
    le  = up & (c > df["don20_hi"].shift(1)) & (df["rsi"] < 72)
    se  = dn & (c < df["don20_lo"].shift(1)) & (df["rsi"] > 28)
    lx  = lh | (c < df["ema50"]); sx = hh | (c > df["ema50"])
    return le, se, 0.015, 0.12, 0.04, lx, sx


def sig_g83(df):
    c       = df["close"]
    dem     = df["demarker14"]
    don_mid = (df["don20_hi"] + df["don20_lo"]) / 2
    dem_xo  = (dem > 0.3) & (dem.shift(1) <= 0.3)   # crossover oversold line
    dem_xu  = (dem < 0.7) & (dem.shift(1) >= 0.7)   # crossunder overbought line
    no_sig  = pd.Series(False, index=df.index)
    le = dem_xo & (c > don_mid)
    lx = dem_xu & (c < don_mid)
    return le, no_sig, 0.02, 0.06, 0.015, lx, no_sig


def sig_g111(df):
    c       = df["close"]
    st_dir  = df["st10_3_dir"]               # -1 = bullish, 1 = bearish (Pine V5 convention)
    don_mid = (df["don20_hi"] + df["don20_lo"]) / 2
    flip_bull = (st_dir == -1) & (st_dir.shift(1) == 1)
    flip_bear = (st_dir == 1)  & (st_dir.shift(1) == -1)
    no_sig  = pd.Series(False, index=df.index)
    le = flip_bull & (c > don_mid)
    lx = flip_bear
    return le, no_sig, 0.015, 0.12, 0.04, lx, no_sig


TV_PF = {
    "G15 Aroon Donchian Breakout":   15.29,
    "G19 Donchian Volume Surge":     18.97,
    "G27 CCI Donchian Wide":          9.50,
    "G28 Donchian Short14":          10.13,
    "G45 CCI Donchian Fusion":       18.48,
    "G68 OBV CCI Cross":             11.00,
    "G88 Vortex Donchian":            6.11,
    "G89 Coppock Donchian":           5.75,
    "G90 BB PercentB RSI":            5.06,
    "G91 ATR Compression Breakout":  12.00,
    "G92 RSI Divergence MACD":       10.00,
    "G94 Pivot Point Reclaim":       14.90,
    "G95 Inside Bar Breakout":       13.00,
    "G99 Chande Momentum BB":        13.00,
    "G100 HigherHigh Structure":      8.71,
    "G83 DeMarker Donchian":         18.62,
    "G111 Supertrend Donchian":      10.07,
}

REGISTRY = {
    "G15 Aroon Donchian Breakout":  (sig_g15,  "ETHUSDT"),
    "G19 Donchian Volume Surge":    (sig_g19,  "ETHUSDT"),
    "G27 CCI Donchian Wide":        (sig_g27,  "LDOUSDT"),
    "G28 Donchian Short14":         (sig_g28,  "SUIUSDT"),
    "G45 CCI Donchian Fusion":      (sig_g45,  "ETHUSDT"),
    "G68 OBV CCI Cross":            (sig_g68,  "SUIUSDT"),
    "G88 Vortex Donchian":          (sig_g88,  "OPUSDT"),
    "G89 Coppock Donchian":         (sig_g89,  "OPUSDT"),
    "G90 BB PercentB RSI":          (sig_g90,  "OPUSDT"),
    "G91 ATR Compression Breakout": (sig_g91,  "LDOUSDT"),
    "G92 RSI Divergence MACD":      (sig_g92,  "LDOUSDT"),
    "G94 Pivot Point Reclaim":      (sig_g94,  "LDOUSDT"),
    "G95 Inside Bar Breakout":      (sig_g95,  "ETHUSDT"),
    "G99 Chande Momentum BB":       (sig_g99,  "ETHUSDT"),
    "G100 HigherHigh Structure":    (sig_g100, "SUIUSDT"),
    "G83 DeMarker Donchian":        (sig_g83,  "ETHUSDT"),
    "G111 Supertrend Donchian":     (sig_g111, "LINKUSDT"),
}

GROUP_B = {"G15","G19","G27","G28","G45","G68"}


def main():
    print("\n" + "=" * 100)
    print("  R-04 GROUP B + GROUP A — Python OOS | $500 fixed | 0.06% comm | 30% OOS")
    print("=" * 100)

    syms = set(sym for _, sym in REGISTRY.values())
    dfs = {}
    for sym in sorted(syms):
        df = load_ohlcv(sym)
        if df.empty:
            continue
        dfs[sym] = add_indicators(df)
    print()

    results = []
    for name, (fn, symbol) in REGISTRY.items():
        if symbol not in dfs:
            print(f"  SKIP {name} — {symbol} no data")
            continue
        df = dfs[symbol]
        try:
            ls, ss, sl, tp, trail, lx, sx = fn(df)
            r = run_oos(df, ls, ss, sl, tp, trail, lx, sx)
        except Exception as e:
            print(f"  ERROR {name}: {e}")
            import traceback; traceback.print_exc()
            continue

        tv_pf   = TV_PF.get(name, 0.0)
        oos     = r["oos"]
        oos_pf  = oos["pf"]
        delta   = round(tv_pf - oos_pf, 2)
        if oos_pf >= 1.20 and oos["roi_day"] > 0 and oos["max_dd"] < 15:
            verdict = "PASS"
        elif oos_pf >= 1.10:
            verdict = "WATCH"
        else:
            verdict = "FAIL"

        results.append({
            "Strategy":   name,
            "Asset":      symbol,
            "TV PF":      tv_pf,
            "OOS PF":     oos_pf,
            "OOS WR%":    oos["wr"],
            "OOS Trades": oos["trades"],
            "ROI/day%":   oos["roi_day"],
            "Max DD%":    oos["max_dd"],
            "PF delta":   delta,
            "IS PF":      r["is"]["pf"],
            "Verdict":    verdict,
        })
        print(f"  {name:<42} {symbol:<10} TV:{tv_pf:>5.2f}  "
              f"OOS:{oos_pf:>5.2f}  ROI/d:{oos['roi_day']:>7.4f}%  "
              f"DD:{oos['max_dd']:>5.1f}%  Trades:{oos['trades']:>4}  {verdict}")

    print("\n" + "=" * 110)
    print(f"  {'Strategy':<42} {'Asset':<10} {'TV PF':>6} {'OOS PF':>7} {'WR%':>5} "
          f"{'Trd':>4} {'ROI/d%':>8} {'DD%':>6} {'PFδ':>6} {'IS PF':>6}  Verdict")
    print("-" * 110)

    for grp_tag, grp_ids in [("── Group B (6 strategies) ──", GROUP_B),
                              ("── Group A (9 strategies) ──", None)]:
        print(f"  {grp_tag}")
        for r in results:
            code = r["Strategy"].split()[0]
            in_b = code in GROUP_B
            if grp_ids is not None and not in_b:
                continue
            if grp_ids is None and in_b:
                continue
            v = {"PASS": "✅ PASS", "WATCH": "⚠️  WATCH", "FAIL": "❌ FAIL"}.get(r["Verdict"], r["Verdict"])
            print(f"  {r['Strategy']:<42} {r['Asset']:<10} {r['TV PF']:>6.2f} {r['OOS PF']:>7.2f} "
                  f"{r['OOS WR%']:>5.1f} {r['OOS Trades']:>4} {r['ROI/day%']:>8.4f} "
                  f"{r['Max DD%']:>6.1f} {r['PF delta']:>6.2f} {r['IS PF']:>6.2f}  {v}")

    out = OUTPUT_DIR / "backtest_r04_groups_results.csv"
    pd.DataFrame(results).to_csv(out, index=False)
    print(f"\n  Results saved → {out}")

    passes  = [r for r in results if r["Verdict"] == "PASS"]
    watches = [r for r in results if r["Verdict"] == "WATCH"]
    fails   = [r for r in results if r["Verdict"] == "FAIL"]
    print(f"\n  SUMMARY: {len(passes)} PASS  |  {len(watches)} WATCH  |  {len(fails)} FAIL")
    if passes:
        print("  Top PASS candidates:")
        for r in sorted(passes, key=lambda x: -x["OOS PF"])[:5]:
            print(f"    → {r['Strategy']} | {r['Asset']} | OOS PF={r['OOS PF']:.2f} | ROI/d={r['ROI/day%']:.4f}%")
    print("=" * 110)


if __name__ == "__main__":
    main()
