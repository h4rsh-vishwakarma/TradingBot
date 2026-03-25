import pytest
import os
from unittest.mock import MagicMock, patch


@patch("tradingview_webhook_bot.exchange.binance_client.Client")
def test_safety_gate_guard(MockClient):
    """Test that safety gate blocks when ALLOW_REAL_TRADES is off."""
    MockClient.return_value = MagicMock()
    with patch.dict("os.environ", {"ALLOW_REAL_TRADES": "false", "BINANCE_TESTNET": "true"}):
        from tradingview_webhook_bot.exchange.binance_client import BinanceClient
        client = BinanceClient(api_key="fake_key", api_secret="fake_secret")
        client.allow_real = False
        res = client.execute_futures_order("BTCUSDT", "BUY", 0.001)
        assert res["status"] == "SKIPPED"
        assert "SAFETY GATE" in res["msg"]


@patch("tradingview_webhook_bot.exchange.binance_client.Client")
def test_binance_retry_logic(MockClient):
    """Test that transient error triggers retry."""
    mock_instance = MagicMock()
    MockClient.return_value = mock_instance
    with patch.dict("os.environ", {"ALLOW_REAL_TRADES": "true", "BINANCE_TESTNET": "true"}):
        from tradingview_webhook_bot.exchange.binance_client import BinanceClient
        client = BinanceClient(api_key="fake_key", api_secret="fake_secret")
        client.allow_real = True
        mock_instance.futures_create_order.side_effect = [
            RuntimeError("Transient 502"),
            {"orderId": 12345, "status": "FILLED"}
        ]
        with patch("time.sleep", return_value=None):
            res = client.execute_futures_order("BTCUSDT", "BUY", 0.001, signal_id="test_retry")
        assert res["orderId"] == 12345
        assert mock_instance.futures_create_order.call_count == 2
