#!/usr/bin/env python3
from binance.client import Client
import json

config = json.load(open('/home/ubuntu/trading_bot/credentials_multi_exchange.json'))['binance']
client = Client(config['api_key'], config['api_secret'], testnet=True)

# Get futures account info
acc = client.futures_account()
print("=" * 60)
print("FUTURES ACCOUNT INFO")
print("=" * 60)
print(f"totalWalletBalance: ${float(acc['totalWalletBalance']):,.2f}")
print(f"availableBalance: ${float(acc['availableBalance']):,.2f}")
print(f"totalUnrealizedProfit: ${float(acc['totalUnrealizedProfit']):,.2f}")
print(f"totalMarginBalance: ${float(acc['totalMarginBalance']):,.2f}")

# Get balance details
balance = client.futures_account_balance()
usdt = [b for b in balance if b['asset'] == 'USDT'][0]
print("\n" + "=" * 60)
print("USDT BALANCE BREAKDOWN")
print("=" * 60)
print(f"balance: ${float(usdt['balance']):,.2f}")
print(f"crossWalletBalance: ${float(usdt['crossWalletBalance']):,.2f}")
print(f"crossUnPnl: ${float(usdt['crossUnPnl']):,.2f}")
print(f"availableBalance: ${float(usdt['availableBalance']):,.2f}")

print("\n" + "=" * 60)
print("EXPLANATION")
print("=" * 60)
print("totalWalletBalance = balance + unrealized P&L")
print(f"${float(usdt['balance']):,.2f} + ${float(usdt['crossUnPnl']):,.2f} = ${float(usdt['balance']) + float(usdt['crossUnPnl']):,.2f}")
