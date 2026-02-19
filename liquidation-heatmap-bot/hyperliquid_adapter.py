"""
Hyperliquid Perpetuals Exchange Adapter
Provides unified interface matching BinanceFuturesAdapter for multi-exchange routing
"""

import json
import time
from typing import Dict, List, Optional, Tuple
from decimal import Decimal
import requests
from eth_account import Account
from eth_account.messages import encode_defunct
import logging

logger = logging.getLogger(__name__)


class HyperliquidAdapter:
    """
    Hyperliquid perpetuals exchange adapter with EVM wallet authentication.
    Matches BinanceFuturesAdapter interface for seamless multi-exchange routing.
    """
    
    BASE_URL = "https://api.hyperliquid.xyz"
    
    def __init__(self, private_key: str, testnet: bool = False):
        """
        Initialize Hyperliquid adapter with Ethereum private key authentication.
        
        Args:
            private_key: Ethereum wallet private key (with or without 0x prefix)
            testnet: If True, uses testnet endpoint (Hyperliquid testnet API)
        """
        self.testnet = testnet
        
        # Clean private key (remove 0x if present)
        if private_key.startswith('0x'):
            private_key = private_key[2:]
        
        # Initialize EVM account
        self.account = Account.from_key(private_key)
        self.address = self.account.address
        
        # API endpoint (testnet uses different URL)
        if testnet:
            self.base_url = "https://api.hyperliquid-testnet.xyz"
        else:
            self.base_url = self.BASE_URL
        
        logger.info(f"🔐 Hyperliquid adapter initialized | Account: {self.address[:6]}...{self.address[-4:]} | Testnet: {testnet}")
    
    def _sign_request(self, payload: Dict) -> str:
        """
        Sign request payload with EVM private key.
        
        Args:
            payload: Request payload to sign
            
        Returns:
            Hex signature string
        """
        message = json.dumps(payload, separators=(',', ':'))
        encoded_msg = encode_defunct(text=message)
        signed = self.account.sign_message(encoded_msg)
        return signed.signature.hex()
    
    def _post_request(self, endpoint: str, payload: Dict) -> Dict:
        """
        Send authenticated POST request to Hyperliquid API.
        
        Args:
            endpoint: API endpoint path
            payload: Request payload
            
        Returns:
            API response as dictionary
        """
        url = f"{self.base_url}{endpoint}"
        
        # Add timestamp and sign
        payload['timestamp'] = int(time.time() * 1000)
        signature = self._sign_request(payload)
        
        headers = {
            'Content-Type': 'application/json',
            'X-Signature': signature,
            'X-Address': self.address
        }
        
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Hyperliquid API error: {e}")
            raise
    
    def _get_request(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """
        Send GET request to Hyperliquid API (public endpoints).
        
        Args:
            endpoint: API endpoint path
            params: Optional query parameters
            
        Returns:
            API response as dictionary
        """
        url = f"{self.base_url}{endpoint}"
        
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Hyperliquid API error: {e}")
            raise
    
    def place_limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        post_only: bool = True,
        client_order_id: Optional[str] = None
    ) -> Dict:
        """
        Place limit order on Hyperliquid (maker-first by default).
        
        Args:
            symbol: Trading pair (e.g., 'BTC-PERP')
            side: 'BUY' or 'SELL'
            quantity: Order quantity in base asset
            price: Limit price
            post_only: If True, order only executes as maker (default: True)
            client_order_id: Optional client order ID
            
        Returns:
            Order response with orderId, status, fills
        """
        payload = {
            'symbol': symbol,
            'side': side.upper(),
            'type': 'LIMIT',
            'quantity': str(quantity),
            'price': str(price),
            'postOnly': post_only,
            'timeInForce': 'GTC'
        }
        
        if client_order_id:
            payload['clientOrderId'] = client_order_id
        
        logger.info(f"📤 Placing Hyperliquid {side} limit order | {symbol} | Qty: {quantity} @ ${price}")
        
        result = self._post_request('/exchange/order', payload)
        
        logger.info(f"✅ Order placed | ID: {result.get('orderId')} | Status: {result.get('status')}")
        return result
    
    def place_bracket_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        post_only: bool = True
    ) -> Dict:
        """
        Place entry order with OCO bracket (stop-loss + take-profit).
        
        Args:
            symbol: Trading pair
            side: 'BUY' or 'SELL'
            quantity: Order quantity
            entry_price: Entry limit price
            stop_loss: Stop-loss trigger price
            take_profit: Take-profit limit price
            post_only: Maker-only entry (default: True)
            
        Returns:
            Dictionary with entry_order, stop_loss_order, take_profit_order
        """
        # Place entry order
        entry_order = self.place_limit_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=entry_price,
            post_only=post_only
        )
        
        # Calculate bracket side (opposite of entry)
        bracket_side = 'SELL' if side == 'BUY' else 'BUY'
        
        # Place OCO bracket (SL + TP)
        bracket_payload = {
            'symbol': symbol,
            'side': bracket_side,
            'quantity': str(quantity),
            'stopLoss': str(stop_loss),
            'takeProfit': str(take_profit),
            'linkedOrderId': entry_order.get('orderId')
        }
        
        logger.info(f"🎯 Placing OCO bracket | SL: ${stop_loss} | TP: ${take_profit}")
        
        bracket_result = self._post_request('/exchange/bracket', bracket_payload)
        
        return {
            'entry_order': entry_order,
            'stop_loss_order': bracket_result.get('stopLoss'),
            'take_profit_order': bracket_result.get('takeProfit')
        }
    
    def get_account_balance(self) -> Dict:
        """
        Get account balance and margin information.
        
        Returns:
            Dictionary with totalBalance, availableBalance, positions
        """
        payload = {
            'type': 'clearinghouseState',
            'user': self.address
        }
        result = self._post_request('/info', payload)
        
        balance_info = {
            'totalBalance': float(result.get('marginSummary', {}).get('accountValue', 0)),
            'availableBalance': float(result.get('marginSummary', {}).get('withdrawable', 0)),
            'positions': result.get('assetPositions', [])
        }
        
        logger.info(f"💰 Hyperliquid Balance | Total: ${balance_info['totalBalance']:.2f} | Available: ${balance_info['availableBalance']:.2f}")
        
        return balance_info
    
    def get_open_positions(self) -> List[Dict]:
        """
        Get all open positions.
        
        Returns:
            List of position dictionaries with symbol, side, size, entryPrice, unrealizedPnl
        """
        balance_info = self.get_account_balance()
        positions = balance_info.get('positions', [])
        
        # Filter only positions with non-zero size
        open_positions = [
            {
                'symbol': pos.get('coin'),
                'side': 'LONG' if float(pos.get('position', {}).get('szi', 0)) > 0 else 'SHORT',
                'size': abs(float(pos.get('position', {}).get('szi', 0))),
                'entryPrice': float(pos.get('position', {}).get('entryPx', 0)),
                'unrealizedPnl': float(pos.get('position', {}).get('unrealizedPnl', 0)),
                'leverage': float(pos.get('position', {}).get('leverage', {}).get('value', 1))
            }
            for pos in positions
            if float(pos.get('position', {}).get('szi', 0)) != 0
        ]
        
        logger.info(f"📊 Open positions: {len(open_positions)}")
        return open_positions
    
    def cancel_order(self, order_id: str, symbol: str) -> Dict:
        """
        Cancel open order.
        
        Args:
            order_id: Order ID to cancel
            symbol: Trading pair
            
        Returns:
            Cancellation response
        """
        payload = {
            'orderId': order_id,
            'symbol': symbol
        }
        
        logger.info(f"❌ Cancelling order {order_id} on {symbol}")
        
        result = self._post_request('/exchange/cancel', payload)
        return result
    
    def get_ticker_price(self, symbol: str) -> float:
        """
        Get current market price for symbol.
        
        Args:
            symbol: Trading pair
            
        Returns:
            Current price as float
        """
        result = self._get_request('/info/allMids')
        
        # Find price for symbol
        for pair_data in result:
            if pair_data.get('coin') == symbol.replace('-PERP', ''):
                return float(pair_data.get('mid', 0))
        
        raise ValueError(f"Symbol {symbol} not found in ticker data")


if __name__ == "__main__":
    # Test script
    import os
    
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Load test credentials (replace with actual keys)
    PRIVATE_KEY = os.getenv('HYPERLIQUID_PRIVATE_KEY', '0xYOUR_PRIVATE_KEY')
    
    adapter = HyperliquidAdapter(private_key=PRIVATE_KEY, testnet=False)
    
    # Test balance fetch
    balance = adapter.get_account_balance()
    print(f"\n✅ Balance: ${balance['totalBalance']:.2f}")
    
    # Test open positions
    positions = adapter.get_open_positions()
    print(f"✅ Open positions: {len(positions)}")
