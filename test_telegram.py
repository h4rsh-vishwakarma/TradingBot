import requests
import os
from dotenv import load_dotenv

load_dotenv()
token = os.getenv("TELEGRAM_TOKEN")
chat_id = os.getenv("TELEGRAM_CHAT_ID_TRADES")

url = f"https://api.telegram.org/bot{token}/sendMessage?chat_id={chat_id}&text=Hello_Harsh_System_Testing"
response = requests.get(url)
print(f"Status Code: {response.status_code}")
print(f"Response: {response.text}")
