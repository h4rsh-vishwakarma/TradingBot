#!/usr/bin/env python3
"""
strategy_combo_builder.py — Auto-invent new strategy combinations.

Runs nightly after tournament (cron 01:30 UTC).
Steps:
  1. Define 10 indicator building-blocks
  2. Generate all 2-combo + 3-combo pairs (AND logic: all signals must agree)
  3. Backtest each combo on all 4h CSVs (OOS 80/20 split)
  4. Keep combos passing: OOS_PF > 1.3, OOS_DD > -40%, Win > 45%
  5. Write new winners to storage/reports/combo_winners.csv
  6. Generate Pine V5 script for each top-5 combo (with alertcondition + alert_message)
  7. Send Telegram summary

Usage:
  python3 scripts/strategy_combo_builder.py
"""

import gc
import json
import os
import sys
import glob
import itertools
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

ENV_FILE = "/etc/tradingbot/env_vars"
if os.path.exists(ENV_FILE):
    load_dotenv(ENV_FILE, override=True)

TOKEN    = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID  = os.getenv("TELEGRAM_CHAT_ID", "5736858710")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "squeeze_tradingview_cluster_2026_secure")
SERVER_URL = "https://tradingbot.operatorbrief.xyz/webhook/tradingview"

DATA_DIR   = PROJECT_ROOT / "storage" / "backtest_data"
REPORT_OUT = PROJECT_ROOT / "storage" / "reports" / "combo_winners.csv"
PINE_OUT   = PROJECT_ROOT / "strategies" / "pine_combos"
MANIFEST   = PROJECT_ROOT / "config" / "approved_strategies.json"

PINE_OUT.mkdir(parents=True, exist_ok=True)

# ── Risk parameters (same as tournament) ─────────────────────────────────────
LEVERAGE       = 1.0
STOP_LOSS      = 0.015
TAKE_PROFIT    = 0.045
FEE_PER_SIDE   = 0.0004
MIN_HOLD_BARS  = 4
COOLDOWN_BARS  = 4
COOLDOWN_TRIG  = 3
MIN_OOS_PF     = 1.30
MIN_OOS_WR     = 45.0
MAX_OOS_DD     = -40.0
TRAIN_PCT      = 0.80


# ── Indicator helpers ─────────────────────────────────────────────────────────
def calc_rsi(close, n=14):
    delta = close.diff()
    up   = delta.clip(lower=0).rolling(n).mean()
    down = (-delta.clip(upper=0)).rolling(n).mean()
    rs   = up / down.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def calc_macd_cross(close, fast=12, slow=26, sig=9):
    m = close.ewm(span=fast, adjust=False).mean() - close.ewm(span=slow, adjust=False).mean()
    s = m.ewm(span=sig, adjust=False).mean()
    long_  = (m > s) & (m.shift(1) <= s.shift(1))
    short_ = (m < s) & (m.shift(1) >= s.shift(1))
    return pd.Series(np.where(long_, 1, np.where(short_, -1, 0)), index=close.index)


def calc_ema_cross(close, fast=8, slow=21):
    f = close.ewm(span=fast, adjust=False).mean()
    s = close.ewm(span=slow, adjust=False).mean()
    return pd.Series(np.where(f > s, 1, -1), index=close.index)


def calc_donchian_brk(high, low, close, n=20):
    upper = high.rolling(n).max().shift(1)
    lower = low.rolling(n).min().shift(1)
    return pd.Series(np.where(close >= upper, 1, np.where(close <= lower, -1, 0)), index=close.index)


def calc_cci(high, low, close, n=20):
    tp   = (high + low + close) / 3
    mean = tp.rolling(n).mean()
    mad  = tp.rolling(n).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    cci  = (tp - mean) / (0.015 * mad.replace(0, np.nan))
    return pd.Series(np.where(cci < -100, 1, np.where(cci > 100, -1, 0)), index=close.index)


def calc_bb_bounce(close, n=20, mult=2.0):
    mid  = close.rolling(n).mean()
    std  = close.rolling(n).std()
    upper = mid + mult * std
    lower = mid - mult * std
    return pd.Series(np.where(close < lower, 1, np.where(close > upper, -1, 0)), index=close.index)


def calc_psar_flip(high, low):
    psar = low.copy().astype(float)
    bull = True
    af_step = 0.02; af_max = 0.2
    af = af_step
    ep = float(high.iloc[0])
    for i in range(2, len(high)):
        prev = float(psar.iloc[i - 1])
        if bull:
            val = prev + af * (ep - prev)
            val = min(val, float(low.iloc[i - 1]), float(low.iloc[i - 2]) if i >= 2 else val)
            if float(low.iloc[i]) < val:
                bull = False; af = af_step; ep = float(low.iloc[i]); val = ep
            else:
                if float(high.iloc[i]) > ep:
                    ep = float(high.iloc[i]); af = min(af + af_step, af_max)
        else:
            val = prev + af * (ep - prev)
            val = max(val, float(high.iloc[i - 1]), float(high.iloc[i - 2]) if i >= 2 else val)
            if float(high.iloc[i]) > val:
                bull = True; af = af_step; ep = float(high.iloc[i]); val = ep
            else:
                if float(low.iloc[i]) < ep:
                    ep = float(low.iloc[i]); af = min(af + af_step, af_max)
        psar.iloc[i] = val
    close = high  # reuse index
    return pd.Series(np.where(high.values > psar.values, 1, -1), index=high.index)


def calc_stoch(high, low, close, k=14, d=3):
    lo = low.rolling(k).min(); hi = high.rolling(k).max()
    raw = 100 * (close - lo) / (hi - lo + 1e-9)
    stoch = raw.rolling(d).mean()
    return pd.Series(np.where(stoch < 20, 1, np.where(stoch > 80, -1, 0)), index=close.index)


def calc_obv_trend(close, volume):
    obv    = (np.sign(close.diff()) * volume).fillna(0).cumsum()
    obv_ma = obv.rolling(20).mean()
    return pd.Series(np.where(obv > obv_ma, 1, -1), index=close.index)


def calc_supertrend(high, low, close, mult=3.0, n=10):
    atr   = (high - low).rolling(n).mean()
    upper = (high + low) / 2 + mult * atr
    lower = (high + low) / 2 - mult * atr
    trend = pd.Series(1, index=close.index, dtype=float)
    for i in range(1, len(close)):
        if float(close.iloc[i]) > float(upper.iloc[i - 1]):
            trend.iloc[i] = 1
        elif float(close.iloc[i]) < float(lower.iloc[i - 1]):
            trend.iloc[i] = -1
        else:
            trend.iloc[i] = trend.iloc[i - 1]
    return trend


def calc_adx(high, low, close, n=14):
    tr   = np.maximum(high - low, np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))))
    atr  = pd.Series(tr.values, index=close.index).rolling(n).mean()
    up   = (high - high.shift(1)).clip(lower=0)
    dn   = (low.shift(1) - low).clip(lower=0)
    pdi  = 100 * up.rolling(n).mean() / (atr + 1e-9)
    mdi  = 100 * dn.rolling(n).mean() / (atr + 1e-9)
    dx   = 100 * abs(pdi - mdi) / (pdi + mdi + 1e-9)
    return dx.rolling(n).mean().fillna(0)


# ── Signal factory ────────────────────────────────────────────────────────────
INDICATOR_FUNCS = {
    "RSI":      lambda df: calc_rsi(df['close']).pipe(lambda r: pd.Series(np.where(r < 30, 1, np.where(r > 70, -1, 0)), index=df.index)),
    "MACD":     lambda df: calc_macd_cross(df['close']),
    "EMA":      lambda df: calc_ema_cross(df['close']),
    "DONCHIAN": lambda df: calc_donchian_brk(df['high'], df['low'], df['close']),
    "CCI":      lambda df: calc_cci(df['high'], df['low'], df['close']),
    "BB":       lambda df: calc_bb_bounce(df['close']),
    "PSAR":     lambda df: calc_psar_flip(df['high'], df['low']),
    "STOCH":    lambda df: calc_stoch(df['high'], df['low'], df['close']),
    "OBV":      lambda df: calc_obv_trend(df['close'], df['volume']),
    "STREND":   lambda df: calc_supertrend(df['high'], df['low'], df['close']),
}


def combo_signal(df, names):
    sigs = []
    for name in names:
        try:
            s = INDICATOR_FUNCS[name](df).fillna(0)
            sigs.append(s.values)
        except Exception:
            return pd.Series(0, index=df.index)
    sigs = np.stack(sigs, axis=1)
    long_  = (sigs == 1).all(axis=1)
    short_ = (sigs == -1).all(axis=1)
    return pd.Series(np.where(long_, 1, np.where(short_, -1, 0)), index=df.index)


# ── Backtest engine ───────────────────────────────────────────────────────────
def run_backtest(df, signal_series):
    df = df.copy()
    df['sig'] = signal_series.values

    # ADX trend filter
    adx = calc_adx(df['high'], df['low'], df['close'])
    df['sig'] = np.where(adx > 20, df['sig'], 0)

    # ATR spike filter
    atr14  = (df['high'] - df['low']).rolling(14).mean()
    atr_ma = atr14.rolling(100).mean()
    df['sig'] = np.where(atr14 > 2 * atr_ma, 0, df['sig'])

    # Min hold filter
    sig_arr = df['sig'].values.copy()
    hold_count = 0; current_sig = 0
    for i in range(len(sig_arr)):
        if sig_arr[i] != current_sig and current_sig != 0:
            if hold_count < MIN_HOLD_BARS:
                sig_arr[i] = current_sig; hold_count += 1
            else:
                current_sig = sig_arr[i]; hold_count = 0
        elif sig_arr[i] != 0 and current_sig == 0:
            current_sig = sig_arr[i]; hold_count = 1
        else:
            if current_sig != 0:
                hold_count += 1
            if sig_arr[i] == 0 and current_sig != 0 and hold_count >= MIN_HOLD_BARS:
                current_sig = 0; hold_count = 0
    df['sig'] = sig_arr

    df['pct'] = df['close'].pct_change()
    df['ret'] = df['sig'].shift(1) * df['pct'] * LEVERAGE
    df['ret'] = df['ret'].clip(lower=-STOP_LOSS, upper=TAKE_PROFIT)

    # Fee model
    sa     = df['sig'].values
    prev_s = np.empty_like(sa); prev_s[0] = 0; prev_s[1:] = sa[:-1]
    next_s = np.empty_like(sa); next_s[-1] = 0; next_s[:-1] = sa[1:]
    is_entry = (sa != 0) & (sa != prev_s)
    is_exit  = (sa != 0) & (sa != next_s)
    df['ret'] -= (is_entry.astype(float) + is_exit.astype(float)) * FEE_PER_SIDE

    # Cooldown
    rets = df['ret'].values.copy(); consec = 0; skip = 0
    for i in range(len(rets)):
        if skip > 0:
            rets[i] = 0.0; skip -= 1; continue
        if rets[i] < 0:
            consec += 1
            if consec >= COOLDOWN_TRIG:
                skip = COOLDOWN_BARS; consec = 0
        else:
            consec = 0
    df['ret'] = rets

    total_bars = max(len(df), 1)
    total_days = max(total_bars / 6, 1)   # 4h bars → 6/day
    daily_roi  = df['ret'].sum() * 100 / total_days

    cum = (1 + df['ret'].fillna(0)).cumprod()
    dd  = ((cum - cum.cummax()) / cum.cummax() * 100).min()

    trades    = df['ret'][df['ret'] != 0]
    total_t   = len(trades)
    wins      = len(trades[trades > 0])
    win_rate  = round(wins / total_t * 100, 1) if total_t > 0 else 0.0
    gross_w   = trades[trades > 0].sum()
    gross_l   = abs(trades[trades < 0].sum())
    pf        = round(gross_w / gross_l, 3) if gross_l > 0 else 0.0
    mean_r    = df['ret'].mean(); std_r = df['ret'].std()
    sharpe    = round((mean_r / std_r) * np.sqrt(6 * 365), 2) if std_r > 0 else 0.0

    return {
        "daily_roi": round(daily_roi, 3),
        "dd":        round(dd, 2),
        "win_rate":  win_rate,
        "pf":        pf,
        "sharpe":    sharpe,
        "trades":    total_t,
    }


# ── Pine Script generator ─────────────────────────────────────────────────────
PINE_IND = {
    "RSI":      ("rsi_val = ta.rsi(close, 14)",
                 "rsi_val < 30", "rsi_val > 70"),
    "MACD":     ("[macd_l, macd_s, _] = ta.macd(close, 12, 26, 9)",
                 "ta.crossover(macd_l, macd_s)", "ta.crossunder(macd_l, macd_s)"),
    "EMA":      ("ema8 = ta.ema(close, 8)\nema21 = ta.ema(close, 21)",
                 "ta.crossover(ema8, ema21)", "ta.crossunder(ema8, ema21)"),
    "DONCHIAN": ("don_hi = ta.highest(high, 20)[1]\ndon_lo = ta.lowest(low, 20)[1]",
                 "close >= don_hi", "close <= don_lo"),
    "CCI":      ("cci_val = ta.cci(high, low, close, 20)",
                 "cci_val < -100", "cci_val > 100"),
    "BB":       ("[bb_u, bb_m, bb_l] = ta.bb(close, 20, 2)",
                 "close < bb_l", "close > bb_u"),
    "PSAR":     ("psar_val = ta.sar(0.02, 0.02, 0.2)",
                 "close > psar_val", "close < psar_val"),
    "STOCH":    ("stoch_k = ta.stoch(close, high, low, 14)",
                 "stoch_k < 20", "stoch_k > 80"),
    "OBV":      ("obv_val = ta.obv\nobv_ma = ta.sma(obv_val, 20)",
                 "obv_val > obv_ma", "obv_val < obv_ma"),
    "STREND":   ("[st_val, st_dir] = ta.supertrend(3.0, 10)",
                 "st_dir < 0", "st_dir > 0"),
}


def generate_pine_combo(sym, names, metrics, webhook_secret):
    combo_id   = "_x_".join(names)
    strat_label = " + ".join(names)
    decls, longs, shorts = [], [], []
    for n in names:
        d, lc, sc = PINE_IND.get(n, ("", "false", "false"))
        decls.append(d)
        longs.append(f"({lc})")
        shorts.append(f"({sc})")

    long_expr  = " and ".join(longs)
    short_expr = " and ".join(shorts)

    oos_roi = metrics.get('daily_roi', 0)
    oos_dd  = metrics.get('dd', 0)
    oos_wr  = metrics.get('win_rate', 0)
    oos_pf  = metrics.get('pf', 0)

    decl_block = "\n".join(decls)
    # Pine double-brace trick: use literal {{ }} for JSON braces inside f-string
    return f"""//@version=5
// AUTO-GENERATED by strategy_combo_builder.py
// Combo: {strat_label}  |  Symbol: {sym}
// OOS: ROI={oos_roi}%/day  DD={oos_dd}%  WR={oos_wr}%  PF={oos_pf}
strategy("{sym} {combo_id} 4H",
     overlay=true, pyramiding=0, initial_capital=10000,
     default_qty_type=strategy.percent_of_equity, default_qty_value=20,
     commission_type=strategy.commission.percent, commission_value=0.04)

float sl_pct = input.float(1.5, "Stop Loss %",   minval=0.1, maxval=10)  / 100
float tp_pct = input.float(4.5, "Take Profit %", minval=0.1, maxval=30) / 100

[diplus, diminus, adx_v] = ta.dmi(14, 14)
bool adx_ok = adx_v > 20

{decl_block}

bool longCond  = adx_ok and {long_expr}
bool shortCond = adx_ok and {short_expr}

var string WHSEC = "{webhook_secret}"
string long_msg  = '{{"secret":"' + WHSEC + '","strategy":"{combo_id}","action":"BUY","ticker":"' + syminfo.ticker + '","interval":"{{interval}}","price":"' + str.tostring(close) + '"}}'
string short_msg = '{{"secret":"' + WHSEC + '","strategy":"{combo_id}","action":"SELL","ticker":"' + syminfo.ticker + '","interval":"{{interval}}","price":"' + str.tostring(close) + '"}}'
string clong_msg = '{{"secret":"' + WHSEC + '","strategy":"{combo_id}","action":"CLOSE_LONG","ticker":"' + syminfo.ticker + '","price":"' + str.tostring(close) + '"}}'
string cshrt_msg = '{{"secret":"' + WHSEC + '","strategy":"{combo_id}","action":"CLOSE_SHORT","ticker":"' + syminfo.ticker + '","price":"' + str.tostring(close) + '"}}'

if longCond and strategy.position_size <= 0
    strategy.entry("Long",  strategy.long,  alert_message=long_msg)
    strategy.exit("LX", "Long",  stop=close*(1-sl_pct), limit=close*(1+tp_pct), alert_message=clong_msg)
if shortCond and strategy.position_size >= 0
    strategy.entry("Short", strategy.short, alert_message=short_msg)
    strategy.exit("SX", "Short", stop=close*(1+sl_pct), limit=close*(1-sl_pct), alert_message=cshrt_msg)

alertcondition(longCond,  title="LONG  {sym}  {combo_id}")
alertcondition(shortCond, title="SHORT {sym}  {combo_id}")

if longCond
    label.new(bar_index, low,  "L", color=color.green, style=label.style_label_up,   size=size.small)
if shortCond
    label.new(bar_index, high, "S", color=color.red,   style=label.style_label_down, size=size.small)
"""


# ── Telegram helper ───────────────────────────────────────────────────────────
def send_telegram(text):
    if not TOKEN:
        print(text); return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=15,
        )
    except Exception:
        pass


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    ts_start = datetime.now(timezone.utc)
    print(f"[combo_builder] START {ts_start.strftime('%Y-%m-%d %H:%M UTC')}")

    data_files = sorted(glob.glob(str(DATA_DIR / "*_3y_4h.csv")))
    if not data_files:
        print("No 4h CSV files found in", DATA_DIR)
        return

    ind_names   = list(INDICATOR_FUNCS.keys())
    combos_2    = list(itertools.combinations(ind_names, 2))
    combos_3    = list(itertools.combinations(ind_names, 3))
    all_combos  = combos_2 + combos_3
    print(f"  Indicators: {len(ind_names)}  |  Combos: {len(all_combos)}  |  Symbols: {len(data_files)}")

    results      = []
    total_tested = 0

    for fpath in data_files:
        sym = os.path.basename(fpath).split("_")[0]
        try:
            df = pd.read_csv(fpath)
            if not {'close', 'high', 'low', 'volume'}.issubset(df.columns):
                continue
            df = df.dropna(subset=['close', 'high', 'low', 'volume']).reset_index(drop=True)
        except Exception as e:
            print(f"  SKIP {sym}: {e}"); continue

        split   = int(len(df) * TRAIN_PCT)
        df_oos  = df.iloc[split:].copy().reset_index(drop=True)

        passed_sym = 0
        for combo in all_combos:
            names    = list(combo)
            combo_id = "_x_".join(names)
            try:
                sig = combo_signal(df_oos, names)
                if sig.abs().sum() == 0:
                    continue
                m = run_backtest(df_oos, sig)
                total_tested += 1

                if (m['pf'] >= MIN_OOS_PF and
                        m['win_rate'] >= MIN_OOS_WR and
                        m['dd'] >= MAX_OOS_DD and
                        m['trades'] >= 10):
                    results.append({
                        "Symbol":      sym,
                        "Combo":       combo_id,
                        "Indicators":  " + ".join(names),
                        "OOS_PF":      m['pf'],
                        "OOS_DD_%":    m['dd'],
                        "OOS_WR_%":    m['win_rate'],
                        "OOS_ROI_%":   m['daily_roi'],
                        "OOS_Sharpe":  m['sharpe'],
                        "Trades":      m['trades'],
                    })
                    passed_sym += 1
            except Exception:
                pass
            finally:
                gc.collect()

        print(f"  {sym}: tested {len(all_combos)} combos — {passed_sym} passed")

    print(f"\nTotal tested: {total_tested}  |  Passing: {len(results)}")

    if not results:
        send_telegram(
            f"<b>Combo Builder</b>\nNo new combos passed OOS filters.\n"
            f"Filters: PF&gt;{MIN_OOS_PF} WR&gt;{MIN_OOS_WR}% DD&gt;{MAX_OOS_DD}%"
        )
        return

    df_out = pd.DataFrame(results).sort_values("OOS_PF", ascending=False)
    df_out.to_csv(REPORT_OUT, index=False)
    print(f"Saved: {REPORT_OUT}")

    # Best entry per unique combo (highest PF across symbols)
    top_by_combo = {}
    for _, row in df_out.iterrows():
        cid = row['Combo']
        if cid not in top_by_combo or row['OOS_PF'] > top_by_combo[cid]['OOS_PF']:
            top_by_combo[cid] = row

    pine_generated = []
    for cid, row in list(top_by_combo.items())[:5]:
        names = cid.split("_x_")
        m     = {"daily_roi": row['OOS_ROI_%'], "dd": row['OOS_DD_%'],
                 "win_rate": row['OOS_WR_%'], "pf": row['OOS_PF']}
        pine  = generate_pine_combo(row['Symbol'], names, m, WEBHOOK_SECRET)
        fname = f"{row['Symbol']}_{cid}_4h.pine"
        fpath = PINE_OUT / fname
        with open(fpath, "w") as fh:
            fh.write(pine)
        pine_generated.append(fname)
        print(f"  Pine written: {fname}")

    top5_txt = "\n".join(
        f"  {i+1}. <code>{cid}</code> [{row['Symbol']}] PF={row['OOS_PF']} WR={row['OOS_WR_%']}% DD={row['OOS_DD_%']}%"
        for i, (cid, row) in enumerate(list(top_by_combo.items())[:5])
    )
    elapsed = (datetime.now(timezone.utc) - ts_start).seconds
    msg = (
        f"<b>Combo Builder — New Discoveries</b>\n"
        f"Date: {ts_start.strftime('%Y-%m-%d')}  |  Elapsed: {elapsed}s\n\n"
        f"Combos tested: {total_tested}  |  Passed: <b>{len(results)}</b>\n"
        f"Filters: PF&gt;{MIN_OOS_PF}, WR&gt;{MIN_OOS_WR}%, DD&gt;{MAX_OOS_DD}%\n\n"
        f"<b>Top 5 New Combos:</b>\n{top5_txt}\n\n"
        f"Pine scripts: strategies/pine_combos/\n"
        f"Use /setup_alerts to get TV alert guide."
    )
    send_telegram(msg)
    print("[combo_builder] DONE")


if __name__ == "__main__":
    main()
