import pytest
import os
from unittest.mock import MagicMock, patch
from tradingview_webhook_bot.exchange.binance_client import BinanceClient

@patch('binance.client.Client.futures_account_balance', return_value=[])
def test_safety_gate_guard(mock_smoke):
    """
    Test 1: Verification of Safety Gate logic.
    Ensures trades are blocked when ALLOW_REAL_TRADES is False.
    """
    with patch.dict('os.environ', {'ALLOW_REAL_TRADES': 'false'}):
        # Initialize client (smoke test is mocked)
        client = BinanceClient(api_key="fake_key", api_secret="fake_secret")
        client.allow_real = False 
        
        res = client.execute_futures_order("BTCUSDT", "BUY", 0.001)
        
        # Verify the block
        assert res["status"] == "SKIPPED"
        assert "SAFETY GATE" in res["msg"]

@patch('binance.client.Client.futures_account_balance', return_value=[])
def test_binance_retry_logic(mock_smoke):
    """
    Test 2: Verification of Retry Logic.
    Ensures that a transient error triggers a second successful attempt.
    """
    client = BinanceClient(api_key="fake_key", api_secret="fake_secret")
    client.allow_real = True 
    
    with patch.object(client.client, 'futures_create_order') as mock_order:
        # Simulate: First call raises Transient Error, Second call succeeds
        mock_order.side_effect = [
            RuntimeError("Transient Binance Failure: 502"),
            {"orderId": 12345, "status": "FILLED"}
        ]
        
        # Bypass real sleep time during tests to make it fast
        with patch('time.sleep', return_value=None):
            res = client.execute_futures_order("BTCUSDT", "BUY", 0.001, signal_id="test_retry_v1")
            
        # Verify result and call count (should be 2 attempts)
        assert res["orderId"] == 12345
        assert mock_order.call_count == 2
        print(f"\n✅ Retry Logic Verified: {mock_order.call_count} attempts made.")

if __name__ == "__main__":
    # Allows running the test file directly
    pytest.main([__file__])
