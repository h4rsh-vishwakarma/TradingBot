import sys
import os
from pathlib import Path

# Project root ko path mein add karna
ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

# Hyphenated folder handling
import importlib.util
folder_path = ROOT_DIR / "tradingview-webhook-bot"
if folder_path.exists():
    spec = importlib.util.spec_from_file_location("tradingview_webhook_bot", str(folder_path / "__init__.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules["tradingview_webhook_bot"] = module
    spec.loader.exec_module(module)

from tradingview_webhook_bot.ledger.positions import PositionLedger

def test_ledger_logic():
    # 1. Initialize Ledger
    ledger = PositionLedger(storage_path="storage/test_ledger.json")
    print("🚀 Starting Ledger Test...")

    # 2. Simulate First Buy: 0.01 BTC @ 60,000
    print("\nStep 1: Buying 0.01 BTC @ 60,000")
    ledger.apply_fill("BTCUSDT", "buy", 0.01, 60000.0, fee=1.0)
    pos = ledger.get_position("BTCUSDT")
    print(f"Current Qty: {pos.quantity} | Avg Price: {pos.avg_price}")

    # 3. Simulate Second Buy: 0.01 BTC @ 64,000 (Average should become 62,000)
    print("\nStep 2: Buying 0.01 BTC @ 64,000")
    ledger.apply_fill("BTCUSDT", "buy", 0.01, 64000.0, fee=1.0)
    pos = ledger.get_position("BTCUSDT")
    print(f"Current Qty: {pos.quantity} | Avg Price: {pos.avg_price}")

    # 4. Simulate Partial Sell: 0.01 BTC @ 65,000 (Profit should be $30 - fees)
    print("\nStep 3: Selling 0.01 BTC @ 65,000")
    ledger.apply_fill("BTCUSDT", "sell", 0.01, 65000.0, fee=1.0)
    pos = ledger.get_position("BTCUSDT")
    print(f"Remaining Qty: {pos.quantity} | Realized PnL: {pos.realized_pnl}")

    # 5. Final Check
    if pos.avg_price == 62000.0 and pos.quantity == 0.01:
        print("\n✅ TEST PASSED: Ledger math is correct!")
    else:
        print("\n❌ TEST FAILED: Check math logic.")

if __name__ == "__main__":
    test_ledger_logic()
