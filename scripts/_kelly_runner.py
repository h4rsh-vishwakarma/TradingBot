#!/usr/bin/env python3
"""Half-Kelly vs Fixed sizing comparison across all 4H symbols."""
import os, sys, pandas as pd, numpy as np
sys.path.insert(0, '/home/ubuntu/tradingview_webhook_bot')
from scripts.backtest_engine_v4 import run_backtest_comparison

DATA_DIR = '/home/ubuntu/tradingview_webhook_bot/storage/backtest_data'


def donchian_signal(df, length=20, mult=2.0):
    hi  = df['high'].rolling(length).max()
    lo  = df['low'].rolling(length).min()
    ema = df['close'].ewm(span=int(length * mult), adjust=False).mean()
    sig = np.zeros(len(df), dtype=int)
    for i in range(length, len(df)):
        if df['close'].iloc[i] > hi.iloc[i - 1] and df['close'].iloc[i] > ema.iloc[i]:
            sig[i] = 1
        elif df['close'].iloc[i] < lo.iloc[i - 1] and df['close'].iloc[i] < ema.iloc[i]:
            sig[i] = -1
    return sig


def load_params():
    path = '/home/ubuntu/tradingview_webhook_bot/storage/reports/tournament_winners_4h_v4.csv'
    try:
        tw   = pd.read_csv(path)
        best = tw.sort_values('OOS_Daily_ROI_pct', ascending=False).groupby('Symbol').first().reset_index()
        return {
            row['Symbol']: {
                'sl'    : float(row['Optimal_SL_pct']) / 100,
                'tp'    : float(row['Optimal_TP_pct']) / 100,
                'lev'   : float(row['Leverage']),
                'mult'  : float(row['Optimal_Mult']),
                'length': int(row['Optimal_Len']),
            }
            for _, row in best.iterrows()
        }
    except Exception as e:
        print(f'Warning: cannot load tournament params: {e}')
        return {}


DEFAULT_PARAMS = {'sl': 0.015, 'tp': 0.06, 'lev': 2.0, 'mult': 2.0, 'length': 20}

params_map = load_params()
files      = sorted(f for f in os.listdir(DATA_DIR) if f.endswith('_4h.csv'))
rows       = []

for fname in files:
    sym = fname.replace('_3y_4h.csv', '').replace('_4h.csv', '')
    df  = pd.read_csv(os.path.join(DATA_DIR, fname))
    df.columns = [c.lower() for c in df.columns]

    p = params_map.get(sym, DEFAULT_PARAMS)
    df['sig'] = donchian_signal(df, length=p['length'], mult=p['mult'])
    days = max(int(len(df) * 4 / 24), 1)

    cmp = run_backtest_comparison(
        df, signal_col='sig',
        sl_pct=p['sl'], tp_pct=p['tp'], leverage=p['lev'],
        total_days=days, min_trades=20,
    )
    if cmp is None:
        print(f'  SKIP {sym}: insufficient trades')
        continue

    rows.append({
        'Symbol'       : sym,
        'Fixed_ROI'    : cmp['fixed_roi_annual_pct'],
        'Kelly_ROI'    : cmp['kelly_roi_annual_pct'],
        'ROI_Delta'    : cmp['sizing_improvement_pct'],
        'Fixed_DD'     : cmp['fixed_max_dd_pct'],
        'Kelly_DD'     : cmp['kelly_max_dd_pct'],
        'DD_Red'       : cmp['dd_improvement_pct'],
        'Fixed_Sharpe' : cmp['fixed_sharpe_ratio'],
        'Kelly_Sharpe' : cmp['kelly_sharpe_ratio'],
        'Sharpe_Delta' : cmp['sharpe_improvement'],
        'AvgSize'      : cmp.get('kelly_kelly_avg_size_pct', 0.0),
        'Kelly_Better' : cmp['kelly_better'],
        'Fixed_Grade'  : cmp['fixed_performance_grade'],
        'Kelly_Grade'  : cmp['kelly_performance_grade'],
    })

if not rows:
    print('No results produced.')
    sys.exit(1)

res = pd.DataFrame(rows)
W   = 128

print()
print('=' * W)
print('  HALF-KELLY vs FIXED SIZING — ALL 4H SYMBOLS  (3-YEAR BACKTEST, Donchian+EMA signals)')
print('=' * W)
HDR = ('  {:<12} {:>10} {:>10} {:>8}  {:>9} {:>9} {:>8}  {:>11} {:>11} {:>8}  {:>8} {:>7}'
       .format('Symbol','Fixed ROI%','Kelly ROI%','Δ ROI','FixedDD%','KellyDD%','Δ DD',
                'FixSharpe','KlySharpe','ΔSharpe','AvgSz%','Better'))
print(HDR)
print('  ' + '-' * (W - 2))

for _, r in res.iterrows():
    better = 'YES' if r['Kelly_Better'] else 'NO'
    line = ('  {:<12} {:>10.1f} {:>10.1f} {:>+8.1f}  {:>9.1f} {:>9.1f} {:>+8.1f}  {:>11.2f} {:>11.2f} {:>+8.2f}  {:>8.1f} {:>7}'
            .format(r['Symbol'], r['Fixed_ROI'], r['Kelly_ROI'], r['ROI_Delta'],
                    r['Fixed_DD'], r['Kelly_DD'], r['DD_Red'],
                    r['Fixed_Sharpe'], r['Kelly_Sharpe'], r['Sharpe_Delta'],
                    r['AvgSize'], better))
    print(line)

print('  ' + '-' * (W - 2))
better_n     = int(res['Kelly_Better'].sum())
avg_dd_red   = res['DD_Red'].mean()
avg_roi_d    = res['ROI_Delta'].mean()
avg_sh_d     = res['Sharpe_Delta'].mean()
avg_ks       = res['AvgSize'].mean()
total        = len(res)
grade_ups    = int((res['Kelly_Grade'] != res['Fixed_Grade']).sum())
print(('  TOTALS: Kelly better in {}/{} symbols | Avg DD reduction: {:+.1f}% | '
       'Avg ROI delta: {:+.1f}pp | Avg Sharpe delta: {:+.2f} | '
       'Avg Kelly size: {:.1f}% | Grade upgrades: {}'
       ).format(better_n, total, avg_dd_red, avg_roi_d, avg_sh_d, avg_ks, grade_ups))
print('=' * W)
