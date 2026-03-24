"""Integration tests for safety gates and circuit breaker."""
import pytest
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tradingview_webhook_bot.ledger.positions import PositionLedger
from tradingview_webhook_bot.storage.idempotency_store import IdempotencyStore
from tradingview_webhook_bot.core.circuit_breaker import CircuitBreaker


class TestIdempotency:
    def test_blocks_duplicate(self, tmp_path):
        store = IdempotencyStore(str(tmp_path / "idem.db"))
        assert not store.is_seen("sig_001")
        store.mark_seen("sig_001", "order_001")
        assert store.is_seen("sig_001")

    def test_allows_new(self, tmp_path):
        store = IdempotencyStore(str(tmp_path / "idem.db"))
        assert not store.is_seen("sig_new")


class TestLedger:
    def test_waep(self, tmp_path):
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

    def test_persistence(self, tmp_path):
        f = str(tmp_path / "l.json")
        l1 = PositionLedger(f)
        l1.apply_fill("SOLUSDT", "BUY", 5.0, 90.0)
        l2 = PositionLedger(f)
        assert l2.positions["SOLUSDT"].quantity == 5.0


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

    def test_win_resets(self, tmp_path):
        cb = CircuitBreaker(str(tmp_path / "cb.json"), {"daily_loss_limit_pct": 50.0, "max_consecutive_losses": 3, "cooldown_minutes": 1})
        cb.record_trade_result(False)
        cb.record_trade_result(False)
        cb.record_trade_result(True)
        cb.record_trade_result(False)
        assert cb.should_allow_trade()

    def test_reset(self, tmp_path):
        cb = CircuitBreaker(str(tmp_path / "cb.json"), {"daily_loss_limit_pct": 5.0, "max_consecutive_losses": 2, "cooldown_minutes": 1})
        cb.record_trade_result(False)
        cb.record_trade_result(False)
        assert not cb.should_allow_trade()
        cb.reset()
        assert cb.should_allow_trade()

    def test_persistence(self, tmp_path):
        f = str(tmp_path / "cb.json")
        cb1 = CircuitBreaker(f, {"max_consecutive_losses": 3, "cooldown_minutes": 1})
        cb1.record_trade_result(False)
        cb1.record_trade_result(False)
        cb2 = CircuitBreaker(f, {"max_consecutive_losses": 3, "cooldown_minutes": 1})
        assert cb2.consecutive_losses == 2
