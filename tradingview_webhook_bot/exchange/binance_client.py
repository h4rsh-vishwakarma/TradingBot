import os
import logging
import time
import math
import requests
from binance.client import Client
from binance.exceptions import BinanceAPIException
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Standard project logger
logger = logging.getLogger("tradingview_webhook_bot.exchange")

# Quantity precision rules per symbol (stepSize from Binance exchangeInfo)
# Format: symbol -> (minQty, stepSize)
QUANTITY_RULES = {
    "BTCUSDT":  (0.001, 0.001),
    "ETHUSDT":  (0.001, 0.001),
    "SOLUSDT":  (0.01,  0.01),
    "BNBUSDT":  (0.01,  0.01),
    "XRPUSDT":  (0.1,   0.1),
    "DOGEUSDT": (1.0,   1.0),
    "ADAUSDT":  (0.1,   0.1),
    "AVAXUSDT": (0.01,  0.01),
    "DOTUSDT":  (0.1,   0.1),
    "LINKUSDT": (0.01,  0.01),
    "MATICUSDT":(0.1,   0.1),
    "LTCUSDT":  (0.001, 0.001),
}

def fix_quantity(symbol, quantity, price=None):
    """Adjust quantity to match Binance precision and minimum notional ($5) rules."""
    min_qty, step_size = QUANTITY_RULES.get(symbol, (0.001, 0.001))
    precision = max(0, int(round(-math.log10(step_size))))

    # Enforce minimum notional of $21 (Binance Futures USDT-M minimum is $20)
    if price and price > 0:
        min_notional_qty = 21.0 / price
        if quantity < min_notional_qty:
            quantity = min_notional_qty

    # Round UP to nearest step (to meet minimum)
    adjusted = math.ceil(quantity / step_size) * step_size
    adjusted = round(adjusted, precision)

    # Enforce minimum qty
    if adjusted < min_qty:
        adjusted = min_qty

    if adjusted != quantity:
        notional = adjusted * (price or 0)
        logger.info(f"📐 Qty adjusted: {quantity} -> {adjusted} (notional=${notional:.2f}) for {symbol}")

    return adjusted


class BinanceClient:
    """
    Hardened Binance Futures API Client (Task D Compliant).
    Supports: Mainnet Price Substitution & Absolute Path Env Loading.
    """

    def __init__(self, api_key=None, api_secret=None, testnet=None):
        # FIX: Explicitly load from our secure /etc/ path
        ENV_FILE_PATH = "/etc/tradingbot/env_vars"
        if os.path.exists(ENV_FILE_PATH):
            load_dotenv(dotenv_path=ENV_FILE_PATH)
        else:
            logger.error(f"❌ Critical Error: Env file not found at {ENV_FILE_PATH}")

        self.api_key = api_key or os.getenv('BINANCE_API_KEY')
        self.api_secret = api_secret or os.getenv('BINANCE_API_SECRET')
        self.mainnet_base = "https://fapi.binance.com"

        if testnet is not None:
            self.testnet = testnet
        else:
            self.testnet = os.getenv('BINANCE_TESTNET', 'true').lower() == 'true'

        self.allow_real = os.getenv("ALLOW_REAL_TRADES", "false").lower() == "true"

        try:
            self.client = Client(self.api_key, self.api_secret, testnet=self.testnet)
            self.client.futures_account_balance()
            mode = "TESTNET" if self.testnet else "LIVE"
            logger.info(f"✅ Connected to Binance Futures [{mode}] | Real Trades: {self.allow_real}")
        except Exception as e:
            logger.error(f"❌ Connection Failed: Check /etc/tradingbot/env_vars content. Error: {e}")
            raise

    def get_mainnet_mark_price(self, symbol):
        """SUB-TASK 1.1: Fetch Real Price from Mainnet"""
        try:
            url = f"{self.mainnet_base}/fapi/v1/premiumIndex"
            res = requests.get(url, params={"symbol": symbol}, timeout=5).json()
            return float(res['markPrice'])
        except Exception as e:
            logger.error(f"⚠️ Mainnet Price Fetch Error: {e}")
            return None

    def get_audit_data(self):
        try:
            positions = self.client.futures_position_information()
            audit_map = {}
            for pos in positions:
                amt = float(pos.get('positionAmt', 0))
                if amt != 0:
                    audit_map[pos['symbol']] = {
                        "quantity": amt,
                        "entry_price": float(pos.get('entryPrice', 0))
                    }
            return audit_map
        except Exception as e:
            logger.error(f"Failed to fetch audit data: {e}")
            return {}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ConnectionError, RuntimeError)),
        reraise=True
    )
    def execute_futures_order(self, symbol, side, quantity, price=None, order_type='MARKET', signal_id=None):
        """
        Execute order with MAINNET PRICE SUBSTITUTION.
        """
        if not self.allow_real:
            logger.warning(f"🚫 SAFETY GATE: Blocked {side} {quantity} {symbol} (Mode: Dry-Run)")
            return {"status": "SKIPPED", "msg": "SAFETY GATE: Real trades disabled"}

        # --- SUB-TASK 1.1: PRICE SUBSTITUTION ---
        mainnet_price = self.get_mainnet_mark_price(symbol)
        if mainnet_price:
            logger.info(f"⚖️ Substituting Signal Price {price} with Mainnet Price {mainnet_price}")
            price = mainnet_price

        try:
            # Fix quantity precision and minimum notional for this symbol
            quantity = fix_quantity(symbol, quantity, price=price)

            client_order_id = signal_id if signal_id else f"bot_{int(time.time())}"
            params = {
                "symbol": symbol,
                "side": side,
                "type": order_type,
                "quantity": quantity,
                "newClientOrderId": client_order_id
            }

            if order_type == 'LIMIT':
                params["price"] = str(price)
                params["timeInForce"] = "GTC"

            logger.info(f"🚀 Executing {order_type} {side} on {symbol} (ID: {client_order_id})...")
            response = self.client.futures_create_order(**params)
            response["status"] = "SUCCESS"
            logger.info(f"✅ Order Success: {response.get('orderId')}")
            return response

        except BinanceAPIException as e:
            logger.error(f"❌ Binance API Error: code={e.code} msg={e.message} status={getattr(e, 'status_code', 'N/A')}")
            if e.code == -2011:
                return {"status": "SKIPPED", "reason": "duplicate_id", "msg": e.message}
            status_code = getattr(e, 'status_code', 0)
            if status_code in [429, 500, 502, 503, 504]:
                raise RuntimeError(f"Transient Binance Failure: {e.message}")
            return {"status": "FAILED", "reason": "permanent", "msg": e.message}
        except Exception as e:
            if isinstance(e, RuntimeError):
                raise e
            logger.error(f"❌ Unexpected Execution Error: {e}")
            return {"status": "FAILED", "reason": "exception", "msg": str(e)}

    def place_stop_loss(self, symbol, side, quantity, entry_price, sl_pct=3.0, signal_id=None):
        """Place a stop-loss order after entry. sl_pct = stop distance in %."""
        if not self.allow_real:
            return {"status": "SKIPPED", "msg": "Dry-run mode"}
        try:
            # Stop side is opposite of entry
            stop_side = "SELL" if side == "BUY" else "BUY"
            if side == "BUY":
                stop_price = round(entry_price * (1 - sl_pct / 100), 2)
            else:
                stop_price = round(entry_price * (1 + sl_pct / 100), 2)

            quantity = fix_quantity(symbol, quantity, price=stop_price)
            params = {
                "symbol": symbol,
                "side": stop_side,
                "type": "STOP_MARKET",
                "stopPrice": str(stop_price),
                "quantity": quantity,
                "closePosition": "false",
                "newClientOrderId": f"SL_{signal_id}" if signal_id else f"SL_{int(time.time())}",
                "workingType": "MARK_PRICE"
            }
            logger.info(f"🛡️ Placing SL: {stop_side} {quantity} {symbol} @ ${stop_price} ({sl_pct}% from ${entry_price})")
            response = self.client.futures_create_order(**params)
            logger.info(f"✅ Stop-Loss placed: {response.get('orderId')}")
            return {"status": "SUCCESS", "orderId": response.get("orderId"), "stopPrice": stop_price}
        except BinanceAPIException as e:
            logger.error(f"❌ Stop-Loss Error: {e.message}")
            return {"status": "FAILED", "msg": e.message}
        except Exception as e:
            logger.error(f"❌ Stop-Loss Error: {e}")
            return {"status": "FAILED", "msg": str(e)}

    def close_all_positions(self):
        """Emergency kill switch: close ALL open futures positions."""
        closed = []
        try:
            positions = self.client.futures_position_information()
            for pos in positions:
                amt = float(pos.get('positionAmt', 0))
                if amt == 0:
                    continue
                symbol = pos['symbol']
                side = "SELL" if amt > 0 else "BUY"
                qty = abs(amt)
                try:
                    qty = fix_quantity(symbol, qty)
                    self.client.futures_create_order(
                        symbol=symbol, side=side, type="MARKET", quantity=qty,
                        newClientOrderId=f"KILL_{int(time.time())}_{symbol}"
                    )
                    logger.critical(f"🚨 KILLED: {side} {qty} {symbol}")
                    closed.append({"symbol": symbol, "side": side, "qty": qty})
                except Exception as e:
                    logger.error(f"❌ Failed to close {symbol}: {e}")
            # Cancel all open orders
            try:
                symbols_with_orders = set(o['symbol'] for o in self.client.futures_get_open_orders())
                for sym in symbols_with_orders:
                    self.client.futures_cancel_all_open_orders(symbol=sym)
                    logger.critical(f"🚨 Cancelled all orders for {sym}")
            except Exception as e:
                logger.error(f"❌ Failed to cancel orders: {e}")
        except Exception as e:
            logger.error(f"❌ Kill switch error: {e}")
        return closed

    def get_account_health(self):
        try:
            acc = self.client.futures_account()
            return {
                "available_balance": float(acc.get('availableBalance', 0)),
                "total_wallet_balance": float(acc.get('totalWalletBalance', 0)),
                "margin_ratio": float(acc.get('totalMaintMargin', 0)) / float(acc.get('totalMarginBalance', 1))
                if float(acc.get('totalMarginBalance', 0)) > 0 else 0
            }
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return None
