#!/usr/bin/env python3
"""Full discovery run with near-miss tracking — shows strategies that almost passed."""
import os, sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, '/home/ubuntu/tradingview_webhook_bot')
os.chdir('/home/ubuntu/tradingview_webhook_bot')

import pandas as pd
import numpy as np
from pathlib import Path
from scripts.strategy_discovery_engine import BUILTIN_STRATEGIES, run_backtest_comparison

DATA_DIR = Path('storage/backtest_data')

# Strict thresholds
STRICT = dict(dd=-20.0, sharpe=0.35, pf=1.25, roi=12.0, trades=30)
# Relaxed — near miss band
RELAX  = dict(dd=-30.0, sharpe=0.25, pf=1.10, roi=6.0,  trades=20)

passed  = []
near    = []
all_best = []

files_4h = sorted(f for f in os.listdir(DATA_DIR) if f.endswith('_4h.csv') or f.endswith('_3y_4h.csv'))
total = len(BUILTIN_STRATEGIES)

for i, (name, (fn, kwargs)) in enumerate(BUILTIN_STRATEGIES.items(), 1):
    print(f'[{i}/{total}] {name}', flush=True)
    best_for_strat = None

    for fname in files_4h:
        sym = fname.replace('_3y_4h.csv','').replace('_4h.csv','')
        try:
            df = pd.read_csv(DATA_DIR / fname)
            df.columns = [c.lower() for c in df.columns]
            if not {'open','high','low','close'}.issubset(df.columns): continue
            days = max(int(len(df)*4/24), 1)
            df['sig'] = fn(df, **kwargs)
            if (df['sig'] != 0).sum() < RELAX['trades']: continue
            cmp = run_backtest_comparison(df, signal_col='sig', sl_pct=0.015, tp_pct=0.060,
                                          leverage=2.0, total_days=days, min_trades=RELAX['trades'])
            if cmp is None: continue

            r = dict(
                strategy=name, symbol=sym, timeframe='4h',
                kelly_roi=round(cmp.get('kelly_roi_annual_pct',0),1),
                kelly_sharpe=round(cmp.get('kelly_sharpe_ratio',0),3),
                kelly_pf=round(cmp.get('kelly_profit_factor',0),2),
                kelly_wr=round(cmp.get('kelly_win_rate_pct',0),1),
                kelly_dd=round(cmp.get('kelly_max_dd_pct',-999),1),
                kelly_gross_dd=round(cmp.get('kelly_gross_dd_pct',-999),1),
                fixed_dd=round(cmp.get('fixed_max_dd_pct',-999),1),
                dd_saved=round(abs(cmp.get('fixed_max_dd_pct',0))-abs(cmp.get('kelly_max_dd_pct',0)),1),
                kelly_trades=int(cmp.get('kelly_total_trades',0)),
                kelly_better=cmp.get('kelly_better',False),
            )
            all_best.append(r)

            # Track best per strategy
            if best_for_strat is None or r['kelly_sharpe'] > best_for_strat['kelly_sharpe']:
                best_for_strat = r

            # Strict pass
            if (r['kelly_dd']>=STRICT['dd'] and r['kelly_sharpe']>=STRICT['sharpe'] and
                r['kelly_pf']>=STRICT['pf'] and r['kelly_roi']>=STRICT['roi'] and
                r['kelly_trades']>=STRICT['trades']):
                passed.append(r)
                print(f'  ✅ PASS {sym}: Sharpe={r["kelly_sharpe"]} DD={r["kelly_dd"]}% ROI={r["kelly_roi"]}%/yr', flush=True)

            # Near miss (relaxed but not strict)
            elif (r['kelly_dd']>=RELAX['dd'] and r['kelly_sharpe']>=RELAX['sharpe'] and
                  r['kelly_pf']>=RELAX['pf'] and r['kelly_roi']>=RELAX['roi'] and
                  r['kelly_trades']>=RELAX['trades']):
                near.append(r)
                print(f'  〰  NEAR {sym}: Sharpe={r["kelly_sharpe"]} DD={r["kelly_dd"]}% ROI={r["kelly_roi"]}%/yr', flush=True)

        except Exception as e:
            pass

# Sort
passed.sort(key=lambda x: (x['kelly_sharpe'], x['kelly_roi']), reverse=True)
near.sort(key=lambda x: (x['kelly_sharpe'], x['kelly_roi']), reverse=True)

# Save
out = Path('storage/reports/strategy_discovery')
out.mkdir(parents=True, exist_ok=True)

if passed:
    pd.DataFrame(passed).to_csv(out/'auto_shortlist.csv', index=False)

if all_best:
    df_all = pd.DataFrame(all_best).sort_values('kelly_sharpe', ascending=False)
    df_all.to_csv(out/'all_strategy_results.csv', index=False)

print('\n' + '='*110)
print(f'  FULL DISCOVERY RESULTS — {total} strategies × {len(files_4h)} symbols')
print('='*110)

print(f'\n✅ PASSED STRICT FILTERS ({len(passed)}) — Ready for paper window consideration:')
if passed:
    print(f'  {"Strategy":<22} {"Symbol":<12} {"ROI%/yr":<9} {"Sharpe":<8} {"PF":<6} {"WR%":<7} {"KellyDD%":<10} {"GrossDD%":<10} {"FixedDD%":<10} {"DD Saved":<10} {"Trades"}')
    print('  '+'-'*100)
    for r in passed:
        print(f'  {r["strategy"]:<22} {r["symbol"]:<12} {r["kelly_roi"]:<9} {r["kelly_sharpe"]:<8} {r["kelly_pf"]:<6} {r["kelly_wr"]:<7} {r["kelly_dd"]:<10} {r["kelly_gross_dd"]:<10} {r["fixed_dd"]:<10} {r["dd_saved"]:<10} {r["kelly_trades"]}')
else:
    print('  None')

print(f'\n〰  NEAR MISS ({len(near)}) — Close to passing, worth investigating:')
if near:
    print(f'  {"Strategy":<22} {"Symbol":<12} {"ROI%/yr":<9} {"Sharpe":<8} {"PF":<6} {"WR%":<7} {"KellyDD%":<10} {"GrossDD%":<10} {"FixedDD%":<10} {"DD Saved":<10} {"Trades"}')
    print('  '+'-'*100)
    for r in near[:15]:
        print(f'  {r["strategy"]:<22} {r["symbol"]:<12} {r["kelly_roi"]:<9} {r["kelly_sharpe"]:<8} {r["kelly_pf"]:<6} {r["kelly_wr"]:<7} {r["kelly_dd"]:<10} {r["kelly_gross_dd"]:<10} {r["fixed_dd"]:<10} {r["dd_saved"]:<10} {r["kelly_trades"]}')

# Best per strategy regardless
print(f'\n📊 BEST RESULT PER STRATEGY (all {total} strategies, best symbol):')
strat_best = {}
for r in all_best:
    k = r['strategy']
    if k not in strat_best or r['kelly_sharpe'] > strat_best[k]['kelly_sharpe']:
        strat_best[k] = r
ranked = sorted(strat_best.values(), key=lambda x: x['kelly_sharpe'], reverse=True)
print(f'  {"Strategy":<22} {"Symbol":<12} {"ROI%/yr":<9} {"Sharpe":<8} {"PF":<6} {"WR%":<7} {"KellyDD%":<10} {"FixedDD%":<10} {"DD Saved"}')
print('  '+'-'*100)
for r in ranked:
    flag = '✅' if r in passed else ('〰' if r in near else '  ')
    print(f'{flag} {r["strategy"]:<22} {r["symbol"]:<12} {r["kelly_roi"]:<9} {r["kelly_sharpe"]:<8} {r["kelly_pf"]:<6} {r["kelly_wr"]:<7} {r["kelly_dd"]:<10} {r["fixed_dd"]:<10} +{r["dd_saved"]}pp')

print('\n' + '='*110)
print(f'Saved: {out}/auto_shortlist.csv ({len(passed)} passed)')
print(f'Saved: {out}/all_strategy_results.csv ({len(all_best)} total results)')
