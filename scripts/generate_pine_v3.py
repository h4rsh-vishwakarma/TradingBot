"""
generate_pine_v3.py
Generate Pine Script V5 strategies for all symbols based on V3 tournament results.
Run from: /home/ubuntu/tradingview_webhook_bot/scripts/
"""
import csv
import os

REPORT_PATH = '/home/ubuntu/tradingview_webhook_bot/storage/reports/tournament_winners_4h_v3.csv'
PINE_OUT_DIR = '/home/ubuntu/tradingview_webhook_bot/strategies/pine_v3'

rows = []
with open(REPORT_PATH) as f:
    reader = csv.DictReader(f)
    for r in reader:
        rows.append(r)

# Best per symbol (by OOS)
best = {}
for r in rows:
    sym = r['Symbol']
    roi = float(r['OOS_Daily_ROI_%'])
    if sym not in best or roi > float(best[sym]['OOS_Daily_ROI_%']):
        best[sym] = r

os.makedirs(PINE_OUT_DIR, exist_ok=True)


def make_pine_psar(sym, mult_f, length_i, sl_pct_f, tp_pct_f, oos_roi, live_roi, strategy):
    af_step = round(mult_f * 0.005, 4)
    af_max  = round(mult_f * 0.05, 4)
    vol_thr = round(max(mult_f * 0.4, 0.8), 2)
    alert_name = strategy.replace(' ', '_')
    return f"""//@version=5
// {sym} — {strategy} (V3 Optimised)
// OOS Daily ROI: {oos_roi}% | Live ROI 2x: {live_roi}% | Ranked by OOS
// Params: af_step={af_step}, af_max={af_max}, vol_len={length_i}, SL={sl_pct_f}%, TP={tp_pct_f}%
strategy("{sym} {strategy} 4H v3",
     overlay=true, pyramiding=0, initial_capital=10000,
     default_qty_type=strategy.percent_of_equity, default_qty_value=20,
     commission_type=strategy.commission.percent, commission_value=0.04)

// Inputs
float sl_inp = input.float({sl_pct_f}, "Stop Loss %",   minval=0.1, maxval=10)  / 100
float tp_inp = input.float({tp_pct_f}, "Take Profit %", minval=0.1, maxval=30) / 100

// PSAR
float psar = ta.sar({af_step}, {af_max})

// Volume filter
float vol_ma = ta.sma(volume, {length_i})
bool  vol_ok = volume > vol_ma * {vol_thr}

// ADX filter
[diplus, diminus, adx_val] = ta.dmi(14, 14)
bool adx_ok = adx_val > 20

// Signals
bool longCond  = close > psar and close[1] <= psar[1] and vol_ok
bool shortCond = close < psar and close[1] >= psar[1] and vol_ok

// Entry
if longCond and strategy.position_size == 0
    strategy.entry("Long", strategy.long)
    strategy.exit("LX", "Long",  stop=close*(1-sl_inp), limit=close*(1+tp_inp))
if shortCond and strategy.position_size == 0
    strategy.entry("Short", strategy.short)
    strategy.exit("SX", "Short", stop=close*(1+sl_inp), limit=close*(1-tp_inp))

// Alerts — JSON payload for webhook
string long_msg  = '{{"symbol":"{sym}","strategy":"{alert_name}","action":"buy","price":' + str.tostring(close) + '}}'
string short_msg = '{{"symbol":"{sym}","strategy":"{alert_name}","action":"sell","price":' + str.tostring(close) + '}}'
alertcondition(longCond,  title="LONG  {sym}")
alertcondition(shortCond, title="SHORT {sym}")

// Visual markers
if longCond
    label.new(bar_index, low,  "L", color=color.green, style=label.style_label_up,   size=size.small)
if shortCond
    label.new(bar_index, high, "S", color=color.red,   style=label.style_label_down, size=size.small)

// Info table
var table t = table.new(position.top_right, 2, 5, bgcolor=color.new(color.black, 80))
if barstate.islast
    table.cell(t, 0, 0, "Symbol",   text_color=color.gray,  text_size=size.small)
    table.cell(t, 1, 0, "{sym}",    text_color=color.white, text_size=size.small)
    table.cell(t, 0, 1, "Strategy", text_color=color.gray,  text_size=size.small)
    table.cell(t, 1, 1, "PSAR+Vol", text_color=color.yellow,text_size=size.small)
    table.cell(t, 0, 2, "OOS ROI",  text_color=color.gray,  text_size=size.small)
    table.cell(t, 1, 2, "{oos_roi}%/day", text_color=color.green, text_size=size.small)
    table.cell(t, 0, 3, "Live 2x",  text_color=color.gray,  text_size=size.small)
    table.cell(t, 1, 3, "{live_roi}%/day", text_color=color.lime, text_size=size.small)
    table.cell(t, 0, 4, "SL/TP",    text_color=color.gray,  text_size=size.small)
    table.cell(t, 1, 4, "{sl_pct_f}% / {tp_pct_f}%", text_color=color.orange, text_size=size.small)
"""


def make_pine_macd(sym, mult_f, length_i, sl_pct_f, tp_pct_f, oos_roi, live_roi, strategy):
    fast_p = max(int(length_i * 0.5), 3)
    sig_p  = max(int(length_i * 0.33), 3)
    vol_thr = round(max(mult_f * 0.5, 0.8), 2)
    alert_name = strategy.replace(' ', '_')
    return f"""//@version=5
// {sym} — {strategy} (V3 Optimised)
// OOS Daily ROI: {oos_roi}% | Live ROI 2x: {live_roi}%
// Params: fast={fast_p}, slow={length_i}, sig={sig_p}, SL={sl_pct_f}%, TP={tp_pct_f}%
strategy("{sym} {strategy} 4H v3",
     overlay=true, pyramiding=0, initial_capital=10000,
     default_qty_type=strategy.percent_of_equity, default_qty_value=20,
     commission_type=strategy.commission.percent, commission_value=0.04)

float sl_inp = input.float({sl_pct_f}, "Stop Loss %",   minval=0.1, maxval=10)  / 100
float tp_inp = input.float({tp_pct_f}, "Take Profit %", minval=0.1, maxval=30) / 100

float macd_line   = ta.ema(close, {fast_p}) - ta.ema(close, {length_i})
float signal_line = ta.ema(macd_line, {sig_p})
float histogram   = macd_line - signal_line
float vol_ma      = ta.sma(volume, {length_i})
bool  vol_ok      = volume > vol_ma * {vol_thr}

bool longCond  = histogram > 0 and histogram[1] <= 0 and vol_ok
bool shortCond = histogram < 0 and histogram[1] >= 0 and vol_ok

if longCond and strategy.position_size == 0
    strategy.entry("Long", strategy.long)
    strategy.exit("LX", "Long",  stop=close*(1-sl_inp), limit=close*(1+tp_inp))
if shortCond and strategy.position_size == 0
    strategy.entry("Short", strategy.short)
    strategy.exit("SX", "Short", stop=close*(1+sl_inp), limit=close*(1-tp_inp))

string long_msg  = '{{"symbol":"{sym}","strategy":"{alert_name}","action":"buy","price":' + str.tostring(close) + '}}'
string short_msg = '{{"symbol":"{sym}","strategy":"{alert_name}","action":"sell","price":' + str.tostring(close) + '}}'
alertcondition(longCond,  title="LONG  {sym}")
alertcondition(shortCond, title="SHORT {sym}")

if longCond
    label.new(bar_index, low,  "L", color=color.green, style=label.style_label_up,   size=size.small)
if shortCond
    label.new(bar_index, high, "S", color=color.red,   style=label.style_label_down, size=size.small)
"""


def make_pine_keltner(sym, mult_f, length_i, sl_pct_f, tp_pct_f, oos_roi, live_roi, strategy):
    alert_name = strategy.replace(' ', '_')
    return f"""//@version=5
// {sym} — {strategy} (V3 Optimised)
// OOS Daily ROI: {oos_roi}% | Live ROI 2x: {live_roi}%
// Params: ema={length_i}, atr_mult={mult_f}, SL={sl_pct_f}%, TP={tp_pct_f}%
strategy("{sym} {strategy} 4H v3",
     overlay=true, pyramiding=0, initial_capital=10000,
     default_qty_type=strategy.percent_of_equity, default_qty_value=20,
     commission_type=strategy.commission.percent, commission_value=0.04)

float sl_inp = input.float({sl_pct_f}, "Stop Loss %",   minval=0.1, maxval=10)  / 100
float tp_inp = input.float({tp_pct_f}, "Take Profit %", minval=0.1, maxval=30) / 100

float ema_k   = ta.ema(close, {length_i})
float atr_k   = ta.atr({length_i})
float upper_k = ema_k + {mult_f} * atr_k
float lower_k = ema_k - {mult_f} * atr_k
float ema_200 = ta.ema(close, 200)
[diplus, diminus, adx_k] = ta.dmi(14, 14)

bool longCond  = close > upper_k and close[1] <= upper_k[1] and close > ema_200
bool shortCond = close < lower_k and close[1] >= lower_k[1] and close < ema_200

if longCond and strategy.position_size == 0
    strategy.entry("Long", strategy.long)
    strategy.exit("LX", "Long",  stop=close*(1-sl_inp), limit=close*(1+tp_inp))
if shortCond and strategy.position_size == 0
    strategy.entry("Short", strategy.short)
    strategy.exit("SX", "Short", stop=close*(1+sl_inp), limit=close*(1-tp_inp))

string long_msg  = '{{"symbol":"{sym}","strategy":"{alert_name}","action":"buy","price":' + str.tostring(close) + '}}'
string short_msg = '{{"symbol":"{sym}","strategy":"{alert_name}","action":"sell","price":' + str.tostring(close) + '}}'
alertcondition(longCond,  title="LONG  {sym}")
alertcondition(shortCond, title="SHORT {sym}")

if longCond
    label.new(bar_index, low,  "L", color=color.green, style=label.style_label_up,   size=size.small)
if shortCond
    label.new(bar_index, high, "S", color=color.red,   style=label.style_label_down, size=size.small)

plot(upper_k, "Upper Keltner", color=color.new(color.green, 60), linewidth=1)
plot(lower_k, "Lower Keltner", color=color.new(color.red,   60), linewidth=1)
plot(ema_k,   "EMA",           color=color.new(color.blue,  60), linewidth=1)
"""


generated = []
for sym, r in sorted(best.items(), key=lambda x: float(x[1]['OOS_Daily_ROI_%']), reverse=True):
    strat     = r['Strategy']
    mult_f    = float(r['Optimal_Mult'])
    length_i  = int(float(r['Optimal_Len']))
    sl_pct_f  = float(r['Optimal_SL_%'])
    tp_pct_f  = float(r['Optimal_TP_%'])
    oos_roi   = r['OOS_Daily_ROI_%']
    live_roi  = r['Live_ROI_%']

    strat_u = strat.upper()
    if 'PSAR' in strat_u or '44' in strat_u or '56' in strat_u:
        pine = make_pine_psar(sym, mult_f, length_i, sl_pct_f, tp_pct_f, oos_roi, live_roi, strat)
    elif 'MACD' in strat_u:
        pine = make_pine_macd(sym, mult_f, length_i, sl_pct_f, tp_pct_f, oos_roi, live_roi, strat)
    elif 'KELTNER' in strat_u or 'KB' in strat_u:
        pine = make_pine_keltner(sym, mult_f, length_i, sl_pct_f, tp_pct_f, oos_roi, live_roi, strat)
    else:
        pine = make_pine_psar(sym, mult_f, length_i, sl_pct_f, tp_pct_f, oos_roi, live_roi, strat)

    clean_strat = strat.replace(' ', '_').replace('/', '_')
    fname = f"{sym}_{clean_strat}_v3.pine"
    fpath = os.path.join(PINE_OUT_DIR, fname)
    with open(fpath, 'w') as f:
        f.write(pine)
    generated.append((sym, fname, float(oos_roi), float(live_roi)))
    print(f"  {sym:<12} {strat:<30} OOS={oos_roi}% -> {fname}")

print(f"\nTotal Pine scripts: {len(generated)}")
print(f"Location: {PINE_OUT_DIR}")

# Print ALLOWED_SYMBOLS summary
allowed = ['SUIUSDT', 'INJUSDT', 'LDOUSDT', 'NEARUSDT', 'APTUSDT']
print("\n=== Current ALLOWED_SYMBOLS — V3 Pine Script Summary ===")
for sym, fname, oos, live in generated:
    if sym in allowed:
        print(f"  {sym}: OOS={oos:.3f}%/day  live={live:.3f}%/day  file={fname}")
