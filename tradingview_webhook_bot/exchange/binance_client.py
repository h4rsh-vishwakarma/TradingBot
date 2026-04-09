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
            self._load_exchange_info()
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

    def set_leverage(self, symbol: str, leverage: int) -> bool:
        """Set futures leverage for a symbol. Returns True on success."""
        if not self.allow_real:
            return True
        try:
            self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
            logger.info(f"⚙️ Leverage set: {symbol} → {leverage}x")
            return True
        except BinanceAPIException as e:
            # -4028 = leverage already set to this value — not a real error
            if e.code == -4028:
                return True
            logger.warning(f"⚠️ set_leverage failed for {symbol}: {e.message}")
            return False
        except Exception as e:
            logger.warning(f"⚠️ set_leverage error for {symbol}: {e}")
            return False

    def cancel_open_orders(self, symbol: str) -> bool:
        """Cancel ALL open orders (SL/TP) for a symbol. Call before placing a close/exit order."""
        if not self.allow_real:
            return True
        try:
            self.client.futures_cancel_all_open_orders(symbol=symbol)
            logger.info(f"🗑️ Cancelled all open orders for {symbol}")
            return True
        except BinanceAPIException as e:
            # -2011 means no open orders — not an error
            if e.code == -2011:
                return True
            logger.warning(f"⚠️ cancel_open_orders failed for {symbol}: {e.message}")
            return False
        except Exception as e:
            logger.warning(f"⚠️ cancel_open_orders error for {symbol}: {e}")
            return False

    def get_order_status(self, symbol: str, client_order_id: str) -> dict:
        """Query order status by clientOrderId — used after timeout to check if order filled."""
        try:
            resp = self.client.futures_get_order(symbol=symbol, origClientOrderId=client_order_id)
            return {
                "status": resp.get("status", "UNKNOWN"),  # NEW, FILLED, CANCELED, PARTIALLY_FILLED…
                "orderId": resp.get("orderId"),
                "avgPrice": float(resp.get("avgPrice", 0) or 0),
                "executedQty": float(resp.get("executedQty", 0) or 0),
            }
        except BinanceAPIException as e:
            if e.code == -2013:  # Order does not exist
                return {"status": "NOT_FOUND"}
            logger.warning(f"⚠️ get_order_status error for {symbol}/{client_order_id}: {e.message}")
            return {"status": "UNKNOWN"}
        except Exception as e:
            logger.warning(f"⚠️ get_order_status error: {e}")
            return {"status": "UNKNOWN"}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ConnectionError, RuntimeError)),
        reraise=True
    )
    def execute_futures_order(self, symbol, side, quantity, price=None, order_type='MARKET', signal_id=None):
        """
        Execute order with MAINNET PRICE SUBSTITUTION.
        Sets leverage before every real trade.
        USE_LIMIT_ORDERS=true → Post-only limit at mark price (maker fee 0.02% vs taker 0.04%).
        Falls back to MARKET if GTX rejected (price already crossed).
        On timeout, returns status=TIMEOUT with client_order_id so caller can verify fill.
        """
        # --- PRICE SUBSTITUTION (always, even paper mode) ---
        mainnet_price = self.get_mainnet_mark_price(symbol)
        if mainnet_price:
            logger.info(f"⚖️ Substituting Signal Price {price} with Mainnet Price {mainnet_price}")
            price = mainnet_price
        reference_price = float(price or 0.0) if price not in (None, "") else 0.0
        maker_fee_bps = float(os.getenv("BINANCE_MAKER_FEE_BPS", "2.0"))
        taker_fee_bps = float(os.getenv("BINANCE_TAKER_FEE_BPS", "4.0"))

        # --- AUTO LIMIT ORDER: saves ~0.02%/side vs market orders ---
        use_limit = os.getenv("USE_LIMIT_ORDERS", "false").lower() == "true"
        if use_limit and order_type == 'MARKET' and price:
            order_type = 'LIMIT_MAKER'   # will be converted to GTX below

        if not self.allow_real:
            # Paper trading: simulate fill at current mainnet price
            quantity = fix_quantity(symbol, quantity, price=price)
            sim_id = f"PAPER_{signal_id}" if signal_id else f"PAPER_{int(time.time())}"
            logger.info(f"📝 PAPER TRADE: {side} {quantity} {symbol} @ ${price} (ID: {sim_id})")
            return {
                "status": "SUCCESS",
                "orderId": sim_id,
                "avg_price": price,
                "paper": True,
                "msg": "Simulated fill",
                "reference_price": reference_price or float(price or 0.0),
                "order_type_used": "LIMIT_GTX" if use_limit else "MARKET",
                "estimated_fee_bps": maker_fee_bps if use_limit else taker_fee_bps
            }

        try:
            # Fix quantity precision and minimum notional for this symbol
            quantity = fix_quantity(symbol, quantity, price=price)

            # --- SET LEVERAGE before every entry ---
            leverage = int(os.getenv("TRADE_LEVERAGE", "1"))
            self.set_leverage(symbol, leverage)

            client_order_id = signal_id if signal_id else f"bot_{int(time.time())}"

            # --- BUILD ORDER PARAMS ---
            if order_type == 'LIMIT_MAKER':
                # Post-only limit at mark price → guaranteed maker fee (0.02%/side)
                # GTX = Good-Till-Crossing (post-only), rejected if it would cross book
                # Round price to symbol precision (8 decimal places max)
                price_str = str(round(float(price), 8)) if price else None
                if price_str:
                    params = {
                        "symbol": symbol, "side": side, "type": "LIMIT",
                        "quantity": quantity, "price": price_str,
                        "timeInForce": "GTX",   # Post-only
                        "newClientOrderId": client_order_id
                    }
                    logger.info(f"📌 POST-ONLY LIMIT {side} {symbol} @ {price_str} (maker fee)...")
                    try:
                        response = self.client.futures_create_order(**params)
                        response["status"] = "SUCCESS"
                        response["order_type_used"] = "LIMIT_GTX"
                        logger.info(f"✅ Post-only limit filled: {response.get('orderId')}")
                        return response
                    except BinanceAPIException as gtx_err:
                        # GTX rejected (would cross book) → fall back to market
                        logger.warning(f"⚠️ GTX rejected ({gtx_err.message}) → falling back to MARKET")
                        order_type = 'MARKET'
                else:
                    order_type = 'MARKET'

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
        except requests.exceptions.Timeout:
            # Order may or may not have been submitted — caller must verify via get_order_status()
            client_order_id = signal_id if signal_id else f"bot_{int(time.time())}"
            logger.warning(f"⏱️ Timeout placing order for {symbol} (ID: {client_order_id}) — status unknown")
            return {"status": "TIMEOUT", "client_order_id": client_order_id, "symbol": symbol}
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


    def place_take_profit(self, symbol, side, quantity, entry_price, tp_pct=5.0, signal_id=None):
        """Place a take-profit order after entry. tp_pct = profit distance in %."""
        if not self.allow_real:
            return {"status": "SKIPPED", "msg": "Dry-run mode"}
        try:
            tp_side = "SELL" if side == "BUY" else "BUY"
            if side == "BUY":
                tp_price = round(entry_price * (1 + tp_pct / 100), 2)
            else:
                tp_price = round(entry_price * (1 - tp_pct / 100), 2)

            quantity = fix_quantity(symbol, quantity, price=tp_price)
            params = {
                "symbol": symbol,
                "side": tp_side,
                "type": "TAKE_PROFIT_MARKET",
                "stopPrice": str(tp_price),
                "quantity": quantity,
                "closePosition": "false",
                "newClientOrderId": f"TP_{signal_id}" if signal_id else f"TP_{int(time.time())}",
                "workingType": "MARK_PRICE"
            }
            logger.info(f"🎯 Placing TP: {tp_side} {quantity} {symbol} @ ${tp_price} ({tp_pct}% from ${entry_price})")
            response = self.client.futures_create_order(**params)
            logger.info(f"✅ Take-Profit placed: {response.get('orderId')}")
            return {"status": "SUCCESS", "orderId": response.get("orderId"), "tpPrice": tp_price}
        except BinanceAPIException as e:
            logger.error(f"❌ Take-Profit Error: {e.message}")
            return {"status": "FAILED", "msg": e.message}
        except Exception as e:
            logger.error(f"❌ Take-Profit Error: {e}")
            return {"status": "FAILED", "msg": str(e)}

    def get_open_positions(self):
        """Fetch all open futures positions from Binance."""
        try:
            positions = self.client.futures_position_information()
            return [p for p in positions if float(p.get('positionAmt', 0)) != 0]
        except Exception as e:
            logger.error(f"Failed to fetch open positions: {e}")
            return []

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

    def _load_exchange_info(self):
        """Fetch quantity rules dynamically from Binance exchangeInfo."""
        global QUANTITY_RULES
        try:
            info = self.client.futures_exchange_info()
            for s in info.get('symbols', []):
                sym = s['symbol']
                for f in s.get('filters', []):
                    if f['filterType'] == 'LOT_SIZE':
                        min_qty = float(f['minQty'])
                        step = float(f['stepSize'])
                        QUANTITY_RULES[sym] = (min_qty, step)
            logger.info(f"📐 Loaded {len(QUANTITY_RULES)} symbol precision rules from exchangeInfo")
        except Exception as e:
            logger.warning(f"⚠️ exchangeInfo fetch failed, using hardcoded rules: {e}")

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
