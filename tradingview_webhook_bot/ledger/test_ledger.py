import pytest
from positions import PositionLedger

def test_weighted_average_and_pnl():
    ledger = PositionLedger()
    
    # 1. Buy 1 BTC at 50,000
    ledger.apply_fill("BTCUSDT", "buy", 1.0, 50000.0)
    pos = ledger.get_position("BTCUSDT")
    assert pos.avg_price == 50000.0
    assert pos.quantity == 1.0

    # 2. Buy another 1 BTC at 60,000 (Average should be 55,000)
    ledger.apply_fill("BTCUSDT", "buy", 1.0, 60000.0)
    pos = ledger.get_position("BTCUSDT")
    assert pos.avg_price == 55000.0
    assert pos.quantity == 2.0

    # 3. Sell 1 BTC at 70,000 (Should realize 15,000 profit)
    # (70k sell - 55k avg buy) * 1 unit = 15k
    ledger.apply_fill("BTCUSDT", "sell", 1.0, 70000.0)
    pos = ledger.get_position("BTCUSDT")
    assert pos.realized_pnl == 15000.0
    assert pos.quantity == 1.0
    assert pos.avg_price == 55000.0
