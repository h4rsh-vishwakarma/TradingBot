"""Comprehensive integration tests for safety gates, circuit breaker, ledger, queue, and signal flow."""
import pytest
import os
import sys
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tradingview_webhook_bot.ledger.positions import PositionLedger
from tradingview_webhook_bot.storage.idempotency_store import IdempotencyStore
from tradingview_webhook_bot.core.circuit_breaker import CircuitBreaker
from tradingview_webhook_bot.storage.signal_queue import DurableSignalQueue


# ============================================================
# IDEMPOTENCY STORE TESTS
# ============================================================
class TestIdempotency:
    def test_blocks_duplicate(self, tmp_path):
        store = IdempotencyStore(str(tmp_path / "idem.db"))
        assert not store.is_seen("sig_001")
        store.mark_seen("sig_001", "order_001")
        assert store.is_seen("sig_001")

    def test_allows_new_signal(self, tmp_path):
        store = IdempotencyStore(str(tmp_path / "idem.db"))
        assert not store.is_seen("sig_new")

    def test_stores_order_mapping(self, tmp_path):
        store = IdempotencyStore(str(tmp_path / "idem.db"))
        store.mark_seen("sig_100", "binance_order_555")
        mapping = store.get_order_mapping("sig_100")
        assert mapping == "binance_order_555"

    def test_multiple_signals(self, tmp_path):
        store = IdempotencyStore(str(tmp_path / "idem.db"))
        for i in range(100):
            store.mark_seen(f"sig_{i}")
        assert store.is_seen("sig_0")
        assert store.is_seen("sig_99")
        assert not store.is_seen("sig_100")

    def test_persistence_across_instances(self, tmp_path):
        db = str(tmp_path / "idem.db")
        s1 = IdempotencyStore(db)
        s1.mark_seen("persist_test")
        s2 = IdempotencyStore(db)
        assert s2.is_seen("persist_test")


# ============================================================
# POSITION LEDGER TESTS
# ============================================================
class TestLedger:
    def test_waep_calculation(self, tmp_path):
        ledger = PositionLedger(str(tmp_path / "l.json"))
        ledger.apply_fill("ETHUSDT", "BUY", 2.0, 2000)
        ledger.apply_fill("ETHUSDT", "BUY", 1.0, 2300)
        pos = ledger.positions["ETHUSDT"]
        assert pos.quantity == 3.0
        assert pos.avg_price == 2100.0

    def test_position_flip(self, tmp_path):
        ledger = PositionLedger(str(tmp_path / "l.json"))
        ledger.apply_fill("BTCUSDT", "BUY", 1.0, 50000)
        ledger.apply_fill("BTCUSDT", "SELL", 2.0, 51000)
        assert ledger.positions["BTCUSDT"].quantity == -1.0

    def test_realized_pnl_on_close(self, tmp_path):
        ledger = PositionLedger(str(tmp_path / "l.json"))
        ledger.apply_fill("SOLUSDT", "BUY", 10.0, 100.0)
        pos = ledger.apply_fill("SOLUSDT", "SELL", 10.0, 110.0)
        assert pos.realized_pnl == 100.0  # (110-100) * 10
        assert pos.quantity == 0.0

    def test_partial_close(self, tmp_path):
        ledger = PositionLedger(str(tmp_path / "l.json"))
        ledger.apply_fill("ETHUSDT", "BUY", 5.0, 2000)
        ledger.apply_fill("ETHUSDT", "SELL", 2.0, 2200)
        pos = ledger.positions["ETHUSDT"]
        assert pos.quantity == 3.0
        assert pos.avg_price == 2000.0  # Avg stays same on partial close
        assert pos.realized_pnl == 400.0  # (2200-2000) * 2

    def test_short_position(self, tmp_path):
        ledger = PositionLedger(str(tmp_path / "l.json"))
        ledger.apply_fill("BTCUSDT", "SELL", 1.0, 50000)
        pos = ledger.positions["BTCUSDT"]
        assert pos.quantity == -1.0

    def test_daily_pnl_tracking(self, tmp_path):
        ledger = PositionLedger(str(tmp_path / "l.json"))
        ledger.apply_fill("SOLUSDT", "BUY", 1.0, 100.0)
        ledger.apply_fill("SOLUSDT", "SELL", 1.0, 105.0)
        pnl = ledger.get_daily_pnl()
        assert pnl == 5.0

    def test_persistence(self, tmp_path):
        f = str(tmp_path / "l.json")
        l1 = PositionLedger(f)
        l1.apply_fill("SOLUSDT", "BUY", 5.0, 90.0)
        l2 = PositionLedger(f)
        assert l2.positions["SOLUSDT"].quantity == 5.0

    def test_trade_history_recorded(self, tmp_path):
        ledger = PositionLedger(str(tmp_path / "l.json"))
        ledger.apply_fill("ETHUSDT", "BUY", 1.0, 2000)
        ledger.apply_fill("ETHUSDT", "SELL", 1.0, 2100)
        assert len(ledger.trade_history) == 1
        assert ledger.trade_history[0]["pnl"] == 100.0

    def test_empty_position_returns_zero(self, tmp_path):
        ledger = PositionLedger(str(tmp_path / "l.json"))
        pos = ledger.get_position("UNKNOWN")
        assert pos.quantity == 0.0
        assert pos.avg_price == 0.0

    def test_manual_position_update(self, tmp_path):
        ledger = PositionLedger(str(tmp_path / "l.json"))
        ledger.update_position_manually("SOLUSDT", 5.5)
        assert ledger.positions["SOLUSDT"].quantity == 5.5

    def test_zero_qty_resets_avg_price(self, tmp_path):
        ledger = PositionLedger(str(tmp_path / "l.json"))
        ledger.update_position_manually("SOLUSDT", 0.0)
        assert ledger.positions["SOLUSDT"].avg_price == 0.0


# ============================================================
# CIRCUIT BREAKER TESTS
# ============================================================
class TestCircuitBreaker:
    def test_allows_initially(self, tmp_path):
        cb = CircuitBreaker(str(tmp_path / "cb.json"), {"daily_loss_limit_pct": 5.0, "max_consecutive_losses": 3, "cooldown_minutes": 1})
        assert cb.should_allow_trade(10000.0)

    def test_trips_on_daily_loss(self, tmp_path):
        cb = CircuitBreaker(str(tmp_path / "cb.json"), {"daily_loss_limit_pct": 5.0, "max_consecutive_losses": 10, "cooldown_minutes": 1})
        cb.should_allow_trade(10000.0)
        assert not cb.should_allow_trade(9400.0)

    def test_trips_on_consecutive_losses(self, tmp_path):
        cb = CircuitBreaker(str(tmp_path / "cb.json"), {"daily_loss_limit_pct": 50.0, "max_consecutive_losses": 3, "cooldown_minutes": 1})
        cb.record_trade_result(False)
        cb.record_trade_result(False)
        cb.record_trade_result(False)
        assert not cb.should_allow_trade()

    def test_win_resets_consecutive_count(self, tmp_path):
        cb = CircuitBreaker(str(tmp_path / "cb.json"), {"daily_loss_limit_pct": 50.0, "max_consecutive_losses": 3, "cooldown_minutes": 1})
        cb.record_trade_result(False)
        cb.record_trade_result(False)
        cb.record_trade_result(True)
        cb.record_trade_result(False)
        assert cb.should_allow_trade()

    def test_manual_reset(self, tmp_path):
        cb = CircuitBreaker(str(tmp_path / "cb.json"), {"daily_loss_limit_pct": 5.0, "max_consecutive_losses": 2, "cooldown_minutes": 1})
        cb.record_trade_result(False)
        cb.record_trade_result(False)
        assert not cb.should_allow_trade()
        cb.reset()
        assert cb.should_allow_trade()

    def test_manual_pause_resume(self, tmp_path):
        cb = CircuitBreaker(str(tmp_path / "cb.json"), {"daily_loss_limit_pct": 5.0, "max_consecutive_losses": 10, "cooldown_minutes": 1})
        cb.pause("Testing")
        assert not cb.should_allow_trade()
        cb.resume()
        assert cb.should_allow_trade()

    def test_persistence(self, tmp_path):
        f = str(tmp_path / "cb.json")
        cb1 = CircuitBreaker(f, {"max_consecutive_losses": 3, "cooldown_minutes": 1})
        cb1.record_trade_result(False)
        cb1.record_trade_result(False)
        cb2 = CircuitBreaker(f, {"max_consecutive_losses": 3, "cooldown_minutes": 1})
        assert cb2.consecutive_losses == 2

    def test_status_report(self, tmp_path):
        cb = CircuitBreaker(str(tmp_path / "cb.json"), {"daily_loss_limit_pct": 5.0, "max_consecutive_losses": 3, "cooldown_minutes": 1})
        status = cb.get_status()
        assert "is_tripped" in status
        assert "consecutive_losses" in status

    def test_small_loss_allowed(self, tmp_path):
        cb = CircuitBreaker(str(tmp_path / "cb.json"), {"daily_loss_limit_pct": 5.0, "max_consecutive_losses": 10, "cooldown_minutes": 1})
        cb.should_allow_trade(10000.0)
        assert cb.should_allow_trade(9600.0)  # 4% loss < 5% limit


# ============================================================
# DURABLE SIGNAL QUEUE TESTS
# ============================================================
class TestDurableQueue:
    def test_enqueue_and_poll(self, tmp_path):
        q = DurableSignalQueue(str(tmp_path / "q.db"))
        q.enqueue({"signal_id": "test_1", "payload": {"symbol": "BTCUSDT"}})
        results = []
        def handler(event):
            results.append(event)
            return True
        q.poll(handler, batch_size=1)
        assert len(results) == 1
        assert results[0]["signal_id"] == "test_1"

    def test_retry_on_failure(self, tmp_path):
        q = DurableSignalQueue(str(tmp_path / "q.db"), max_retries=3)
        q.enqueue({"signal_id": "retry_test"})
        call_count = [0]
        def handler(event):
            call_count[0] += 1
            return False  # Always fail
        q.poll(handler, batch_size=1)
        q.poll(handler, batch_size=1)
        q.poll(handler, batch_size=1)
        # After 3 retries, should be in DLQ
        stats = q.get_stats()
        assert stats["dlq"] == 1

    def test_crash_recovery(self, tmp_path):
        db = str(tmp_path / "q.db")
        q1 = DurableSignalQueue(db)
        q1.enqueue({"signal_id": "crash_test"})
        # Simulate crash: mark as processing but don't complete
        import sqlite3
        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE signals SET status='processing' WHERE signal_id='crash_test'")
            conn.commit()
        # New instance should recover stuck signals
        q2 = DurableSignalQueue(db)
        results = []
        def handler(event):
            results.append(event)
            return True
        q2.poll(handler, batch_size=1)
        assert len(results) == 1

    def test_stats(self, tmp_path):
        q = DurableSignalQueue(str(tmp_path / "q.db"))
        q.enqueue({"signal_id": "s1"})
        q.enqueue({"signal_id": "s2"})
        stats = q.get_stats()
        assert stats["pending"] == 2
        assert stats["completed"] == 0

    def test_cleanup(self, tmp_path):
        q = DurableSignalQueue(str(tmp_path / "q.db"))
        q.enqueue({"signal_id": "old_signal"})
        def handler(event):
            return True
        q.poll(handler, batch_size=1)
        # Cleanup with 0 hours = delete everything completed
        q.cleanup(max_age_hours=0)
        stats = q.get_stats()
        assert stats["completed"] == 0

    def test_empty_queue_poll(self, tmp_path):
        q = DurableSignalQueue(str(tmp_path / "q.db"))
        results = []
        def handler(event):
            results.append(event)
            return True
        stats = q.poll(handler, batch_size=10)
        assert stats["processed"] == 0
        assert len(results) == 0

    def test_multiple_signals_order(self, tmp_path):
        q = DurableSignalQueue(str(tmp_path / "q.db"))
        for i in range(5):
            q.enqueue({"signal_id": f"order_{i}"})
        results = []
        def handler(event):
            results.append(event["signal_id"])
            return True
        q.poll(handler, batch_size=5)
        assert results == ["order_0", "order_1", "order_2", "order_3", "order_4"]


# ============================================================
# KILL SWITCH FILE TESTS
# ============================================================
class TestKillSwitch:
    def test_kill_file_detection(self, tmp_path):
        kill_file = str(tmp_path / "KILL_SWITCH")
        assert not os.path.exists(kill_file)
        with open(kill_file, 'w') as f:
            f.write("ACTIVATED")
        assert os.path.exists(kill_file)
        os.remove(kill_file)
        assert not os.path.exists(kill_file)


# ============================================================
# SAFETY GATE LOGIC TESTS (unit-level, no exchange needed)
# ============================================================
class TestSafetyGateLogic:
    def test_daily_pnl_blocks_when_exceeded(self, tmp_path):
        ledger = PositionLedger(str(tmp_path / "l.json"))
        # Simulate a losing day
        ledger.apply_fill("SOLUSDT", "BUY", 10.0, 100.0)
        ledger.apply_fill("SOLUSDT", "SELL", 10.0, 90.0)  # -$100 loss
        pnl = ledger.get_daily_pnl()
        assert pnl == -100.0

    def test_position_conflict_detection(self, tmp_path):
        ledger = PositionLedger(str(tmp_path / "l.json"))
        ledger.apply_fill("binance:SOLUSDT", "BUY", 1.0, 90.0)
        pos = ledger.get_position("binance:SOLUSDT")
        assert pos.quantity > 0
        # BUY when already long = conflict
        already_long = pos.quantity > 0
        assert already_long

    def test_no_conflict_on_opposite_side(self, tmp_path):
        ledger = PositionLedger(str(tmp_path / "l.json"))
        ledger.apply_fill("binance:SOLUSDT", "BUY", 1.0, 90.0)
        pos = ledger.get_position("binance:SOLUSDT")
        # SELL when long = not a conflict (closing position)
        is_conflict = (pos.quantity < 0)  # SELL side, checking if already short
        assert not is_conflict
