import sys
import os
# Add path to your project
sys.path.append(os.getcwd())

from exchange.binance_client import BinanceClient

def verify_health():
    print("🔍 Starting Real-Time Health Verification...")
    client = BinanceClient()
    
    # 1. Test Mainnet Price Substitution
    price = client.get_mainnet_mark_price("BTCUSDT")
    if price:
        print(f"✅ Mainnet Substitution Working! BTC Price: ${price}")
    else:
        print("❌ Mainnet Price Fetch Failed!")

    # 2. Test Account Health (Testnet)
    health = client.get_account_health()
    if health:
        print(f"✅ Account Sync Working! Balance: {health['available_balance']}")
    else:
        print("❌ Account Health Sync Failed!")

if __name__ == "__main__":
    verify_health()
