#!/usr/bin/env python3
from binance.client import Client
import json

config = json.load(open('/home/ubuntu/trading_bot/credentials_multi_exchange.json'))['binance']
client = Client(config['api_key'], config['api_secret'], testnet=True)

# Get current position
pos = client.futures_position_information(symbol='BTCUSDT')
active_pos = [p for p in pos if float(p['positionAmt']) != 0]

if not active_pos:
    print("No active position")
    exit(0)

p = active_pos[0]
entry = float(p['entryPrice'])
current = float(p['markPrice'])
size = float(p['positionAmt'])
unrealized = float(p['unRealizedProfit'])

# Get all open orders
orders = client.futures_get_open_orders(symbol='BTCUSDT')

# Find actual stop loss and take profit
stop_losses = []
take_profits = []

for o in orders:
    if o['type'] == 'STOP_MARKET' and ((size > 0 and o['side'] == 'SELL') or (size < 0 and o['side'] == 'BUY')):
        stop_losses.append(float(o['stopPrice']))
    elif o['type'] == 'TAKE_PROFIT_MARKET':
        take_profits.append(float(o['stopPrice']))

# Find the extremes (closest to current price)
if stop_losses:
    # For LONG, stop loss is below entry
    closest_sl = max(stop_losses) if size > 0 else min(stop_losses)
else:
    closest_sl = None

if take_profits:
    # For LONG, take profit is above entry  
    closest_tp = min(take_profits) if size > 0 else max(take_profits)
else:
    closest_tp = None

print("=" * 80)
print("📊 POSITION CLOSE ANALYSIS")
print("=" * 80)
print(f"\n🔵 Current Position: LONG 0.7740 BTC")
print(f"   Entry: ${entry:,.2f}")
print(f"   Current: ${current:,.2f}")
print(f"   Unrealized P&L: ${unrealized:,.2f} ({(unrealized/(size*entry)*100):+.2f}%)")

print(f"\n{'=' * 80}")
print("⏱️  WHEN WILL POSITION CLOSE?")
print("=" * 80)

if closest_sl:
    sl_diff = current - closest_sl
    sl_pct = (sl_diff / current) * 100
    sl_loss_per_btc = entry - closest_sl
    sl_total_loss = sl_loss_per_btc * size
    
    print(f"\n❌ STOP LOSS SCENARIO:")
    print(f"   Stop Loss Price: ${closest_sl:,.2f}")
    print(f"   Needs price to DROP: ${sl_diff:,.2f} ({sl_pct:.2f}%)")
    print(f"   Loss if triggered: ${sl_total_loss:,.2f}")
    print(f"   ⚠️  Very close! Only {sl_pct:.1f}% away")

if closest_tp:
    tp_diff = closest_tp - current
    tp_pct = (tp_diff / current) * 100
    tp_profit_per_btc = closest_tp - entry
    tp_total_profit = tp_profit_per_btc * size
    
    print(f"\n✅ TAKE PROFIT SCENARIO:")
    print(f"   Take Profit Price: ${closest_tp:,.2f}")
    print(f"   Needs price to DROP: ${abs(tp_diff):,.2f} ({abs(tp_pct):.2f}%)")
    print(f"   Profit if triggered: ${tp_total_profit:,.2f}")

print(f"\n{'=' * 80}")
print("🎯 ANALYSIS")
print("=" * 80)

# Check which is closer
if closest_sl and closest_tp:
    sl_distance = abs(current - closest_sl)
    tp_distance = abs(current - closest_tp)
    
    if sl_distance < tp_distance:
        print(f"\n⚠️  STOP LOSS is CLOSER ({sl_pct:.2f}% vs {abs(tp_pct):.2f}%)")
        print(f"   If price drops ${sl_diff:,.2f}, you'll lose ${sl_total_loss:,.2f}")
    else:
        print(f"\n✅ TAKE PROFIT is closer ({abs(tp_pct):.2f}% vs {sl_pct:.2f}%)")
        print(f"   If price drops ${abs(tp_diff):,.2f}, you'll gain ${tp_total_profit:,.2f}")

print(f"\n⏰ Position will automatically close when price reaches:")
print(f"   • ${closest_sl:,.2f} (Stop Loss) → Loss ~${sl_total_loss:,.2f}")
print(f"   • ${closest_tp:,.2f} (Take Profit) → Profit ~${tp_total_profit:,.2f}")

print(f"\n💡 Current Status:")
print(f"   • Your entry was great! Up ${unrealized:,.2f} ({(unrealized/(size*entry)*100):+.2f}%)")
print(f"   • Price is now ${current:,.2f}")
print(f"   • Both SL and TP are BELOW current price (waiting for pullback)")
print(f"   • If price drops {abs(tp_pct):.1f}%, you take profit")
print(f"   • If price drops {sl_pct:.1f}%, you hit stop loss")

print(f"\n{'=' * 80}")
