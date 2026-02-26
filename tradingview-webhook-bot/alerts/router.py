"""
Alert Router
Handles centralized logging, dispatching of system alerts,
and polling for interactive Telegram commands.
"""

import logging
import time
import requests
import os
from typing import Optional, List, Dict
from tradingview_webhook_bot.storage.jsonl_queue import append_jsonl

logger = logging.getLogger(__name__)

class AlertRouter:
    def __init__(self, alerts_log_path: str, telegram_token: Optional[str] = None, chat_id: Optional[str] = None):
        self.alerts_log_path = alerts_log_path
        # Environment variables se credentials uthana sabse safe hai
        self.telegram_token = telegram_token or os.getenv('TELEGRAM_TOKEN')
        self.chat_id = chat_id or os.getenv('TELEGRAM_CHAT_ID')
        self.last_update_id = 0 # Naye messages track karne ke liye

    def send(self, message: str, severity: str = "INFO", strategy_id: Optional[str] = None):
        """
        Alerts ko local storage (JSONL) aur Telegram par dispatch karta hai.
        """
        alert_payload = {
            "timestamp": time.time(),
            "severity": severity,
            "strategy_id": strategy_id,
            "message": message
        }

        # 1. Audit trail ke liye local file mein save karein
        append_jsonl(self.alerts_log_path, alert_payload)

        # 2. Console logging
        log_msg = f"[{severity}] {message}"
        if severity == "CRITICAL":
            logger.error(log_msg)
        else:
            logger.info(log_msg)

        # 3. Agar credentials hain toh Telegram bhejein
        if self.telegram_token and self.chat_id:
            self._send_telegram(message, severity)

        return True

    def _send_telegram(self, message: str, severity: str):
        """Internal helper: Telegram API par formatted message bhejta hai."""
        emoji = "ℹ️"
        if "TRADE" in message or "Executed" in message or "Updated" in message:
            emoji = "✅"
        elif severity == "WARNING":
            emoji = "⚠️"
        elif severity == "CRITICAL":
            emoji = "🚨"

        formatted_text = f"{emoji} *Bot Alert ({severity})*\n\n{message}"

        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": formatted_text,
            "parse_mode": "Markdown"
        }

        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")

    # --- INTERACTIVE COMMAND METHODS ---

    def get_updates(self) -> List[Dict]:
        """
        Telegram se naye messages (commands) fetch karta hai.
        """
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

                # Security: Sirf AAPKE chat_id se aane wale messages sunein
                if str(message.get("chat", {}).get("id")) == str(self.chat_id):
                    text = message.get("text")
                    if text:
                        new_commands.append(text)

            return new_commands
        except Exception as e:
            logger.error(f"Error fetching Telegram updates: {e}")
            return []

    def reply(self, text: str):
        """Bina severity formatting ke seedha reply bhejne ke liye."""
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
