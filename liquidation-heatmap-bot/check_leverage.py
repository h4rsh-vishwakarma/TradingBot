#!/usr/bin/env python3
"""Check current position leverage and margin details."""

import json
from binance.client import Client

# Load credentials
with open('credentials_multi_exchange.json', 'r') as f:
    creds = json.load(f)

binance_config = creds['binance']
client = Client(
    binance_config['api_key'],
    binance_config['api_secret'],
    testnet=binance_config.get('testnet', False)
)

# Get position info
symbol = 'BTCUSDT'
position = client.futures_position_information(symbol=symbol)[0]
account = client.futures_account()

position_amt = float(position['positionAmt'])
entry_price = float(position['entryPrice'])
mark_price = float(position['markPrice'])
leverage = int(position.get('leverage', 0))
margin_type = position.get('marginType', 'CROSS')
liquidation_price = float(position.get('liquidationPrice', 0))
unrealized_pnl = float(position['unRealizedProfit'])

# Get leverage from account if not in position
if leverage == 0:
    leverage_brackets = client.futures_leverage_bracket(symbol=symbol)
    if leverage_brackets:
        leverage = leverage_brackets[0].get('initialLeverage', 1)

notional_value = abs(position_amt * mark_price)

wallet_balance = float(account['totalWalletBalance'])
available_balance = float(account['availableBalance'])
used_margin = float(account['totalInitialMargin'])

print("=" * 70)
print("POSITION DETAILS")
print("=" * 70)
print(f"Position Size: {position_amt:.4f} BTC")
print(f"Entry Price: ${entry_price:,.2f}")
print(f"Mark Price: ${mark_price:,.2f}")
print(f"Notional Value: ${notional_value:,.2f}")
print(f"\nLeverage: {leverage}x")
print(f"Margin Type: {margin_type}")
print(f"Liquidation Price: ${liquidation_price:,.2f}")
print(f"Unrealized P&L: ${unrealized_pnl:,.2f}")

print("\n" + "=" * 70)
print("ACCOUNT MARGIN")
print("=" * 70)
print(f"Wallet Balance: ${wallet_balance:,.2f}")
print(f"Available Balance: ${available_balance:,.2f}")
print(f"Used Margin: ${used_margin:,.2f}")
print(f"Margin Usage: {(used_margin / wallet_balance * 100):.2f}%")

print("\n" + "=" * 70)
print("RISK METRICS")
print("=" * 70)
distance_to_liq = abs(mark_price - liquidation_price)
distance_pct = (distance_to_liq / mark_price) * 100
print(f"Distance to Liquidation: ${distance_to_liq:,.2f} ({distance_pct:.2f}%)")

# Calculate effective leverage based on margin used
effective_leverage = notional_value / wallet_balance if wallet_balance > 0 else 0
print(f"Effective Leverage: {effective_leverage:.2f}x")
print(f"Set Leverage: {leverage}x")
print("=" * 70)
