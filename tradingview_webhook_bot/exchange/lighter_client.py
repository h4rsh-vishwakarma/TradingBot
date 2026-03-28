"""
Lighter.xyz Exchange Client — Testnet/Mainnet support.
Same interface as BinanceClient for drop-in orchestrator integration.
"""
import os
import time
import logging
import asyncio
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

try:
    from lighter import SignerClient, Configuration, OrderApi, AccountApi, InfoApi
    LIGHTER_SDK_AVAILABLE = True
except ImportError:
    LIGHTER_SDK_AVAILABLE = False
    logger.warning("lighter-sdk not installed. Run: pip install lighter-sdk")

SYMBOL_MAP = {
    "ETHUSDT": "ETH-USDC",
    "BTCUSDT": "BTC-USDC",
    "SOLUSDT": "SOL-USDC",
    "LINKUSDT": "LINK-USDC",
    "AAVEUSDT": "AAVE-USDC",
    "UNIUSDT": "UNI-USDC",
}
REVERSE_SYMBOL_MAP = {v: k for k, v in SYMBOL_MAP.items()}


class LighterClient:
    """Lighter.xyz exchange client with same interface as BinanceClient."""

    def __init__(self):
        if not LIGHTER_SDK_AVAILABLE:
            raise ImportError("lighter-sdk not installed")

        self.api_url = os.getenv("LIGHTER_API_URL", "https://testnet.lighter.xyz")
        self.account_index = int(os.getenv("LIGHTER_ACCOUNT_INDEX", "0"))
        self.api_key_index = int(os.getenv("LIGHTER_API_KEY_INDEX", "4"))
        self.private_key = os.getenv("LIGHTER_PRIVATE_KEY", "")
        self.api_private_key = os.getenv("LIGHTER_API_PRIVATE_KEY", self.private_key)
        self.allow_real = os.getenv("ALLOW_REAL_TRADES", "false").lower() == "true"

        if not self.private_key:
            raise ValueError("LIGHTER_PRIVATE_KEY not set in env_vars")

        if not self.private_key.startswith("0x"):
            self.private_key = "0x" + self.private_key
        if self.api_private_key and not self.api_private_key.startswith("0x"):
            self.api_private_key = "0x" + self.api_private_key

        self.is_testnet = "testnet" in self.api_url.lower()

        try:
            api_keys = {self.api_key_index: self.api_private_key}
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self.signer = SignerClient(
                url=self.api_url,
                account_index=self.account_index,
                api_private_keys=api_keys,
            )
            self.config = Configuration(host=self.api_url)
            self.order_api = OrderApi(configuration=self.config)
            self.account_api = AccountApi(configuration=self.config)
            self.info_api = InfoApi(configuration=self.config)

            mode = "TESTNET" if self.is_testnet else "MAINNET"
            logger.info("Connected to Lighter [%s] | Account: %d", mode, self.account_index)
        except Exception as e:
            logger.error("Lighter connection failed: %s", e)
            raise

    def _to_lighter_symbol(self, symbol):
        return SYMBOL_MAP.get(symbol, symbol)

    def execute_futures_order(self, symbol, side, quantity, price=None, order_type='MARKET', signal_id=None):
        lighter_symbol = self._to_lighter_symbol(symbol)
        if not self.allow_real:
            sim_id = "LIGHTER_PAPER_%s" % (signal_id or int(time.time()))
            logger.info("PAPER TRADE [Lighter]: %s %s %s @ $%s", side, quantity, lighter_symbol, price)
            return {"status": "SUCCESS", "orderId": sim_id, "avg_price": price, "paper": True, "exchange": "lighter"}

        try:
            is_buy = side.upper() == "BUY"
            logger.info("Executing %s %s %s on Lighter", side, quantity, lighter_symbol)
            result = self.signer.create_market_order(
                order_book_symbol=lighter_symbol,
                size=str(quantity),
                is_buy=is_buy,
            )
            if result:
                logger.info("Lighter order: %s", result)
                return {"status": "SUCCESS", "orderId": str(result), "avg_price": price, "exchange": "lighter"}
            return {"status": "FAILED", "reason": "permanent", "msg": "Empty result", "exchange": "lighter"}
        except Exception as e:
            logger.error("Lighter execution error: %s", e)
            return {"status": "FAILED", "reason": "permanent", "msg": str(e), "exchange": "lighter"}

    def place_stop_loss(self, symbol, side, quantity, entry_price, sl_pct=3.0, signal_id=None):
        if not self.allow_real:
            return {"status": "SKIPPED", "msg": "Paper mode"}
        lighter_symbol = self._to_lighter_symbol(symbol)
        stop_side = not (side.upper() == "BUY")
        if side.upper() == "BUY":
            stop_price = round(entry_price * (1 - sl_pct / 100), 2)
        else:
            stop_price = round(entry_price * (1 + sl_pct / 100), 2)
        try:
            self.signer.create_sl_order(order_book_symbol=lighter_symbol, size=str(quantity),
                trigger_price=str(stop_price), is_buy=stop_side)
            logger.info("Lighter SL: %s @ $%s", lighter_symbol, stop_price)
            return {"status": "SUCCESS", "stopPrice": stop_price}
        except Exception as e:
            logger.error("Lighter SL error: %s", e)
            return {"status": "FAILED", "msg": str(e)}

    def place_take_profit(self, symbol, side, quantity, entry_price, tp_pct=5.0, signal_id=None):
        if not self.allow_real:
            return {"status": "SKIPPED", "msg": "Paper mode"}
        lighter_symbol = self._to_lighter_symbol(symbol)
        tp_side = not (side.upper() == "BUY")
        if side.upper() == "BUY":
            tp_price = round(entry_price * (1 + tp_pct / 100), 2)
        else:
            tp_price = round(entry_price * (1 - tp_pct / 100), 2)
        try:
            self.signer.create_tp_order(order_book_symbol=lighter_symbol, size=str(quantity),
                trigger_price=str(tp_price), is_buy=tp_side)
            logger.info("Lighter TP: %s @ $%s", lighter_symbol, tp_price)
            return {"status": "SUCCESS", "tpPrice": tp_price}
        except Exception as e:
            logger.error("Lighter TP error: %s", e)
            return {"status": "FAILED", "msg": str(e)}

    def close_all_positions(self):
        try:
            result = self.signer.cancel_all_orders()
            logger.critical("Lighter: All orders cancelled: %s", result)
            return [{"exchange": "lighter", "action": "cancel_all"}]
        except Exception as e:
            logger.error("Lighter cancel all failed: %s", e)
            return []

    def get_account_info(self):
        try:
            from lighter.models import ReqGetAccount
            account = self.account_api.get_account(ReqGetAccount(account_index=str(self.account_index)))
            return {"account_index": self.account_index, "data": account.to_dict() if account else {}}
        except Exception as e:
            logger.error("Lighter account error: %s", e)
            return None

    def get_supported_markets(self):
        try:
            orderbooks = self.info_api.get_order_books()
            return [str(ob) for ob in (orderbooks.order_books or [])] if orderbooks else []
        except Exception as e:
            logger.error("Lighter markets error: %s", e)
            return []


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from dotenv import load_dotenv
    load_dotenv("/etc/tradingbot/env_vars")
    try:
        client = LighterClient()
        print("Connected!")
        print("Markets:", client.get_supported_markets())
        client.allow_real = False
        print("Paper trade:", client.execute_futures_order("ETHUSDT", "BUY", 0.01, 2000))
    except Exception as e:
        print("Error: %s" % e)
