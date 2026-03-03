import requests
import json
import time
import random
import os
from dotenv import load_dotenv

# Environment variables load karein
load_dotenv()

# Webhook Configuration
WEBHOOK_URL = "http://localhost:5000/webhook/tradingview"
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "default_secret")

def send_test_signal(strategy_name, symbol, action_type):
    """
    Simulates a signal with indicator values and specific actions (BUY/SELL/TP).
    """
    # Random Price and Indicator values for simulation
    price = round(random.uniform(62000, 65000), 2)
    rsi_val = round(random.uniform(30, 70), 2)
    ema_val = round(price - random.uniform(-5, 5), 2)

    # Note: Hum 'strategy_id' aur 'indicator' keys bhej rahe hain 
    # jo humne schemas.py aur orchestrator.py mein update kiye hain.
    payload = {
        "strategy_id": strategy_name,
        "symbol": symbol,
        "action": action_type, # 'buy', 'sell', or 'tp'
        "quantity": 0.05,
        "price": price,
        "indicator": f"RSI: {rsi_val} | EMA: {ema_val}",
        "secret": WEBHOOK_SECRET,
        "run_id": "TEST_SESSION_MARCH"
    }

    print(f"📡 Sending Simulated Signal: {action_type.upper()} for {symbol}...")

    headers = {'Content-Type': 'application/json'}
    try:
        response = requests.post(WEBHOOK_URL, data=json.dumps(payload), headers=headers, timeout=5)
        if response.status_code in [200, 202]:
            print(f"✅ Webhook Accepted: {response.json()}")
        else:
            print(f"❌ Webhook Rejected: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"🔥 Error connecting to server: {e}")

if __name__ == "__main__":
    print("🚀 Starting Signal Simulation...")
    print(f"🔗 Target URL: {WEBHOOK_URL}\n")

    # 1. Test a BUY Signal (Expected: 🟢 emoji)
    send_test_signal("EMA_CROSS_V2", "BTCUSDT", "buy")
    print("⏳ Waiting 5 seconds for processing...")
    time.sleep(5) 

    # 2. Test a SELL Signal (Expected: 🔴 emoji)
    send_test_signal("EMA_CROSS_V2", "BTCUSDT", "sell")
    print("⏳ Waiting 5 seconds for processing...")
    time.sleep(5)

    # 3. Test a TAKE PROFIT Signal (Expected: 🎯 emoji)
    send_test_signal("EMA_CROSS_V2", "BTCUSDT", "tp")

    print("\n✨ All test signals sent. Check your Telegram and Database!")

