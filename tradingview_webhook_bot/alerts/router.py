import logging
import time
import requests
import os
import json
from typing import Optional, List

logger = logging.getLogger(__name__)

class AlertRouter:
    def __init__(self, alerts_log_path: str, telegram_token: Optional[str] = None):
        self.alerts_log_path = alerts_log_path
        self.telegram_token = telegram_token or os.getenv('TELEGRAM_BOT_TOKEN') or os.getenv('TELEGRAM_TOKEN')
        self.chat_id_system = os.getenv('TELEGRAM_CHAT_ID_SYSTEM') or os.getenv('TELEGRAM_CHAT_ID')
        self.chat_id_trades = os.getenv('TELEGRAM_CHAT_ID_TRADES') or self.chat_id_system

    def _append_jsonl(self, path: str, data: dict):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'a') as f:
                f.write(json.dumps(data) + '\n')
        except: pass

    def send(self, message: str, severity: str = "INFO", strategy_id: Optional[str] = None, channel: str = "SYSTEM"):
        # Log to file
        self._append_jsonl(self.alerts_log_path, {"ts": time.time(), "msg": message})
        
        target_chat_id = self.chat_id_trades if channel == "TRADES" else self.chat_id_system
        
        if self.telegram_token and target_chat_id:
            # Clean formatting: No extra headers, just the message
            clean_message = message.replace('\\n', '\n').replace('**', '').replace('`', '')
            
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            payload = {
                "chat_id": target_chat_id,
                "text": clean_message
            }
            try:
                requests.post(url, json=payload, timeout=10)
            except Exception as e:
                logger.error(f"Telegram failed: {e}")
        return True

    def get_updates(self): return []
    def reply(self, text, channel="SYSTEM"): self.send(text, channel=channel)
