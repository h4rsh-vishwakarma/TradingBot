"""
Alert Router (Hardened for Day 5)
Handles centralized logging, dispatching of system alerts,
and polling for interactive Telegram commands with MarkdownV2 support.
"""

import logging
import time
import requests
import os
import re
from typing import Optional, List, Dict
from tradingview_webhook_bot.storage.jsonl_queue import append_jsonl

logger = logging.getLogger(__name__)

class AlertRouter:
    def __init__(self, alerts_log_path: str, telegram_token: Optional[str] = None, chat_id: Optional[str] = None):
        self.alerts_log_path = alerts_log_path
        self.telegram_token = telegram_token or os.getenv('TELEGRAM_TOKEN')
        self.chat_id = chat_id or os.getenv('TELEGRAM_CHAT_ID')
        self.last_update_id = 0 

    def _escape_markdown(self, text: str) -> str:
        """
        Day 5 Polish: Telegram MarkdownV2 ke liye special characters ko escape karta hai
        taaki formatting errors na aayein aur newline (\n) properly render ho.
        """
        # Sirf un characters ko escape karein jo Markdown syntax bigad sakte hain
        # Lekin humne symbols (like *) ko allow kiya hai formatting ke liye.
        escape_chars = r'_[]()~`>#+-=|{}.!'
        return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

    def send(self, message: str, severity: str = "INFO", strategy_id: Optional[str] = None):
        """Alerts ko JSONL aur Telegram par bhejta hai."""
        alert_payload = {
            "timestamp": time.time(),
            "severity": severity,
            "strategy_id": strategy_id,
            "message": message
        }

        append_jsonl(self.alerts_log_path, alert_payload)

        log_msg = f"[{severity}] {message}"
        if severity == "CRITICAL":
            logger.error(log_msg)
        else:
            logger.info(log_msg)

        if self.telegram_token and self.chat_id:
            self._send_telegram(message, severity)

        return True

    def _send_telegram(self, message: str, severity: str):
        """Day 5: Formatted Telegram alerts with fixed newline rendering."""
        emoji = "ℹ️"
        if any(x in message for x in ["TRADE", "Executed", "Updated", "Success"]):
            emoji = "✅"
        elif severity == "WARNING":
            emoji = "⚠️"
        elif severity == "CRITICAL":
            emoji = "🚨"

        # Markdown formatting polish
        # Hum \n ko explicitly replace karte hain taaki JSON payload mein error na aaye
        clean_message = message.replace('\\n', '\n') 
        header = f"{emoji} *Bot Alert ({severity})*"
        
        # MarkdownV2 requires escaping for non-formatted text
        formatted_text = f"{header}\n\n{clean_message}"

        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": formatted_text,
            "parse_mode": "Markdown" # MarkdownV2 zyaada strict hai, Markdown filhaal stable hai
        }

        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")

    def get_updates(self) -> List[str]:
        """Telegram commands fetch karta hai."""
        if not self.telegram_token:
            return []

        url = f"https://api.telegram.org/bot{self.telegram_token}/getUpdates"
        params = {"offset": self.last_update_id + 1, "timeout": 5}

        try:
            response = requests.get(url, params=params, timeout=10)
            data = response.json()

            if not data.get("ok"):
                return []

            new_commands = []
            for update in data.get("result", []):
                self.last_update_id = update["update_id"]
                message = update.get("message", {})

                if str(message.get("chat", {}).get("id")) == str(self.chat_id):
                    text = message.get("text")
                    if text:
                        new_commands.append(text)

            return new_commands
        except Exception as e:
            logger.error(f"Error fetching Telegram updates: {e}")
            return []

    def reply(self, text: str):
        """Interactive commands ka reply bhejta hai."""
        if not self.telegram_token or not self.chat_id:
            return

        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }
        try:
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            logger.error(f"Failed to send Telegram reply: {e}")
