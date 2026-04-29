#!/usr/bin/env python3
"""
Walk-Forward Analysis + Monte Carlo for top strategies.
Usage: python3 scripts/run_wfa_montecarlo.py
Output: storage/reports/wfa_results_YYYYMMDD.json
"""
import json, os, sys, random, math
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
import numpy as np

BASE_DIR   = Path(__file__).resolve().parent.parent
DATA_DIR   = BASE_DIR / 'storage' / 'backtest_data'
REPORT_DIR = BASE_DIR / 'storage' / 'reports'
REPORT_DIR.mkdir(parents=True, exist_ok=True)

# ── CONFIG ────────────────────────────────────────────────────────────────────
TOP_STRATEGIES = [
    {'name': 'CCI_Trend',     'symbol': 'ETHUSDT',  'tf': '4h', 'file': 'ETHUSDT_3y_4h.csv'},
    {'name': 'Donchian_EMA',  'symbol': 'ETHUSDT',  'tf': '4h', 'file': 'ETHUSDT_3y_4h.csv'},
    {'name': 'G28_SUI',       'symbol': 'SUIUSDT',  'tf': '4h', 'file': 'SUIUSDT_3y_4h.csv'},
    {'name': 'G94_Pivot',     'symbol': 'AVAXUSDT', 'tf': '4h', 'file': 'AVAXUSDT_3y_4h.csv'},
    {'name': 'Keltner_FIL',   'symbol': 'FILUSDT',  'tf': '4h', 'file': 'FILUSDT_3y_4h.csv'},
]

WFA_WINDOWS     = 6    # months per IS window
WFA_OOS_MONTHS  = 2    # months per OOS window
MC_RUNS         = 1000
MC_DD_THRESHOLD = 40.0  # reject if MC worst DD-95% > 40%


def load_csv(fname: str) -> pd.DataFrame:
    p = DATA_DIR / fname
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_csv(p, parse_dates=['timestamp'] if 'timestamp' in pd.read_csv(p, nrows=1).columns else None)
    if 'close' not in df.columns:
        for col in ['Close', 'CLOSE', 'price']:
            if col in df.columns:
                df.rename(columns={col: 'close'}, inplace=True)
                break
    return df


def simple_returns(df: pd.DataFrame, n_skip: int = 1) -> pd.Series:
    """Bar-by-bar returns as proxy for strategy equity curve."""
    if 'close' not in df.columns or len(df) < 10:
        return pd.Series(dtype=float)
    return df['close'].pct_change(n_skip).dropna()


def sharpe(rets: pd.Series, bars_per_year: float = 2190) -> float:
    if rets.std() == 0 or len(rets) < 5:
        return 0.0
    return float((rets.mean() / rets.std()) * math.sqrt(bars_per_year))


def max_drawdown(rets: pd.Series) -> float:
    equity = (1 + rets).cumprod()
    rolling_max = equity.cummax()
    dd = (equity - rolling_max) / rolling_max
    return float(dd.min() * 100)


def wfa(df: pd.DataFrame, is_months: int, oos_months: int) -> list:
    if df.empty or 'close' not in df.columns:
        return []
    df = df.copy().reset_index(drop=True)

    # Estimate bars per month
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        span_days = (df['timestamp'].iloc[-1] - df['timestamp'].iloc[0]).days
        bars_per_day = len(df) / max(span_days, 1)
    else:
        bars_per_day = 6  # 4h → 6 bars/day
    bars_per_month = int(bars_per_day * 30)

    window   = (is_months + oos_months) * bars_per_month
    step     = oos_months * bars_per_month
    results  = []

    for start in range(0, len(df) - window, step):
        is_end   = start + is_months * bars_per_month
        oos_end  = is_end + oos_months * bars_per_month
        is_df    = df.iloc[start:is_end]
        oos_df   = df.iloc[is_end:oos_end]
        if len(is_df) < 20 or len(oos_df) < 5:
            break
        is_rets  = simple_returns(is_df)
        oos_rets = simple_returns(oos_df)
        results.append({
            'is_sharpe':  round(sharpe(is_rets),  3),
            'oos_sharpe': round(sharpe(oos_rets), 3),
            'is_dd':      round(max_drawdown(is_rets),  2),
            'oos_dd':     round(max_drawdown(oos_rets), 2),
        })
    return results


def monte_carlo(rets: pd.Series, n_runs: int = 1000) -> dict:
    if len(rets) < 20:
        return {'mc_worst_dd_95': -999.0, 'mc_median_sharpe': 0.0}
    rets_arr = rets.values
    worst_dds = []
    sharpes   = []
    for _ in range(n_runs):
        shuffled = np.random.choice(rets_arr, size=len(rets_arr), replace=True)
        s = pd.Series(shuffled)
        worst_dds.append(max_drawdown(s))
        sharpes.append(sharpe(s))
    p95_dd = float(np.percentile(worst_dds, 5))   # 5th pct = worst tail
    return {
        'mc_worst_dd_95': round(p95_dd, 2),
        'mc_median_sharpe': round(float(np.median(sharpes)), 3),
        'mc_pass': abs(p95_dd) < MC_DD_THRESHOLD,
    }


def btc_regime_filter_test(strategy_df: pd.DataFrame, btc_df: pd.DataFrame) -> dict:
    """Simulate only trading when BTC close > BTC 50 EMA."""
    if btc_df.empty or strategy_df.empty:
        return {'regime_filtered': False, 'reason': 'missing data'}
    try:
        btc = btc_df.copy()
        btc['ema50'] = btc['close'].ewm(span=50, adjust=False).mean()
        btc['bull'] = btc['close'] > btc['ema50']
        # Align by index length (simplified — assumes same bar count)
        min_len = min(len(strategy_df), len(btc))
        strat_rets  = simple_returns(strategy_df.iloc[-min_len:])
        bull_mask   = btc['bull'].values[-min_len:]
        bull_mask   = bull_mask[1:]  # align after pct_change drops first row
        min_l2 = min(len(strat_rets), len(bull_mask))
        filtered_rets = strat_rets.values[:min_l2][bull_mask[:min_l2]]
        if len(filtered_rets) < 10:
            return {'regime_filtered': False, 'reason': 'insufficient bars after filter'}
        fs = pd.Series(filtered_rets)
        return {
            'regime_filtered': True,
            'filtered_sharpe': round(sharpe(fs), 3),
            'filtered_dd': round(max_drawdown(fs), 2),
            'pct_bars_traded': round(bull_mask[:min_l2].mean() * 100, 1),
        }
    except Exception as e:
        return {'regime_filtered': False, 'reason': str(e)}


def main():
    print("=== WFA + Monte Carlo + Regime Filter ===")
    btc_df = load_csv('BTCUSDT_3y_4h.csv')
    report = {'generated_at': datetime.now(timezone.utc).isoformat(), 'strategies': []}

    for strat in TOP_STRATEGIES:
        print(f"\n[{strat['name']} / {strat['symbol']}]")
        df = load_csv(strat['file'])
        if df.empty:
            print(f"  SKIP: no data file {strat['file']}")
            report['strategies'].append({'name': strat['name'], 'symbol': strat['symbol'], 'error': 'no data'})
            continue

        rets = simple_returns(df)

        # WFA
        wfa_windows = wfa(df, WFA_WINDOWS, WFA_OOS_MONTHS)
        if wfa_windows:
            oos_sharpes = [w['oos_sharpe'] for w in wfa_windows]
            wfa_summary = {
                'windows': len(wfa_windows),
                'avg_oos_sharpe': round(sum(oos_sharpes) / len(oos_sharpes), 3),
                'min_oos_sharpe': round(min(oos_sharpes), 3),
                'pct_positive_oos': round(sum(1 for s in oos_sharpes if s > 0) / len(oos_sharpes) * 100, 1),
            }
            print(f"  WFA: {wfa_summary['windows']} windows, avg OOS Sharpe={wfa_summary['avg_oos_sharpe']}, positive_OOS={wfa_summary['pct_positive_oos']}%")
        else:
            wfa_summary = {'error': 'insufficient data'}
            print("  WFA: insufficient data")

        # Monte Carlo
        mc = monte_carlo(rets, MC_RUNS)
        mc_status = "PASS" if mc.get('mc_pass', False) else "FAIL"
        print(f"  MC ({MC_RUNS} runs): worst_DD_95={mc['mc_worst_dd_95']}% → {mc_status}")

        # BTC Regime
        regime = btc_regime_filter_test(df, btc_df)
        if regime.get('regime_filtered'):
            print(f"  Regime filter: Sharpe={regime['filtered_sharpe']}, DD={regime['filtered_dd']}%, bars_traded={regime['pct_bars_traded']}%")
        else:
            print(f"  Regime filter: {regime.get('reason', 'N/A')}")

        report['strategies'].append({
            'name':    strat['name'],
            'symbol':  strat['symbol'],
            'wfa':     wfa_summary,
            'monte_carlo': mc,
            'regime_filter': regime,
        })

    # Save report
    out = REPORT_DIR / f"wfa_results_{datetime.now(timezone.utc).strftime('%Y%m%d')}.json"
    with open(out, 'w') as f:
        json.dump(report, f, indent=2)
    print(f"\n=== Report saved: {out} ===")

    # Summary table
    print("\n{'='*60}")
    print(f"{'Strategy':<22} {'OOS Sharpe':<12} {'MC DD-95%':<12} {'Regime Sharpe':<14} {'Status'}")
    print('-' * 72)
    for s in report['strategies']:
        oos = s.get('wfa', {}).get('avg_oos_sharpe', 'N/A')
        mc_dd = s.get('monte_carlo', {}).get('mc_worst_dd_95', 'N/A')
        rsh = s.get('regime_filter', {}).get('filtered_sharpe', 'N/A')
        mc_ok = s.get('monte_carlo', {}).get('mc_pass', False)
        status = 'APPROVED' if mc_ok else 'REVIEW'
        print(f"{s['name']:<22} {str(oos):<12} {str(mc_dd):<12} {str(rsh):<14} {status}")


if __name__ == '__main__':
    main()
