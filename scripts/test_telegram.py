import os
import asyncio
from dotenv import load_dotenv
# Hum direct send_alert function ko import karenge
from alerts.router import send_alert 

async def test_alert():
    load_dotenv()
    
    print("🚀 Sending test alert to Telegram using send_alert function...")
    
    # Aapka function alert_key mangta hai, hum 'test_key' pass karenge
    # Note: Ye function sync hai (requests use karta hai), isliye await ki zaroorat nahi
    send_alert("Test Alert: Your TradingBot is connected to Windows!", "test_key")
    
    print("✅ Check your phone. If Token/ID are correct, you will see a notification.")

if __name__ == "__main__":
    asyncio.run(test_alert())