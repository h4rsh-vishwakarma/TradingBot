import requests
import json
import time
import random
import os
from dotenv import load_dotenv

load_dotenv()

# Webhook URL (Aapka local Flask server)
WEBHOOK_URL = "http://localhost:5000/webhook/tradingview"
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "default_secret")

def send_fake_signal(strategy_name, symbol):
    # Action ko random BUY ya SELL rakhte hain testing ke liye
    action = random.choice(["buy", "sell"])
    price = random.uniform(60000, 65000) if "BTC" in symbol else random.uniform(3000, 3500)
    
    payload = {
        "strategy_id": strategy_name,
        "symbol": symbol,
        "action": action,
        "quantity": 0.01,
        "price": round(price, 2),
        "secret": WEBHOOK_SECRET, # Authentication ke liye
        "signal_id": f"SIM-{int(time.time())}"
    }

    print(f"🚀 Sending {action.upper()} signal for {symbol}...")
    
    headers = {'Content-Type': 'application/json'}
    try:
        response = requests.post(WEBHOOK_URL, data=json.dumps(payload), headers=headers)
        if response.status_code in [200, 202]:
            print(f"✅ Success: {response.json()}")
        else:
            print(f"❌ Failed: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"🔥 Connection Error: {e}")

if __name__ == "__main__":
    # Test ke liye 3 signals bhejte hain
    strategies = ["BOLLINGER_BREAKOUT", "RSI_MEAN_REVERSION", "MACD_TREND"]
    
    for _ in range(3):
        strat = random.choice(strategies)
        send_fake_signal(strat, "BTCUSDT")
        time.sleep(2) # 2 second ka gap
