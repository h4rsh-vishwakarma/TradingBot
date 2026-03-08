import os
from dotenv import load_dotenv
import requests

load_dotenv()

token = os.getenv("TELEGRAM_TOKEN")
system_id = os.getenv("TELEGRAM_CHAT_ID_SYSTEM")
trade_id = os.getenv("TELEGRAM_CHAT_ID_TRADES")

def test_send(chat_id, label):
    if not chat_id:
        print(f"❌ {label} ID missing in .env")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": f"🚀 Test Message for {label}"}
    res = requests.post(url, json=payload)
    print(f"Result for {label}: {res.status_code} - {res.text}")

test_send(system_id, "SYSTEM GROUP")
test_send(trade_id, "TRADES GROUP")
