import pytest
from unittest.mock import MagicMock, patch


@patch("tradingview_webhook_bot.exchange.binance_client.Client")
def test_safety_gate_paper_mode(MockClient):
    """Test that allow_real=False returns paper trade (not real execution)."""
    from tradingview_webhook_bot.exchange.binance_client import BinanceClient
    mock_instance = MagicMock()
    MockClient.return_value = mock_instance
    client = BinanceClient.__new__(BinanceClient)
    client.api_key = "fake"
    client.api_secret = "fake"
    client.testnet = True
    client.allow_real = False
    client.client = mock_instance
    client.mainnet_base = "https://fapi.binance.com"
    res = client.execute_futures_order("BTCUSDT", "BUY", 0.001, price=50000)
    assert res["status"] == "SUCCESS"
    assert res.get("paper") == True
    assert "PAPER" in res.get("orderId", "")
    # Verify NO real order was placed
    mock_instance.futures_create_order.assert_not_called()


@patch("tradingview_webhook_bot.exchange.binance_client.Client")
def test_binance_retry_logic(MockClient):
    """Test that transient error triggers retry."""
    from tradingview_webhook_bot.exchange.binance_client import BinanceClient
    mock_instance = MagicMock()
    MockClient.return_value = mock_instance
    client = BinanceClient.__new__(BinanceClient)
    client.api_key = "fake"
    client.api_secret = "fake"
    client.testnet = True
    client.allow_real = True
    client.client = mock_instance
    client.mainnet_base = "https://fapi.binance.com"
    mock_instance.futures_create_order.side_effect = [
        RuntimeError("Transient 502"),
        {"orderId": 12345, "status": "FILLED"}
    ]
    with patch("time.sleep", return_value=None):
        res = client.execute_futures_order("BTCUSDT", "BUY", 0.001, price=50000, signal_id="test_retry")
    assert res["orderId"] == 12345
    assert mock_instance.futures_create_order.call_count == 2


@patch("tradingview_webhook_bot.exchange.binance_client.Client")
def test_qty_precision_fix(MockClient):
    """Test that fix_quantity adjusts precision correctly."""
    from tradingview_webhook_bot.exchange.binance_client import fix_quantity
    # SOL: step_size=0.1, min_qty=0.1
    qty_sol = fix_quantity("SOLUSDT", 0.05, price=90)
    assert qty_sol * 90 >= 21  # meets min notional $21
    # BTC: step_size=0.001, min_qty=0.001
    assert fix_quantity("BTCUSDT", 0.0005, price=90000) == 0.001  # bumped to min_qty
    # ETH: step_size=0.001, min_qty=0.001
    qty = fix_quantity("ETHUSDT", 0.009, price=2000)
    assert qty >= 0.009  # at least what we asked for (after rounding up)
