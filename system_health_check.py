import os
import subprocess
import requests
import logging
from dotenv import load_dotenv
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

# Load Telegram Credentials from bot folder
BASE_DIR = Path("/home/ubuntu/Multi-Strategy-Crypto-Trading-Systems")
ENV_PATH = BASE_DIR / "tradingview-webhook-bot" / ".env"
load_dotenv(dotenv_path=ENV_PATH)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SERVICES = ["tv-webhook.service", "tv-engine.service"]

def send_telegram_alert(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logging.error("❌ Telegram credentials missing!")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        logging.error(f"❌ Failed to send Telegram alert: {e}")

def check_service_status(service_name):
    # Systemctl status check
    status = subprocess.run(["systemctl", "is-active", service_name], capture_output=True, text=True)
    return status.stdout.strip() == "active"

def run_health_check():
    issues = []
    for service in SERVICES:
        if not check_service_status(service):
            logging.warning(f"⚠️ Service DOWN: {service}")
            issues.append(service)
        else:
            logging.info(f"✅ Service OK: {service}")

    if issues:
        alert_msg = f"🚨 <b>BOT CRITICAL ALERT</b>\n\nThe following services are <b>DOWN</b> on your EC2 instance:\n"
        for issue in issues:
            alert_msg += f"- {issue}\n"
        alert_msg += "\n<i>Action: Please check sudo journalctl logs.</i>"
        send_telegram_alert(alert_msg)

if __name__ == "__main__":
    run_health_check()
