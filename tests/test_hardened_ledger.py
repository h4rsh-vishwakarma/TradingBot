import pytest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../tradingview_webhook_bot')))

from ledger.positions import PositionLedger

@pytest.fixture
def temp_ledger(tmp_path):
    # Aapke code mein 'storage_path' use ho raha hai
    db_file = str(tmp_path / "test_ledger.json")
    return PositionLedger(db_file)

def test_weighted_average_calculation(temp_ledger):
    temp_ledger.apply_fill("BTCUSDT", "BUY", 1.0, 50000)
    temp_ledger.apply_fill("BTCUSDT", "BUY", 1.0, 60000)
    
    # Check if positions is a dict or a Pydantic model
    positions = temp_ledger.positions
    btc_pos = positions["BTCUSDT"]
    
    # Dynamic access for Pydantic objects or Dictionaries
    qty = float(getattr(btc_pos, 'quantity', btc_pos.get('quantity') if isinstance(btc_pos, dict) else 0))
    avg = float(getattr(btc_pos, 'avg_price', btc_pos.get('avg_price') if isinstance(btc_pos, dict) else 0))
    
    assert qty == 2.0
    assert avg == 55000.0

def test_position_flip_long_to_short(temp_ledger):
    temp_ledger.apply_fill("BTCUSDT", "BUY", 1.0, 50000)
    temp_ledger.apply_fill("BTCUSDT", "SELL", 2.0, 51000) # Flips to 1.0 Short
    
    btc_pos = temp_ledger.positions["BTCUSDT"]
    qty = float(getattr(btc_pos, 'quantity', btc_pos.get('quantity') if isinstance(btc_pos, dict) else 0))
    
    assert qty == -1.0

def test_realized_pnl_calculation(temp_ledger):
    symbol = "BTCUSDT"
    # Long 1 BTC at 50000
    temp_ledger.apply_fill(symbol, "BUY", 1.0, 50000)
    # Sell 0.5 BTC at 55000 (Partial Exit)
    temp_ledger.apply_fill(symbol, "SELL", 0.5, 55000)
    
    # JSON structure ke mutabiq symbol ke andar dhoondein
    pos = temp_ledger.positions[symbol]
    
    # Pydantic object ho ya dict, dono handle karein
    pnl = float(getattr(pos, 'realized_pnl', pos.get('realized_pnl') if isinstance(pos, dict) else 0))
    
    # Expected: (55000 - 50000) * 0.5 = 2500
    assert pnl == 2500.0

def test_idempotency_of_ledger_save(temp_ledger):
    temp_ledger.apply_fill("ETHUSDT", "BUY", 10, 2000)
    
    # Reloading using the exact attribute we found: storage_path
    new_ledger = PositionLedger(temp_ledger.storage_path)
    
    assert "ETHUSDT" in new_ledger.positions
    eth_pos = new_ledger.positions["ETHUSDT"]
    qty = float(getattr(eth_pos, 'quantity', eth_pos.get('quantity') if isinstance(eth_pos, dict) else 0))
    assert qty == 10.0
