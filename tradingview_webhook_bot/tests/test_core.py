import pytest
from core.schemas import SignalPayload

def test_signal_payload_validation():
    data = {
        "secret": "test",
        "strategy": "test",
        "symbol": "BTCUSDT",
        "action": "BUY",
        "quantity": 0.001,
        "price": 60000
    }
    payload = SignalPayload(**data)
    assert payload.symbol == "BTCUSDT"
    assert payload.action == "BUY"
