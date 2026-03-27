"""
Lighter.xyz DEX Client - same interface as BinanceClient/HyperliquidClient.
Zero-fee perpetual futures on Ethereum L2 ZK-rollup.
"""
import os, time, logging, asyncio
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

SYMBOL_TO_MARKET = {
    "ETHUSDT": 0, "ETHUSD": 0, "ETH": 0,
    "LINKUSDT": 1, "LINKUSD": 1, "LINK": 1,
    "UNIUSDT": 2, "UNIUSD": 2, "UNI": 2,
    "AAVEUSDT": 3, "AAVEUSD": 3, "AAVE": 3,
    "LDOUSDT": 4, "LDOUSD": 4, "LDO": 4,
}

class LighterClient:
    def __init__(self):
        self.url = os.getenv("LIGHTER_API_URL", "https://mainnet.lighter.xyz")
        self.account_index = int(os.getenv("LIGHTER_ACCOUNT_INDEX", "0"))
        api_key_index = int(os.getenv("LIGHTER_API_KEY_INDEX", "4"))
        api_private_key = os.getenv("LIGHTER_API_PRIVATE_KEY", "")
        self.allow_real = os.getenv("ALLOW_REAL_TRADES", "false").lower() == "true"
        if not api_private_key:
            logger.warning("LIGHTER_API_PRIVATE_KEY not set. Lighter disabled.")
            self.client = None
            return
        try:
            import lighter
            self.signer = lighter.SignerClient(
                url=self.url, account_index=self.account_index,
                api_private_keys={api_key_index: api_private_key})
            self.api_client = lighter.ApiClient()
            self.account_api = lighter.AccountApi(self.api_client)
            self.order_api = lighter.OrderApi(self.api_client)
            self.client = self.signer
            self._counter = int(time.time()) % 100000
            logger.info("Lighter.xyz connected | Account: %d" % self.account_index)
        except Exception as e:
            logger.error("Lighter init failed: %s" % e)
            self.client = None

    def _market_idx(self, symbol):
        s = symbol.upper().replace("_PREMIUM","").replace("_PERP","")
        idx = SYMBOL_TO_MARKET.get(s)
        if idx is None:
            idx = SYMBOL_TO_MARKET.get(s.replace("USDT","").replace("USD",""))
        return idx

    def _next_idx(self):
        self._counter += 1
        return self._counter

    def _scale(self, market_index):
        from lighter import SignerClient
        return SignerClient.ASSET_TO_TICKER_SCALE.get(market_index + 1, 1e8)

    def market_order(self, symbol, is_buy, quantity, price=0, signal_id=""):
        if not self.client:
            return {"status": "error", "msg": "Not initialized"}
        if not self.allow_real:
            logger.info("PAPER (Lighter): %s %s %s @ $%s" % ("BUY" if is_buy else "SELL", quantity, symbol, price))
            return {"status": "ok", "response": {"data": {"statuses": [{"filled": {"avgPx": str(price)}}]}}, "paper": True}
        mi = self._market_idx(symbol)
        if mi is None:
            return {"status": "error", "msg": "Unknown market: %s" % symbol}
        try:
            best = self.signer.get_best_price(mi, is_ask=(not is_buy))
            if best == 0 and price > 0:
                best = int(price * self._scale(mi))
            base = int(quantity * self._scale(mi))
            logger.info("Lighter: %s %s %s" % ("BUY" if is_buy else "SELL", quantity, symbol))
            tx, resp, err = self.signer.create_market_order(
                market_index=mi, client_order_index=self._next_idx(),
                base_amount=base, avg_execution_price=best, is_ask=(not is_buy))
            if err:
                return {"status": "error", "msg": str(err)}
            return {"status": "ok", "response": {"data": {"statuses": [{"filled": {"avgPx": str(price)}}]}},
                    "orderId": "LIGHTER_%d" % self._counter}
        except Exception as e:
            return {"status": "error", "msg": str(e)}

    def place_stop_loss(self, symbol, is_buy, quantity, entry_price, sl_pct=3.0):
        if not self.client: return {"status": "error", "msg": "Not initialized"}
        mi = self._market_idx(symbol)
        if mi is None: return {"status": "error", "msg": "Unknown market"}
        try:
            tp = entry_price * (1 - sl_pct/100) if is_buy else entry_price * (1 + sl_pct/100)
            s = self._scale(mi)
            tx, resp, err = self.signer.create_sl_order(
                market_index=mi, client_order_index=self._next_idx(),
                base_amount=int(quantity * s), trigger_price=int(tp * s),
                price=int(tp * s), is_ask=is_buy, reduce_only=True)
            if err: return {"status": "error", "msg": str(err)}
            logger.info("Lighter SL: %s @ $%.2f" % (symbol, tp))
            return {"status": "ok", "trigger_price": tp}
        except Exception as e:
            return {"status": "error", "msg": str(e)}

    def place_take_profit(self, symbol, is_buy, quantity, entry_price, tp_pct=5.0):
        if not self.client: return {"status": "error", "msg": "Not initialized"}
        mi = self._market_idx(symbol)
        if mi is None: return {"status": "error", "msg": "Unknown market"}
        try:
            tp = entry_price * (1 + tp_pct/100) if is_buy else entry_price * (1 - tp_pct/100)
            s = self._scale(mi)
            tx, resp, err = self.signer.create_tp_order(
                market_index=mi, client_order_index=self._next_idx(),
                base_amount=int(quantity * s), trigger_price=int(tp * s),
                price=int(tp * s), is_ask=is_buy, reduce_only=True)
            if err: return {"status": "error", "msg": str(err)}
            logger.info("Lighter TP: %s @ $%.2f" % (symbol, tp))
            return {"status": "ok", "trigger_price": tp}
        except Exception as e:
            return {"status": "error", "msg": str(e)}

    def cancel_all_orders(self):
        if not self.client: return {"status": "error"}
        try:
            from lighter import SignerClient
            tx, resp, err = self.signer.cancel_all_orders(
                time_in_force=SignerClient.CANCEL_ALL_TIF_IMMEDIATE,
                timestamp_ms=int(time.time() * 1000))
            if err: return {"status": "error", "msg": str(err)}
            return {"status": "ok"}
        except Exception as e:
            return {"status": "error", "msg": str(e)}

    def close_all_positions(self):
        if not self.client: return []
        self.cancel_all_orders()
        return []
