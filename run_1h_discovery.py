#!/usr/bin/env python3
"""Full 26-strategy discovery on 1H data — with near-miss tracking."""
import os, sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, '/home/ubuntu/tradingview_webhook_bot')
os.chdir('/home/ubuntu/tradingview_webhook_bot')

import pandas as pd
import numpy as np
from pathlib import Path
from scripts.strategy_discovery_engine import BUILTIN_STRATEGIES, run_backtest_comparison

DATA_DIR = Path('storage/backtest_data')
OUT_DIR  = Path('storage/reports/strategy_discovery')
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 1H-adjusted thresholds
# Commission impact: 4H ~200 trades/yr → 1H ~600 trades/yr
# So minimum PF must be higher to overcome extra fees
STRICT = dict(dd=-20.0, sharpe=0.35, pf=1.30, roi=15.0, trades=50)
RELAX  = dict(dd=-30.0, sharpe=0.22, pf=1.10, roi=6.0,  trades=30)

# 1H SL/TP — tighter than 4H
SL_PCT = 0.010   # 1.0% (4H was 1.5%)
TP_PCT = 0.030   # 3.0% (4H was 6.0%)

files_1h = sorted(f for f in os.listdir(DATA_DIR) if f.endswith('_3y_1h.csv'))
total_strats = len(BUILTIN_STRATEGIES)

print(f'1H Discovery: {total_strats} strategies × {len(files_1h)} symbols = {total_strats*len(files_1h)} combos')
print(f'Strict filters: DD>{STRICT["dd"]}%, Sharpe>{STRICT["sharpe"]}, PF>{STRICT["pf"]}, ROI>{STRICT["roi"]}%/yr, Trades>={STRICT["trades"]}')
print(f'SL={SL_PCT*100}% TP={TP_PCT*100}%')
print()

passed, near, all_results = [], [], []

for i, (name, (fn, kwargs)) in enumerate(BUILTIN_STRATEGIES.items(), 1):
    print(f'[{i}/{total_strats}] {name}', flush=True)

    for fname in files_1h:
        sym = fname.replace('_3y_1h.csv', '')
        try:
            df = pd.read_csv(DATA_DIR / fname)
            df.columns = [c.lower() for c in df.columns]
            if not {'open','high','low','close'}.issubset(df.columns):
                continue
            days = max(int(len(df) / 24), 1)
            df['sig'] = fn(df, **kwargs)
            if (df['sig'] != 0).sum() < RELAX['trades']:
                continue
            cmp = run_backtest_comparison(
                df, signal_col='sig',
                sl_pct=SL_PCT, tp_pct=TP_PCT,
                leverage=2.0, total_days=days,
                min_trades=RELAX['trades']
            )
            if cmp is None:
                continue

            r = dict(
                strategy=name, symbol=sym, timeframe='1h',
                kelly_roi=round(cmp.get('kelly_roi_annual_pct', 0), 1),
                kelly_sharpe=round(cmp.get('kelly_sharpe_ratio', 0), 3),
                kelly_pf=round(cmp.get('kelly_profit_factor', 0), 2),
                kelly_wr=round(cmp.get('kelly_win_rate_pct', 0), 1),
                kelly_dd=round(cmp.get('kelly_max_dd_pct', -999), 1),
                kelly_gross_dd=round(cmp.get('kelly_gross_dd_pct', -999), 1),
                fixed_dd=round(cmp.get('fixed_max_dd_pct', -999), 1),
                dd_saved=round(abs(cmp.get('fixed_max_dd_pct', 0)) - abs(cmp.get('kelly_max_dd_pct', 0)), 1),
                kelly_trades=int(cmp.get('kelly_total_trades', 0)),
                fixed_roi=round(cmp.get('fixed_roi_annual_pct', 0), 1),
                fixed_sharpe=round(cmp.get('fixed_sharpe_ratio', 0), 3),
                kelly_better=cmp.get('kelly_better', False),
            )
            all_results.append(r)

            is_strict = (r['kelly_dd'] >= STRICT['dd'] and r['kelly_sharpe'] >= STRICT['sharpe'] and
                         r['kelly_pf'] >= STRICT['pf'] and r['kelly_roi'] >= STRICT['roi'] and
                         r['kelly_trades'] >= STRICT['trades'])
            is_near   = (not is_strict and
                         r['kelly_dd'] >= RELAX['dd'] and r['kelly_sharpe'] >= RELAX['sharpe'] and
                         r['kelly_pf'] >= RELAX['pf'] and r['kelly_roi'] >= RELAX['roi'] and
                         r['kelly_trades'] >= RELAX['trades'])

            if is_strict:
                passed.append(r)
                print(f'  ✅ PASS  {sym:<12} Sharpe={r["kelly_sharpe"]:.3f}  DD={r["kelly_dd"]:.1f}%  ROI={r["kelly_roi"]:.1f}%/yr  PF={r["kelly_pf"]:.2f}  Trades={r["kelly_trades"]}', flush=True)
            elif is_near:
                near.append(r)
                print(f'  〰  NEAR  {sym:<12} Sharpe={r["kelly_sharpe"]:.3f}  DD={r["kelly_dd"]:.1f}%  ROI={r["kelly_roi"]:.1f}%/yr  PF={r["kelly_pf"]:.2f}  Trades={r["kelly_trades"]}', flush=True)

        except Exception:
            pass

# ── Sort ──────────────────────────────────────────────────────────────────────
passed.sort(key=lambda x: (x['kelly_sharpe'], x['kelly_roi']), reverse=True)
near.sort(key=lambda x: (x['kelly_sharpe'], x['kelly_roi']), reverse=True)

# ── Save ──────────────────────────────────────────────────────────────────────
if passed:
    df_pass = pd.DataFrame(passed)
    df_pass.to_csv(OUT_DIR / 'shortlist_1h.csv', index=False)

if all_results:
    df_all = pd.DataFrame(all_results).sort_values('kelly_sharpe', ascending=False)
    df_all.to_csv(OUT_DIR / 'all_results_1h.csv', index=False)

# ── Best per strategy ─────────────────────────────────────────────────────────
strat_best = {}
for r in all_results:
    k = r['strategy']
    if k not in strat_best or r['kelly_sharpe'] > strat_best[k]['kelly_sharpe']:
        strat_best[k] = r
ranked = sorted(strat_best.values(), key=lambda x: x['kelly_sharpe'], reverse=True)

# ── Print results ─────────────────────────────────────────────────────────────
W = 120
print('\n' + '='*W)
print(f'  1H DISCOVERY RESULTS — {total_strats} strategies × {len(files_1h)} symbols')
print('='*W)

def print_table(rows, title):
    if not rows:
        print(f'\n{title}: None')
        return
    print(f'\n{title} ({len(rows)}):')
    hdr = f'  {"Strategy":<22} {"Symbol":<12} {"ROI%/yr":>8} {"Sharpe":>7} {"PF":>5} {"WR%":>6} {"KellyDD%":>9} {"GrossDD%":>9} {"FixedDD%":>9} {"DD Saved":>9} {"Trades":>7}'
    print(hdr)
    print('  ' + '-'*(W-2))
    for r in rows:
        print(f'  {r["strategy"]:<22} {r["symbol"]:<12} {r["kelly_roi"]:>8.1f} {r["kelly_sharpe"]:>7.3f} '
              f'{r["kelly_pf"]:>5.2f} {r["kelly_wr"]:>6.1f} {r["kelly_dd"]:>9.1f} {r["kelly_gross_dd"]:>9.1f} {r["fixed_dd"]:>9.1f} '
              f'{r["dd_saved"]:>+9.1f} {r["kelly_trades"]:>7}')

print_table(passed, '✅ PASSED STRICT (ready for paper window)')
print_table(near[:20], '〰  NEAR MISS (close to passing)')

print(f'\n📊 BEST PER STRATEGY — all {total_strats} strategies (best symbol on 1H):')
hdr2 = f'  {"":2} {"Strategy":<22} {"Symbol":<12} {"ROI%/yr":>8} {"Sharpe":>7} {"PF":>5} {"WR%":>6} {"KellyDD%":>9} {"FixedDD%":>9} {"DD Saved":>9}'
print(hdr2)
print('  ' + '-'*(W-2))
for r in ranked:
    flag = '✅' if r in passed else ('〰' if r in near else '  ')
    print(f'{flag} {r["strategy"]:<22} {r["symbol"]:<12} {r["kelly_roi"]:>8.1f} {r["kelly_sharpe"]:>7.3f} '
          f'{r["kelly_pf"]:>5.2f} {r["kelly_wr"]:>6.1f} {r["kelly_dd"]:>9.1f} {r["kelly_gross_dd"]:>9.1f} {r["fixed_dd"]:>9.1f} '
          f'{r["dd_saved"]:>+9.1f}')

print('\n' + '='*W)
print(f'Passed: {len(passed)} | Near miss: {len(near)} | Total tested: {len(all_results)}')
if passed:
    print(f'Saved: storage/reports/strategy_discovery/shortlist_1h.csv')
print(f'Full results: storage/reports/strategy_discovery/all_results_1h.csv')
