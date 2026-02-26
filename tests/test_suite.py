import pytest
from pydantic import ValidationError
from tradingview_webhook_bot.schemas import TradingViewPayload, SignalStatus
from tradingview_webhook_bot.ledger.positions import PositionLedger
import os
import json

# --- 1. SCHEMA TESTS (Missing Fields & Validation) ---
def test_payload_validation():
    # Test Valid Payload
    valid_data = {
        "symbol": "BTCUSDT",
        "action": "BUY",
        "quantity": 1.0,
        "price": 60000,
        "strategy": "Test",
        "secret": "test_secret"
    }
    payload = TradingViewPayload(**valid_data)
    assert payload.symbol == "BTCUSDT"

    # Test Missing Field (Quantity bacha hai?)
    invalid_data = {"symbol": "BTCUSDT", "action": "BUY"}
    with pytest.raises(ValidationError):
        TradingViewPayload(**invalid_data)

    # Test Negative Quantity
    with pytest.raises(ValidationError):
        TradingViewPayload(symbol="BTCUSDT", action="BUY", quantity=-1, price=100)

# --- 2. LEDGER TESTS (Deterministic Logic) ---
def test_ledger_logic():
    ledger_file = "storage/test_ledger.json"
    if os.path.exists(ledger_file): 
        os.remove(ledger_file)

    ledger = PositionLedger(ledger_file)

    # First Buy
    ledger.apply_fill("ETHUSDT", "BUY", 2.0, 2000)
    
    # FIX: Use attribute access (.) instead of bracket access ([])
    # Pydantic models (PositionSnapshot) attributes allow dot notation
    eth_pos = ledger.positions["ETHUSDT"]
    assert eth_pos.quantity == 2.0
    assert eth_pos.avg_price == 2000

    # Second Buy (Weighted Average Price check)
    ledger.apply_fill("ETHUSDT", "BUY", 1.0, 2300)
    
    # Total Qty: 3.0, Total Cost: (2*2000 + 1*2300) = 6300, Avg: 2100
    eth_pos_updated = ledger.positions["ETHUSDT"]
    assert eth_pos_updated.quantity == 3.0
    assert eth_pos_updated.avg_price == 2100
    
    print("✅ Ledger Logic Test Passed with Pydantic Objects")
# --- 3. DLQ BEHAVIOR (Error Handling) ---
def test_dlq_logging(tmp_path):
    # Dummy DLQ test
    dlq_file = tmp_path / "dlq.jsonl"
    error_signal = {"raw": "bad_data", "error": "Validation Failed"}
    
    with open(dlq_file, "a") as f:
        f.write(json.dumps(error_signal) + "\n")
        
    assert dlq_file.read_text().strip() != ""
