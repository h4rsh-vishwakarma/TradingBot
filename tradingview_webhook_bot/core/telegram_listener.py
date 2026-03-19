import os, sys, time, requests
from pathlib import Path
from dotenv import load_dotenv

# Path Setup
FILE_PATH = Path(__file__).resolve()
PROJECT_ROOT = FILE_PATH.parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

ENV_VARS_PATH = "/etc/tradingbot/env_vars"
load_dotenv(dotenv_path=ENV_VARS_PATH, override=True)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OFFSET_FILE = "/tmp/tg_offset.txt"

def get_last_offset():
    if os.path.exists(OFFSET_FILE):
        with open(OFFSET_FILE, "r") as f: return int(f.read())
    return 0

def set_offset(offset):
    with open(OFFSET_FILE, "w") as f: f.write(str(offset))

def listen():
    print("🛰️ Telegram Listener Active... Waiting for /alpha command")
    offset = get_last_offset()
    
    while True:
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/getUpdates?offset={offset + 1}&timeout=30"
            resp = requests.get(url).json()
            
            if "result" in resp:
                for update in resp["result"]:
                    msg_text = update.get("message", {}).get("text", "")
                    chat_id = update.get("message", {}).get("chat", {}).get("id", "")
                    update_id = update.get("update_id")
                    
                    if msg_text == "/alpha":
                        print(f"🚀 Command Received: /alpha from {chat_id}")
                        # Trigger script_vault
                        os.system(f"python3 {PROJECT_ROOT}/tradingview_webhook_bot/core/script_vault.py")
                    
                    offset = update_id
                    set_offset(offset)
        except Exception as e:
            print(f"⚠️ Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    listen()
