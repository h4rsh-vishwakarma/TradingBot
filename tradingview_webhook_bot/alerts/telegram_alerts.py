"""
Telegram alert system for critical trading events.
Sends formatted notifications for circuit breaker trips, errors, and important events.
"""

import html
import logging
import os
import re
import threading
import time
from enum import Enum
from typing import Dict, Optional

from datetime import timezone, timedelta
import requests

IST = timezone(timedelta(hours=5, minutes=30))

# Global send throttle — enforce min gap between Telegram API calls to avoid 429 bursts
_tg_send_lock = threading.Lock()
_tg_last_send_time = 0.0
_TG_MIN_SEND_INTERVAL = 0.5  # seconds between consecutive sends

logger = logging.getLogger(__name__)


class AlertSeverity(Enum):
    """Alert severity levels."""
    DEBUG = "🔍 DEBUG"
    INFO = "ℹ️ INFO"
    WARNING = "⚠️ WARNING"
    HIGH = "🔶 HIGH"
    CRITICAL = "🚨 CRITICAL"


class TelegramAlert:
    """Telegram bot for sending trading alerts."""
    
    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        """
        Initialize Telegram alerter.
        
        Args:
            bot_token: Telegram bot token (or use TELEGRAM_BOT_TOKEN env var)
            chat_id: Telegram chat ID (or use TELEGRAM_CHAT_ID env var)
        """
        self.bot_token = bot_token or os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = chat_id or os.getenv('TELEGRAM_CHAT_ID')
        self.enabled = bool(self.bot_token and self.chat_id)
        
        if not self.enabled:
            logger.warning("⚠️ Telegram alerts disabled: credentials not configured")
        else:
            logger.info(f"✅ Telegram alerts enabled for chat {self.chat_id[:8]}...")
        
        # Rate limiting
        self.last_alert_time = {}
        self.rate_limit_seconds = 60  # Don't spam same alert within 60s

    @staticmethod
    def _normalize_display_text(text: str) -> str:
        """Normalize Telegram-facing text for consistent presentation."""
        normalized = str(text or "").strip()
        if not normalized:
            return normalized

        normalized = html.unescape(normalized)
        for tag in ("<b>", "</b>", "<code>", "</code>", "<i>", "</i>"):
            normalized = normalized.replace(tag, "")

        replacements = [
            (r"\bBUY↔SELL\b", "LONG↔SHORT"),
            (r"\bSELL↔BUY\b", "SHORT↔LONG"),
            (r"\bBUY\b", "LONG"),
            (r"\bSELL\b", "SHORT"),
        ]
        for pattern, replacement in replacements:
            normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
        return normalized
    
    def _should_send(self, alert_key: str) -> bool:
        """Check if alert should be sent (rate limiting)."""
        if alert_key in self.last_alert_time:
            elapsed = time.time() - self.last_alert_time[alert_key]
            if elapsed < self.rate_limit_seconds:
                logger.debug(f"Rate limited: {alert_key} (sent {elapsed:.0f}s ago)")
                return False
        return True
    
    def send(self, severity: AlertSeverity, title: str, message: str, 
             alert_key: Optional[str] = None, force: bool = False) -> bool:
        """
        Send alert via Telegram.
        
        Args:
            severity: Alert severity level
            title: Alert title
            message: Alert message body
            alert_key: Unique key for rate limiting (optional)
            force: Force send even if rate limited
        
        Returns:
            True if sent successfully
        """
        if not self.enabled:
            logger.debug(f"Alert (disabled): [{severity.value}] {title}")
            return False
        
        # Rate limiting
        if alert_key and not force:
            if not self._should_send(alert_key):
                return False

        title = self._normalize_display_text(title)
        message = self._normalize_display_text(message)
        
        # Format message
        text = f"{severity.value}\n\n"
        text += f"{title}\n\n"
        text += message
        text += f"\n\nTime: {time.strftime('%Y-%m-%d %I:%M:%S %p IST', time.localtime(time.time() + 19800))}"
        
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            payload = {
                'chat_id': self.chat_id,
                'text': text,
                'parse_mode': 'HTML',
                'disable_web_page_preview': True
            }

            # Global throttle: enforce minimum gap between any two Telegram sends
            global _tg_last_send_time
            with _tg_send_lock:
                now = time.time()
                gap = now - _tg_last_send_time
                if gap < _TG_MIN_SEND_INTERVAL:
                    time.sleep(_TG_MIN_SEND_INTERVAL - gap)
                _tg_last_send_time = time.time()

            # Retry with backoff for HTTP 429 (rate limit)
            max_retries = 5
            for attempt in range(max_retries):
                response = requests.post(url, json=payload, timeout=15)

                if response.status_code == 200:
                    logger.info(f"Alert sent: {title}")
                    if alert_key:
                        self.last_alert_time[alert_key] = time.time()
                    return True
                elif response.status_code == 429:
                    # Telegram rate limit — extract retry_after, cap at 60s
                    try:
                        retry_after = min(response.json().get("parameters", {}).get("retry_after", 5), 60)
                    except Exception:
                        retry_after = 5
                    _tg_last_send_time = time.time() + retry_after
                    logger.warning(f"Rate limited (429). Retrying in {retry_after}s (attempt {attempt+1}/{max_retries})")
                    time.sleep(retry_after)
                else:
                    logger.error(f"Failed to send alert: HTTP {response.status_code}")
                    return False

            logger.error(f"Failed after {max_retries} retries (429 rate limit)")
            return False

        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")
            return False
    
    def circuit_breaker_tripped(self, reason: str, balance: float, loss_pct: float):
        """Alert: Circuit breaker tripped."""
        self.send(
            AlertSeverity.CRITICAL,
            "🛑 Circuit Breaker Tripped",
            f"<b>Reason:</b> {reason}\n"
            f"<b>Balance:</b> ${balance:.2f}\n"
            f"<b>Daily Loss:</b> {loss_pct:.2f}%\n\n"
            f"⏸️ Trading paused automatically",
            alert_key="circuit_breaker"
        )
    
    def position_stuck(self, signal_id: str, symbol: str, side: str, duration_seconds: float):
        """Alert: Position stuck in processing."""
        self.send(
            AlertSeverity.HIGH,
            "⏱️ Position Stuck",
            f"<b>Signal:</b> {signal_id}\n"
            f"<b>Symbol:</b> {symbol}\n"
            f"<b>Side:</b> {side}\n"
            f"<b>Duration:</b> {duration_seconds:.0f} seconds\n\n"
            f"Position may be stuck in processing state",
            alert_key=f"stuck_{signal_id}"
        )
    
    def no_signals_received(self, minutes: int):
        """Alert: No signals received for extended period."""
        self.send(
            AlertSeverity.HIGH,
            "📡 No Signals Received",
            f"No trading signals received for {minutes} minutes.\n\n"
            f"Check:\n"
            f"• TradingView webhook configuration\n"
            f"• Nginx/webhook service status\n"
            f"• SSL certificate validity",
            alert_key="no_signals",
            force=True  # Always send this one
        )
    
    def api_error_spike(self, error_count: int, window_minutes: int):
        """Alert: API errors spiking."""
        self.send(
            AlertSeverity.HIGH,
            "⚡ API Error Spike",
            f"<b>Errors:</b> {error_count} in {window_minutes} minutes\n\n"
            f"Exchange API may be experiencing issues.\n"
            f"Consider pausing trading temporarily.",
            alert_key="api_errors"
        )
    
    def position_opened(self, signal_id: str, symbol: str, side: str,
                       entry_price: float, position_size: float,
                       sl_price: float = 0.0, tp_price: float = 0.0):
        """Alert: Position opened with SL/TP (INFO level)."""
        trade_type = "Open Long" if side.upper() == "BUY" else "Open Short"
        emoji = "🟢" if side.upper() == "BUY" else "🔴"

        sl_tp = ""
        if sl_price > 0:
            sl_tp += f"<b>Stop-Loss:</b> ${sl_price:,.2f}\n"
        if tp_price > 0:
            sl_tp += f"<b>Take-Profit:</b> ${tp_price:,.2f}\n"

        self.send(
            AlertSeverity.INFO,
            f"{emoji} {trade_type}: {symbol}",
            f"<b>Type:</b> {trade_type}\n"
            f"<b>Entry:</b> ${entry_price:,.2f}\n"
            f"<b>Size:</b> {position_size} contracts\n"
            f"{sl_tp}"
            f"<b>Signal:</b> {signal_id}",
            alert_key=f"opened_{signal_id}"
        )
    
    def position_closed(self, symbol: str, side: str, exit_type: str,
                       pnl: float, balance: float):
        """Alert: Position closed with P&L."""
        # side is the closing side: SELL closes a long, BUY closes a short
        trade_type = "Close Long" if side.upper() == "SELL" else "Close Short"
        pnl_emoji = "✅" if pnl >= 0 else "❌"
        trade_emoji = "🔻" if side.upper() == "SELL" else "🔺"
        severity = AlertSeverity.INFO if pnl >= 0 else AlertSeverity.WARNING

        self.send(
            severity,
            f"{trade_emoji} {trade_type}: {symbol}",
            f"<b>Type:</b> {trade_type}\n"
            f"<b>Exit Reason:</b> {exit_type}\n"
            f"{pnl_emoji} <b>P&L:</b> ${pnl:.2f}\n"
            f"<b>New Balance:</b> ${balance:.2f}",
            alert_key=None
        )
    
    def daily_summary(self, stats: Dict):
        """Alert: Daily trading summary."""
        win_rate = (stats.get('winning_trades', 0) / max(1, stats.get('total_trades', 1))) * 100
        
        self.send(
            AlertSeverity.INFO,
            "📊 Daily Trading Summary",
            f"<b>Total Trades:</b> {stats.get('total_trades', 0)}\n"
            f"<b>Wins:</b> {stats.get('winning_trades', 0)}\n"
            f"<b>Losses:</b> {stats.get('losing_trades', 0)}\n"
            f"<b>Win Rate:</b> {win_rate:.1f}%\n"
            f"<b>Realized P&L:</b> ${stats.get('realized_pnl', 0):.2f}\n"
            f"<b>Balance:</b> ${stats.get('balance', 0):.2f}",
            alert_key="daily_summary",
            force=True
        )
    
    def bot_started(self, strategy: str, balance: float):
        """Alert: Bot started."""
        self.send(
            AlertSeverity.INFO,
            "🚀 Trading Bot Started",
            f"<b>Strategy:</b> {strategy}\n"
            f"<b>Balance:</b> ${balance:.2f}\n"
            f"<b>Status:</b> Ready for signals",
            alert_key=None
        )
    
    def bot_stopped(self, reason: str = "Manual shutdown"):
        """Alert: Bot stopped."""
        self.send(
            AlertSeverity.WARNING,
            "🛑 Trading Bot Stopped",
            f"<b>Reason:</b> {reason}",
            alert_key=None,
            force=True
        )
    
    def test_alert(self):
        """Send test alert to verify configuration."""
        return self.send(
            AlertSeverity.INFO,
            "🧪 Test Alert",
            "Telegram alerts are configured correctly!\n\n"
            "You will receive notifications for:\n"
            "• Circuit breaker trips\n"
            "• Stuck positions\n"
            "• API errors\n"
            "• Position opens/closes\n"
            "• Daily summaries",
            alert_key=None,
            force=True
        )


# Test function
def test_telegram_alerts():
    """Test Telegram alerts (requires credentials in environment)."""
    alerter = TelegramAlert()
    
    if not alerter.enabled:
        print("⚠️ Telegram credentials not configured")
        print("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables")
        return
    
    print("Sending test alert...")
    success = alerter.test_alert()
    
    if success:
        print("✅ Test alert sent successfully!")
    else:
        print("❌ Failed to send test alert")


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    test_telegram_alerts()
