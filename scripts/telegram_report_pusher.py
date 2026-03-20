import requests
import os
from datetime import datetime
from export_logs import export_to_csv

# Load credentials
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def push_report():
    summary, file_path = export_to_csv()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    # Executive Summary Text
    caption = (
        f"📊 *Executive Summary ({timestamp})*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📥 *Total Signals:* `{summary['total_signals']}`\n"
        f"✅ *Trades Filled:* `{summary['trades']}`\n"
        f"🚧 *Risk Blocks:* `{summary['blocks']}`\n"
        f"❌ *System Errors:* `{summary['errors']}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 *Target:* `1% Daily Check`\n"
        f"📂 _Detailed Audit Attached below._"
    )

    # Send Document
    url = f"https://api.telegram.org/bot{TOKEN}/sendDocument"
    with open(file_path, 'rb') as doc:
        files = {'document': doc}
        data = {'chat_id': CHAT_ID, 'caption': caption, 'parse_mode': 'Markdown'}
        response = requests.post(url, data=data, files=files)
        
    if response.status_code == 200:
        print("✅ Report pushed to Telegram successfully.")
    else:
        print(f"❌ Failed to push: {response.text}")

if __name__ == "__main__":
    push_report()
