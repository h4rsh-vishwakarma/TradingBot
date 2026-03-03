import os
import subprocess
import requests
import logging
from dotenv import load_dotenv
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

# Paths
BASE_DIR = Path("/home/ubuntu/Multi-Strategy-Crypto-Trading-Systems")
ENV_PATH = BASE_DIR / "tradingview-webhook-bot" / ".env"
DLQ_FILE = BASE_DIR / "storage" / "dead_letter.jsonl"

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
    status = subprocess.run(["systemctl", "is-active", service_name], capture_output=True, text=True)
    return status.stdout.strip() == "active"

def check_dlq_status():
    """Returns alert message if DLQ has failed signals"""
    if DLQ_FILE.exists() and os.path.getsize(DLQ_FILE) > 0:
        with open(DLQ_FILE, 'r') as f:
            count = sum(1 for line in f)
        return f"⚠️ <b>DLQ ALERT:</b> {count} failed signals detected in Dead Letter Queue!"
    return None

def run_health_check():
    issues = []
    # 1. Check Services
    for service in SERVICES:
        if not check_service_status(service):
            logging.warning(f"⚠️ Service DOWN: {service}")
            issues.append(service)
    
    if issues:
        msg = "🚨 <b>BOT CRITICAL ALERT</b>\n\nServices DOWN:\n" + "\n".join([f"- {i}" for i in issues])
        send_telegram_alert(msg)

    # 2. Check DLQ
    dlq_msg = check_dlq_status()
    if dlq_msg:
        send_telegram_alert(dlq_msg)

if __name__ == "__main__":
    run_health_check()
