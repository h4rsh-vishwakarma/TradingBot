import os
import logging
from binance.client import Client
from binance.exceptions import BinanceAPIException
from dotenv import load_dotenv

# Using the project's standard logger instead of a custom setup_logger if possible
logger = logging.getLogger("tradingview_webhook_bot.exchange")

class BinanceClient:
    """
    Advanced Binance Futures API Client.
    Supports: Safety Gates, Testnet Staging, and Reconciliation.
    """

    def __init__(self, api_key=None, api_secret=None, testnet=None):
        load_dotenv()
        
        # Priority: Constructor Arg > Environment Variable
        self.api_key = api_key or os.getenv('BINANCE_API_KEY')
        self.api_secret = api_secret or os.getenv('BINANCE_API_SECRET')
        
        # Day 3 Requirement: Seamless Testnet/Live switching for Staging
        if testnet is not None:
            self.testnet = testnet
        else:
            self.testnet = os.getenv('BINANCE_TESTNET', 'true').lower() == 'true'

        # Day 1 Requirement: ALLOW_REAL_TRADES Safety Gate
        self.allow_real = os.getenv("ALLOW_REAL_TRADES", "false").lower() == "true"

        try:
            self.client = Client(self.api_key, self.api_secret, testnet=self.testnet)
            
            # Connectivity Smoke Test
            self.client.futures_account_balance()
            mode = "TESTNET" if self.testnet else "LIVE"
            logger.info(f"✅ Connected to Binance Futures [{mode}] | Real Trades: {self.allow_real}")
        except Exception as e:
            logger.error(f"❌ Connection Failed: {e}")
            raise

    def get_audit_data(self):
        """
        Day 4 Requirement: Reconciliation Metrics.
        Returns a simplified dict of current exchange positions for drift detection.
        """
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

    def execute_futures_order(self, symbol, side, quantity, price=None, order_type='MARKET'):
        """
        Execute order with strict Day 1 Safety Gate checks.
        """
        # --- SAFETY GATE ---
        if not self.allow_real:
            logger.warning(f"🚫 SAFETY GATE: Blocked {side} {quantity} {symbol} (Mode: Dry-Run)")
            return {"status": "SKIPPED", "msg": "Real trades disabled in .env"}

        try:
            params = {
                "symbol": symbol,
                "side": side,
                "type": order_type,
                "quantity": quantity,
            }
            
            if order_type == 'LIMIT':
                params["price"] = str(price)
                params["timeInForce"] = "GTC"

            logger.info(f"🚀 Executing {order_type} {side} on {symbol}...")
            response = self.client.futures_create_order(**params)
            logger.info(f"✅ Order Success: {response.get('orderId')}")
            return response

        except BinanceAPIException as e:
            logger.error(f"❌ Order Execution Failed: {e.message}")
            # Day 4: This should trigger a Critical Alert in Orchestrator
            raise
        except Exception as e:
            logger.error(f"❌ Unexpected Execution Error: {e}")
            raise

    def get_account_health(self):
        """
        Day 4 Requirement: Basic Metrics (Balance + Margin Ratio)
        """
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
