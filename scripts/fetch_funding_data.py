#!/usr/bin/env python3
"""
Funding Rate & Basis Data Fetcher
===================================
Delta-neutral lane data stream — Sainath framework Stream B.
Fetches from Binance USDT-M futures:
  - Funding rate history (8h intervals)
  - Perp vs spot basis/premium
  - Open interest (OI) snapshots

Outputs:
  storage/reports/funding_rates/{SYMBOL}_funding.csv
  storage/reports/funding_rates/funding_summary.json

Run: python3 scripts/fetch_funding_data.py [--symbols BTC ETH SOL XRP]
Cron: every 8 hours (aligned with funding payment)
"""
import os, json, sys, time, logging
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('funding')

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR   = PROJECT_ROOT / 'storage' / 'reports' / 'funding_rates'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT']
BINANCE_FAPI = 'https://fapi.binance.com/fapi/v1'
BINANCE_API  = 'https://api.binance.com/api/v3'
DAYS_HISTORY = 90   # 90 days of 8h funding = 270 records per symbol


def fetch_funding_history(symbol: str, days: int = 90) -> pd.DataFrame:
    """Fetch funding rate history from Binance USDT-M futures."""
    end_ms   = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = end_ms - days * 86_400_000
    url = f'{BINANCE_FAPI}/fundingRate'
    params = {'symbol': symbol, 'startTime': start_ms, 'endTime': end_ms, 'limit': 1000}
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        rows = r.json()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df['fundingTime'] = pd.to_datetime(df['fundingTime'].astype(int), unit='ms', utc=True)
        df['fundingRate'] = df['fundingRate'].astype(float)
        df['symbol'] = symbol
        return df[['symbol', 'fundingTime', 'fundingRate']]
    except Exception as e:
        log.warning(f'{symbol} funding history failed: {e}')
        return pd.DataFrame()


def fetch_mark_price(symbol: str) -> dict:
    """Fetch current mark price, index price, and basis."""
    try:
        r = requests.get(f'{BINANCE_FAPI}/premiumIndex', params={'symbol': symbol}, timeout=5)
        r.raise_for_status()
        d = r.json()
        return {
            'symbol':        symbol,
            'markPrice':     float(d.get('markPrice', 0)),
            'indexPrice':    float(d.get('indexPrice', 0)),
            'lastFundingRate': float(d.get('lastFundingRate', 0)),
            'nextFundingTime': d.get('nextFundingTime', 0),
            'basis_pct':     round((float(d.get('markPrice', 0)) / max(float(d.get('indexPrice', 1)), 1e-9) - 1) * 100, 4),
        }
    except Exception as e:
        log.warning(f'{symbol} mark price failed: {e}')
        return {}


def fetch_open_interest(symbol: str) -> float:
    """Fetch current open interest in USDT notional."""
    try:
        r = requests.get(f'{BINANCE_FAPI}/openInterest', params={'symbol': symbol}, timeout=5)
        r.raise_for_status()
        oi_contracts = float(r.json().get('openInterest', 0))
        price_r = requests.get(f'{BINANCE_FAPI}/ticker/price', params={'symbol': symbol}, timeout=5)
        price_r.raise_for_status()
        price = float(price_r.json().get('price', 0))
        return round(oi_contracts * price, 0)
    except Exception as e:
        log.warning(f'{symbol} open interest failed: {e}')
        return 0.0


def annualize_funding(df: pd.DataFrame) -> dict:
    """Compute annualized funding stats from history df."""
    if df.empty:
        return {}
    rates = df['fundingRate'].values
    avg_8h   = float(rates.mean())
    std_8h   = float(rates.std())
    pos_rate = float((rates > 0).mean())  # fraction of periods with positive funding (longs pay shorts)
    # 3 payments/day * 365 days
    ann_avg  = avg_8h * 3 * 365 * 100  # in %
    ann_vol  = std_8h * (3 * 365) ** 0.5 * 100
    return {
        'avg_8h_rate_pct':   round(avg_8h * 100, 5),
        'ann_funding_pct':   round(ann_avg, 2),
        'ann_vol_pct':       round(ann_vol, 2),
        'pct_periods_positive': round(pos_rate * 100, 1),
        'min_rate_pct':      round(float(rates.min()) * 100, 5),
        'max_rate_pct':      round(float(rates.max()) * 100, 5),
        'periods':           len(rates),
    }


def main():
    summary = {}
    for sym in SYMBOLS:
        log.info(f'Fetching {sym}...')
        df = fetch_funding_history(sym, DAYS_HISTORY)
        if not df.empty:
            out = OUTPUT_DIR / f'{sym}_funding.csv'
            df.to_csv(out, index=False)
            stats = annualize_funding(df)
        else:
            stats = {}

        mark = fetch_mark_price(sym)
        oi   = fetch_open_interest(sym)

        summary[sym] = {
            'funding_stats':   stats,
            'current_mark':    mark,
            'open_interest_usd': oi,
            'updated_at':      datetime.now(timezone.utc).isoformat(),
        }
        log.info(f'  {sym}: ann_funding={stats.get("ann_funding_pct","?")}%'
                 f', basis={mark.get("basis_pct","?")}%'
                 f', OI=${oi/1e9:.2f}B')
        time.sleep(0.3)

    # Write summary
    summary_path = OUTPUT_DIR / 'funding_summary.json'
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2)

    # Print readable table
    print('\n=== DELTA-NEUTRAL LANE DATA STREAM ===')
    print(f'{"Symbol":<12} {"Ann.Fund%":>10} {"Basis%":>8} {"OI($B)":>8} {"PosRatePct":>11}')
    print('-' * 55)
    for sym, d in summary.items():
        fs = d.get('funding_stats', {})
        mk = d.get('current_mark', {})
        oi_b = d.get('open_interest_usd', 0) / 1e9
        print(f'{sym:<12} {fs.get("ann_funding_pct",0):>10.2f} '
              f'{mk.get("basis_pct",0):>8.4f} {oi_b:>8.2f} '
              f'{fs.get("pct_periods_positive",0):>11.1f}')
    print(f'\nSummary saved: {summary_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
