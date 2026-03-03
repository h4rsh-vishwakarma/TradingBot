"""
Alert Router (Enhanced for Multi-Channel Routing)
Handles centralized logging, dispatching of system alerts to multiple Telegram channels,
and polling for interactive commands.
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
    def __init__(self, alerts_log_path: str, telegram_token: Optional[str] = None):
        self.alerts_log_path = alerts_log_path
        self.telegram_token = telegram_token or os.getenv('TELEGRAM_TOKEN')
        
        # Load multiple Chat IDs from environment variables
        self.chat_id_system = os.getenv('TELEGRAM_CHAT_ID_SYSTEM') or os.getenv('TELEGRAM_CHAT_ID')
        self.chat_id_trades = os.getenv('TELEGRAM_CHAT_ID_TRADES')
        
        self.last_update_id = 0

    def _escape_markdown(self, text: str) -> str:
        """
        Escapes special characters for Telegram MarkdownV2 compatibility.
        """
        escape_chars = r'_[]()~`>#+-=|{}.!'
        return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

    def send(self, message: str, severity: str = "INFO", strategy_id: Optional[str] = None, channel: str = "SYSTEM"):
        """
        Dispatches alerts to JSONL logs and specific Telegram channels.
        'channel' parameter determines the destination (SYSTEM or TRADES).
        """
        alert_payload = {
            "timestamp": time.time(),
            "severity": severity,
            "strategy_id": strategy_id,
            "message": message,
            "channel": channel
        }

        append_jsonl(self.alerts_log_path, alert_payload)

        log_msg = f"[{severity}][{channel}] {message}"
        if severity == "CRITICAL":
            logger.error(log_msg)
        else:
            logger.info(log_msg)

        # Route to the correct Chat ID based on the requested channel
        target_chat_id = self.chat_id_trades if channel == "TRADES" else self.chat_id_system

        if self.telegram_token and target_chat_id:
            self._send_telegram(message, severity, target_chat_id)
        
        return True

    def _send_telegram(self, message: str, severity: str, target_chat_id: str):
        """
        Sends formatted Telegram alerts to the specified chat ID.
        """
        emoji = "ℹ️"
        if any(x in message for x in ["TRADE", "Executed", "Updated", "Success"]):
            emoji = "✅"
        elif severity == "WARNING":
            emoji = "⚠️"
        elif severity == "CRITICAL":
            emoji = "🚨"

        # Explicitly handle newline characters for clean rendering
        clean_message = message.replace('\\n', '\n')
        header = f"{emoji} *Bot Alert ({severity})*"
        formatted_text = f"{header}\n\n{clean_message}"

        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        payload = {
            "chat_id": target_chat_id,
            "text": formatted_text,
            "parse_mode": "Markdown"
        }

        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to send Telegram alert to {target_chat_id}: {e}")

    def get_updates(self) -> List[str]:
        """
        Polls for incoming Telegram commands. 
        Note: Currently monitors the SYSTEM channel for commands.
        """
        if not self.telegram_token or not self.chat_id_system:
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

                # Check if message comes from the authorized SYSTEM chat ID
                if str(message.get("chat", {}).get("id")) == str(self.chat_id_system):
                    text = message.get("text")
                    if text:
                        new_commands.append(text)

            return new_commands
        except Exception as e:
            logger.error(f"Error fetching Telegram updates: {e}")
            return []

    def reply(self, text: str, channel: str = "SYSTEM"):
        """
        Sends a reply to interactive commands on the specified channel.
        """
        target_chat_id = self.chat_id_trades if channel == "TRADES" else self.chat_id_system
        
        if not self.telegram_token or not target_chat_id:
            return

        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        payload = {
            "chat_id": target_chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }
        try:
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            logger.error(f"Failed to send Telegram reply to {target_chat_id}: {e}")
