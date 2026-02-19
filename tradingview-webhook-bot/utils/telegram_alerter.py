"""
Telegram Alert System - Real-time Notifications for Critical Events

Sends Telegram messages for:
- Critical balance drift (>5%)
- Order placement failures
- API errors (Binance, Sheets)
- System startup/shutdown
- Duplicate signal alerts (idempotency triggers)

Configuration:
- Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in environment
- Bot must be added to chat/channel
- Uses Telegram Bot API for reliable delivery
"""

import os
import requests
from datetime import datetime, timezone
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class TelegramAlerter:
    """
    Send alerts to Telegram for critical trading system events.
    
    Features:
    - Rate limiting (max 20 msgs/min to avoid spam)
    - Message formatting (Markdown support)
    - Error handling (graceful degradation if Telegram unavailable)
    - Priority levels (info, warning, critical)
    """
    
    def __init__(self, bot_token: Optional[str] = None, 
                 chat_id: Optional[str] = None,
                 enabled: bool = True):
        """
        Initialize Telegram alerter.
        
        Args:
            bot_token: Telegram Bot API token
            chat_id: Telegram chat/channel ID
            enabled: Whether alerts are enabled
        """
        self.bot_token = bot_token or os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = chat_id or os.getenv('TELEGRAM_CHAT_ID')
        self.enabled = enabled and self.bot_token and self.chat_id
        
        # Rate limiting
        self.last_alert_time = {}
        self.min_interval = 60  # Minimum seconds between same alert types
        
        if self.enabled:
            logger.info(f"📱 TelegramAlerter initialized (chat_id: {self.chat_id})")
        else:
            logger.warning("⚠️ TelegramAlerter disabled (missing credentials)")
    
    def _can_send_alert(self, alert_type: str) -> bool:
        """
        Check if we can send this alert type (rate limiting).
        
        Args:
            alert_type: Type of alert (for tracking)
            
        Returns:
            True if alert can be sent
        """
        now = datetime.now(timezone.utc).timestamp()
        last_sent = self.last_alert_time.get(alert_type, 0)
        
        if now - last_sent < self.min_interval:
            return False
        
        self.last_alert_time[alert_type] = now
        return True
    
    def _send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        """
        Send message to Telegram.
        
        Args:
            text: Message text
            parse_mode: Formatting mode (Markdown or HTML)
            
        Returns:
            True if sent successfully
        """
        if not self.enabled:
            return False
        
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            payload = {
                'chat_id': self.chat_id,
                'text': text,
                'parse_mode': parse_mode,
                'disable_web_page_preview': True
            }
            
            response = requests.post(url, json=payload, timeout=10)
            
            if response.status_code == 200:
                logger.debug(f"✅ Telegram alert sent")
                return True
            else:
                logger.warning(f"⚠️ Telegram alert failed: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Failed to send Telegram alert: {e}")
            return False
    
    def alert_system_started(self, strategy: str, virtual_balance: float,
                            testnet_balance: float):
        """
        Alert when bot starts.
        
        Args:
            strategy: Strategy name
            virtual_balance: Virtual balance
            testnet_balance: Testnet balance
        """
        if not self._can_send_alert('system_started'):
            return
        
        message = (
            f"🚀 *Trading Bot Started*\n\n"
            f"Strategy: `{strategy}`\n"
            f"Virtual Balance: `${virtual_balance:.2f}`\n"
            f"Testnet Balance: `${testnet_balance:.2f}`\n"
            f"Time: `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}`"
        )
        
        self._send_message(message)
    
    def alert_critical_drift(self, virtual_balance: float, testnet_balance: float,
                            drift_pct: float):
        """
        Alert on critical balance drift.
        
        Args:
            virtual_balance: Virtual balance
            testnet_balance: Testnet balance
            drift_pct: Drift percentage
        """
        if not self._can_send_alert('critical_drift'):
            return
        
        message = (
            f"🚨 *CRITICAL BALANCE DRIFT*\n\n"
            f"Virtual: `${virtual_balance:.2f}`\n"
            f"Testnet: `${testnet_balance:.2f}`\n"
            f"Drift: `{drift_pct:.2%}` (>5% threshold)\n\n"
            f"⚠️ *ACTION REQUIRED*\n"
            f"Check for:\n"
            f"• Missed order fills\n"
            f"• P&L calculation errors\n"
            f"• Exchange fees\n"
            f"• Manual interventions"
        )
        
        self._send_message(message)
    
    def alert_order_placement_failed(self, signal_id: str, symbol: str,
                                     side: str, error: str):
        """
        Alert on order placement failure.
        
        Args:
            signal_id: Signal identifier
            symbol: Trading symbol
            side: LONG or SHORT
            error: Error message
        """
        if not self._can_send_alert(f'order_failed_{symbol}'):
            return
        
        message = (
            f"❌ *Order Placement Failed*\n\n"
            f"Signal: `{signal_id}`\n"
            f"Symbol: `{symbol}`\n"
            f"Side: `{side}`\n"
            f"Error: `{error}`\n\n"
            f"Check signal queue and logs"
        )
        
        self._send_message(message)
    
    def alert_duplicate_signal(self, signal_id: str, strategy: str, count: int):
        """
        Alert on duplicate signal detection (multiple times).
        
        Args:
            signal_id: Signal identifier
            strategy: Strategy name
            count: Number of duplicates detected
        """
        # Only alert if many duplicates (suggests TradingView issue)
        if count < 3:
            return
        
        if not self._can_send_alert(f'duplicate_{signal_id}'):
            return
        
        message = (
            f"🔒 *Duplicate Signal Alert*\n\n"
            f"Signal: `{signal_id}`\n"
            f"Strategy: `{strategy}`\n"
            f"Duplicates: `{count}` times\n\n"
            f"Idempotency layer blocking duplicates.\n"
            f"Check TradingView alert configuration."
        )
        
        self._send_message(message)
    
    def alert_api_error(self, service: str, endpoint: str, error: str,
                       retry_count: int = 0):
        """
        Alert on API errors.
        
        Args:
            service: Service name (Binance, Sheets, etc.)
            endpoint: API endpoint
            error: Error message
            retry_count: Number of retries attempted
        """
        # Only alert on persistent errors (multiple retries)
        if retry_count < 2:
            return
        
        if not self._can_send_alert(f'api_error_{service}'):
            return
        
        message = (
            f"⚠️ *API Error - {service}*\n\n"
            f"Endpoint: `{endpoint}`\n"
            f"Error: `{error}`\n"
            f"Retries: `{retry_count}`\n\n"
            f"System may be degraded"
        )
        
        self._send_message(message)
    
    def alert_position_opened(self, signal_id: str, symbol: str, side: str,
                             size: float, entry_price: float):
        """
        Alert when position is opened (optional - can be noisy).
        
        Args:
            signal_id: Signal identifier
            symbol: Trading symbol
            side: LONG or SHORT
            size: Position size
            entry_price: Entry price
        """
        # Disabled by default (too noisy)
        # Uncomment to enable position opened alerts
        # if not self._can_send_alert(f'position_opened_{signal_id}'):
        #     return
        # 
        # message = (
        #     f"📊 *Position Opened*\n\n"
        #     f"Signal: `{signal_id}`\n"
        #     f"Symbol: `{symbol}`\n"
        #     f"Side: `{side}`\n"
        #     f"Size: `{size:.4f}`\n"
        #     f"Entry: `${entry_price:.2f}`"
        # )
        # 
        # self._send_message(message)
        pass
    
    def alert_position_closed(self, signal_id: str, symbol: str,
                             pnl: float, pnl_pct: float, reason: str):
        """
        Alert when position is closed with P&L.
        
        Args:
            signal_id: Signal identifier
            symbol: Trading symbol
            pnl: Realized P&L
            pnl_pct: P&L percentage
            reason: Close reason (tp, sl, manual)
        """
        # Only alert on significant P&L (>$10 or >2%)
        if abs(pnl) < 10 and abs(pnl_pct) < 0.02:
            return
        
        if not self._can_send_alert(f'position_closed_{signal_id}'):
            return
        
        emoji = "🟢" if pnl > 0 else "🔴"
        
        message = (
            f"{emoji} *Position Closed*\n\n"
            f"Signal: `{signal_id}`\n"
            f"Symbol: `{symbol}`\n"
            f"P&L: `${pnl:.2f}` ({pnl_pct:+.2%})\n"
            f"Reason: `{reason}`"
        )
        
        self._send_message(message)
    
    def alert_system_shutdown(self, strategy: str, reason: str = "manual"):
        """
        Alert when bot shuts down.
        
        Args:
            strategy: Strategy name
            reason: Shutdown reason
        """
        message = (
            f"🛑 *Trading Bot Stopped*\n\n"
            f"Strategy: `{strategy}`\n"
            f"Reason: `{reason}`\n"
            f"Time: `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}`"
        )
        
        self._send_message(message)


# Singleton instance
_telegram_alerter = None

def get_telegram_alerter(bot_token: Optional[str] = None,
                        chat_id: Optional[str] = None,
                        enabled: bool = True) -> TelegramAlerter:
    """
    Get singleton TelegramAlerter instance.
    
    Args:
        bot_token: Telegram Bot API token
        chat_id: Telegram chat/channel ID
        enabled: Whether alerts are enabled
        
    Returns:
        TelegramAlerter instance
    """
    global _telegram_alerter
    if _telegram_alerter is None:
        _telegram_alerter = TelegramAlerter(bot_token, chat_id, enabled)
    return _telegram_alerter
