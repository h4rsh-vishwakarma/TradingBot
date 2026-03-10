import requests
import json
import uuid

URL = "http://127.0.0.1:5000/webhook/tradingview" 
SECRET = "squeeze_tradingview_cluster_2026_secure"

payload = {
    "signal_id": f"FINAL_SUCCESS_{uuid.uuid4().hex[:6]}",
    "secret": SECRET,
    "symbol": "BTCUSDT",
    "action": "BUY",
    "quantity": 0.003,  # Increased to meet $100 minimum notional
    "price": 60000.0,
    "strategy": "SMC_PRO_STABLE"
}

print(f"🚀 Sending High-Notional Signal to {URL}...")
response = requests.post(URL, json=payload)
print(f"📡 Status: {response.status_code} | Body: {response.text}")
