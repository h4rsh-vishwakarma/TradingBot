#!/usr/bin/env python3
"""Check live Binance positions vs ledger for duplicates/drift."""
import os, sys, json
sys.path.insert(0, '/home/ubuntu/tradingview_webhook_bot')
os.chdir('/home/ubuntu/tradingview_webhook_bot/tradingview_webhook_bot')
from dotenv import load_dotenv
load_dotenv('/etc/tradingbot/env_vars', override=True)

from tradingview_webhook_bot.exchange.binance_client import BinanceClient

client = BinanceClient()
raw = client.get_open_positions()

print('=== LIVE BINANCE TESTNET POSITIONS (non-zero) ===')
live = {}
for p in raw:
    amt = float(p.get('positionAmt', 0))
    if abs(amt) > 0.0001:
        sym  = p['symbol']
        ep   = float(p.get('entryPrice', 0))
        upnl = float(p.get('unrealizedProfit', 0))
        side = 'LONG' if amt > 0 else 'SHORT'
        print(f'  {sym:<12} {side:<6} qty={amt:>10.4f}  entry={ep:>10.4f}  uPnL=${upnl:>8.4f}')
        live[sym] = {'qty': amt, 'entry': ep, 'upnl': upnl}

with open('/home/ubuntu/tradingview_webhook_bot/tradingview_webhook_bot/storage/ledger_state.json') as f:
    ledger = json.load(f)

print()
print('=== LEDGER vs LIVE COMPARISON ===')
print(f'  {"Symbol":<12}  {"LedgerQty":>10}  {"LiveQty":>10}  {"LedgerAvg":>10}  {"LiveEntry":>10}  {"LiveuPnL":>10}  {"Drift?"}')
print('  ' + '-'*85)

symbols_checked = set()
for key, pos in ledger.get('positions', {}).items():
    if ':' not in key:
        continue
    parts = key.split(':')
    if len(parts) != 2:
        continue
    exchange, sym = parts
    if exchange != 'binance' or sym in symbols_checked:
        continue
    symbols_checked.add(sym)
    ledger_qty = float(pos.get('quantity', 0) or 0)
    ledger_avg = float(pos.get('avg_price', 0) or 0)
    if abs(ledger_qty) < 0.0001:
        continue
    lv = live.get(sym, {})
    live_qty  = lv.get('qty', 0)
    live_entry = lv.get('entry', 0)
    live_upnl  = lv.get('upnl', 0)
    drift = abs(abs(ledger_qty) - abs(live_qty)) > 0.01
    flag = 'DRIFT!' if drift else 'OK'
    print(f'  {sym:<12}  {ledger_qty:>10.4f}  {live_qty:>10.4f}  {ledger_avg:>10.4f}  {live_entry:>10.4f}  ${live_upnl:>8.4f}  {flag}')

print()
print('=== ETH DEEP DIVE ===')
eth_keys = [(k, v) for k, v in ledger.get('positions', {}).items() if 'ETH' in k]
for k, v in eth_keys:
    q = float(v.get('quantity', 0) or 0)
    avg = float(v.get('avg_price', 0) or 0)
    rpnl = float(v.get('realized_pnl', 0) or 0)
    if abs(q) > 0 or abs(rpnl) > 0:
        print(f'  {k}: qty={q}  avg={avg}  realized_pnl={rpnl:.4f}')
eth_live = live.get('ETHUSDT', {})
print(f'  LIVE binance:ETHUSDT: qty={eth_live.get("qty", "N/A")}  uPnL=${eth_live.get("upnl", 0):.4f}')
