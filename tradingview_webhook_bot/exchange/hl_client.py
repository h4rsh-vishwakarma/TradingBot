import os
import logging
import eth_account
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants

logger = logging.getLogger("hl_client")

class HyperliquidClient:
    def __init__(self):
        # Env vars se credentials uthana
        self.address = os.getenv("HL_WALLET_ADDRESS")
        self.key = os.getenv("HL_PRIVATE_KEY")
        self.is_testnet = str(os.getenv("HL_IS_TESTNET", "True")).lower() == "true"
        
        # Initialize placeholders to avoid "AttributeError"
        self.info = None
        self.exchange = None
        
        if not self.address or not self.key:
            logger.error("❌ HL Credentials missing in /etc/tradingbot/env_vars!")
            return

        # Network Setup
        self.base_url = constants.TESTNET_API_URL if self.is_testnet else constants.MAINNET_API_URL
        
        try:
            # Initialize Account & SDK
            self.account = eth_account.Account.from_key(self.key)
            self.info = Info(self.base_url, skip_ws=True)
            self.exchange = Exchange(self.account, self.base_url, account_address=self.address)
            logger.info(f"✅ HL Client Initialized | Wallet: {self.address} | Network: {'Testnet' if self.is_testnet else 'Mainnet'}")
        except Exception as e:
            logger.error(f"❌ HL Initialization Error: {e}")

    def get_balance(self):
        """Safe USDC Balance check"""
        if not self.info:
            logger.error("⚠️ Cannot fetch balance: HL Info client not initialized.")
            return 0.0
            
        try:
            user_state = self.info.user_state(self.address)
            
            # 1. Check withdrawable (Standard USDC)
            withdrawable = user_state.get('withdrawable', [])
            if withdrawable and len(withdrawable) > 0:
                return float(withdrawable[0])
            
            # 2. Fallback: Check Account Value (Margin Summary)
            margin_summary = user_state.get('marginSummary', {})
            account_value = margin_summary.get('accountValue', 0.0)
            return float(account_value)
            
        except Exception as e:
            logger.error(f"⚠️ Balance Fetch Error: {e}")
            return 0.0

    def market_order(self, coin, is_buy, size):
        if not self.exchange:
            logger.error("❌ HL Exchange client not initialized. Cannot trade.")
            return None
        try:
            # Get latest price for 1% slippage protection
            all_mids = self.info.all_mids()
            mid_price = float(all_mids.get(coin, 0))
            if mid_price == 0:
                logger.error(f"❌ Could not get price for {coin}")
                return None

            slippage = 0.01 
            limit_px = mid_price * (1 + slippage) if is_buy else mid_price * (1 - slippage)

            logger.info(f"🚀 HL Market Order -> {coin} | Side: {'BUY' if is_buy else 'SELL'} | Qty: {size} | Cap Px: {limit_px}")
            result = self.exchange.market_open(coin, is_buy, size, limit_px)
            return result
        except Exception as e:
            logger.error(f"🔥 HL Client Critical Error: {str(e)}")
            return {"status": "error", "message": str(e)}
