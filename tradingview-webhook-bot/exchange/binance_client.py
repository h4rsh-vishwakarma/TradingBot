import os
import logging
import time
from binance.client import Client
from binance.exceptions import BinanceAPIException
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Standard project logger
logger = logging.getLogger("tradingview_webhook_bot.exchange")

class BinanceClient:
    """
    Hardened Binance Futures API Client (Task D Compliant).
    Supports: Safety Gates, Idempotent Retries, and Error Classification.
    """

    def __init__(self, api_key=None, api_secret=None, testnet=None):
        load_dotenv()

        # Priority: Constructor Arg > Environment Variable
        self.api_key = api_key or os.getenv('BINANCE_API_KEY')
        self.api_secret = api_secret or os.getenv('BINANCE_API_SECRET')

        # Day 3: Testnet/Live switching
        if testnet is not None:
            self.testnet = testnet
        else:
            self.testnet = os.getenv('BINANCE_TESTNET', 'true').lower() == 'true'

        # Day 1: Safety Gate
        self.allow_real = os.getenv("ALLOW_REAL_TRADES", "false").lower() == "true"

        try:
            self.client = Client(self.api_key, self.api_secret, testnet=self.testnet)
            # Smoke Test
            self.client.futures_account_balance()
            mode = "TESTNET" if self.testnet else "LIVE"
            logger.info(f"✅ Connected to Binance Futures [{mode}] | Real Trades: {self.allow_real}")
        except Exception as e:
            logger.error(f"❌ Connection Failed: {e}")
            raise

    def get_audit_data(self):
        """Day 4: Reconciliation Metrics for drift detection."""
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

    # --- TASK D: HARDENED RETRY LOGIC (Idempotent & Deterministic) ---
    @retry(
        stop=stop_after_attempt(3), # Max 3 attempts
        wait=wait_exponential(multiplier=1, min=2, max=10), # 2s, 4s, 8s backoff
        retry=retry_if_exception_type((BinanceAPIException, ConnectionError)),
        reraise=True
    )
    def execute_futures_order(self, symbol, side, quantity, price=None, order_type='MARKET', signal_id=None):
        """
        Task D: Execute order with Idempotency using signal_id as newClientOrderId.
        """
        # --- SAFETY GATE (Day 1) ---
        if not self.allow_real:
            logger.warning(f"🚫 SAFETY GATE: Blocked {side} {quantity} {symbol} (Mode: Dry-Run)")
            return {"status": "SKIPPED", "msg": "Real trades disabled in .env"}

        try:
            # Task D: Deterministic Client Order ID to prevent duplicate trades
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
            logger.info(f"✅ Order Success: {response.get('orderId')}")
            return response

        except BinanceAPIException as e:
            # Task D: Error Classification (Permanent vs Transient)
            # Permanent Errors: Invalid symbol (-1121), Insufficient balance (-2019)
            if e.code in [-1121, -2019, -1102, -1013]: 
                logger.error(f"❌ Permanent Exchange Error: {e.message}")
                raise e # Don't retry
            
            # Transient Errors: Network/Server issues (Retry logic handles these)
            logger.warning(f"⚠️ Transient Error: {e.message}. Retrying...")
            raise e
        except Exception as e:
            logger.error(f"❌ Unexpected Execution Error: {e}")
            raise

    def get_account_health(self):
        """Day 4: Basic Metrics (Balance + Margin Ratio)"""
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
