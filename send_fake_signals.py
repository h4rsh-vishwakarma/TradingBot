import requests
import time
import random

# Aapka Public IP
URL = "http://3.27.205.150/webhook/tradingview" 
SECRET = "squeeze_tradingview_cluster_2026_secure"

def send_signal():
    action = random.choice(["buy", "sell"])
    # FLAT STRUCTURE: No "payload" key
    data = {
        "secret": SECRET,
        "signal_id": f"STRESS_TEST_{int(time.time())}",
        "status": "received",
        "symbol": "BTCUSDT",
        "action": action,
        "quantity": 0.002,
        "price": 66000 + random.randint(-50, 50),
        "strategy": "Python_Stress_Test"
    }
    
    try:
        response = requests.post(URL, json=data, timeout=5)
        print(f"🚀 Sent: {action} | Status: {response.status_code} | Response: {response.text}")
    except Exception as e:
        print(f"❌ Connection Error: {e}")

if __name__ == "__main__":
    print("⏲️ Starting Fake Signal Loop (Every 20s)... Press Ctrl+C to stop.")
    while True:
        send_signal()
        time.sleep(20)
