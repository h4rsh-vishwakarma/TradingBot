import os
import time
import requests
from storage.jsonl_queue import append_jsonl

# Requirement 6.1: Rate limiting and local fallback
ALERTS_LOG = "storage/alerts.jsonl"
LAST_ALERT_TIME = {}
RATE_LIMIT_SECONDS = 60  # Only 1 alert per minute for the same issue

def send_alert(message, alert_key="general"):
    """
    Subtask 6.1: Implement alerts router with Telegram and local fallback.
    """
    global LAST_ALERT_TIME
    
    # Rate Limiting Logic
    current_time = time.time()
    if alert_key in LAST_ALERT_TIME and (current_time - LAST_ALERT_TIME[alert_key]) < RATE_LIMIT_SECONDS:
        return  # Skip if we sent this alert recently

    # 1. Local Logging (Requirement 6.1)
    alert_entry = {
        "timestamp": current_time,
        "message": message,
        "alert_key": alert_key
    }
    append_jsonl(ALERTS_LOG, alert_entry)
    
    # 2. Telegram Send (Subtask 6.3)
    # You will need to add these to your .env file
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if token and chat_id:
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = {"chat_id": chat_id, "text": f"🚨 *BOT ALERT*:\n{message}", "parse_mode": "Markdown"}
            requests.post(url, json=payload, timeout=5)
            LAST_ALERT_TIME[alert_key] = current_time
        except Exception as e:
            print(f"Telegram Failed: {e}")

if __name__ == "__main__":
    # Test: Subtask 6.3
    print("Testing Alert Router...")
    send_alert("Test Alert: System is operational!", "test_key")