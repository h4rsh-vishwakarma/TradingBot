import pytest
import time
from tradingview_webhook_bot.enhanced_trading_bot_remote import TradingBotOrchestrator

def test_full_pipeline_integration(tmp_path):
    # 1. Setup Config
    cfg = {
        'QUEUE_PATH': str(tmp_path / "q.jsonl"),
        'OFFSET_PATH': str(tmp_path / "o.txt"),
        'DLQ_PATH': str(tmp_path / "d.jsonl"),
        'IDEMPOTENCY_DB_PATH': str(tmp_path / "i.db"),
        'ALERTS_LOG_PATH': str(tmp_path / "a.jsonl"),
        'POLL_INTERVAL': 0.1
    }
    
    bot = TradingBotOrchestrator(cfg)
    
    # 2. Manually drop a signal into the queue (Simulating Webhook)
    from tradingview_webhook_bot.storage.jsonl_queue import append_jsonl
    signal = {
        "signal_id": "TEST-123",
        "payload": {"symbol": "BTCUSDT", "action": "buy", "quantity": 1.0, "price": 50000.0}
    }
    append_jsonl(cfg['QUEUE_PATH'], signal)
    
    # 3. Run one poll cycle
    bot.consumer.poll(bot.process_signal)
    
    # 4. Verify Ledger was updated
    pos = bot.ledger.get_position("BTCUSDT")
    assert pos.quantity == 1.0
    assert pos.avg_price == 50000.0
    
    # 5. Verify Idempotency prevents double-processing
    bot.consumer.poll(bot.process_signal) # Try again
    assert pos.quantity == 1.0 # Should still be 1.0, not 2.0
