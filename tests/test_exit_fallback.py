from types import SimpleNamespace
from unittest.mock import MagicMock

from tradingview_webhook_bot.core.orchestrator import Orchestrator
from tradingview_webhook_bot.ledger.positions import PositionLedger


def test_exit_signal_falls_back_to_aggregate_position(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLOWED_SYMBOLS", "")
    monkeypatch.setenv("POSITION_SIZE_MODE", "fixed")

    orch = Orchestrator.__new__(Orchestrator)
    orch.idempotency = MagicMock()
    orch.idempotency.is_seen.return_value = False
    orch.telegram = MagicMock()
    orch.sheets_logger = MagicMock()
    orch.webhook_secret = "test_secret"
    orch._thread_pool = SimpleNamespace(submit=lambda fn: fn())
    orch._is_duplicate_signal = lambda *args, **kwargs: False
    orch._is_symbol_in_cooldown = lambda *args, **kwargs: False
    orch._is_candle_locked = lambda *args, **kwargs: False
    orch.exchange_hl = None
    orch.exchange_lighter = None
    orch.exchange_binance = MagicMock()
    orch.exchange_binance.get_mainnet_mark_price.return_value = 81.0
    orch.exchange_binance.cancel_open_orders.return_value = True
    orch.exchange_binance.execute_futures_order.return_value = {
        "status": "SUCCESS",
        "avg_price": 81.0,
    }
    orch.analytics = MagicMock()
    orch.circuit_breaker = None
    orch.processed_count = 0
    orch.MAX_QTY = {"SOLUSDT": 1.0}
    orch._mark_symbol_traded = MagicMock()
    orch._set_candle_lock = MagicMock()
    orch.allow_real = True
    orch.daily_loss_limit = -50.0
    orch.ledger_path = str(tmp_path / "ledger_state.json")
    orch.dlq_path = str(tmp_path / "dead_letter.jsonl")
    orch.ledger = PositionLedger(orch.ledger_path)
    orch.ledger.update_position_manually("binance:SOLUSDT", -2.0, avg_price=80.0)
    orch.ledger.update_position_manually("binance:SOLUSDT:07 macd breakout", 0.0)

    event = {
        "signal_id": "SIG-EXIT-FALLBACK",
        "payload": {
            "exchange": "binance",
            "strategy": "07_MACD_Breakout",
            "symbol": "SOLUSDT",
            "action": "SELL",
            "price": 0.0,
            "quantity": 0.003,
            "secret": "test_secret",
            "is_exit": True,
        },
    }

    assert orch.handle_signal(event) is True

    orch.exchange_binance.execute_futures_order.assert_called_once_with(
        "SOLUSDT",
        "BUY",
        2.0,
        81.0,
        signal_id="SIG-EXIT-FALLBACK",
    )
    assert orch.ledger.get_position("binance:SOLUSDT").quantity == 0.0
    assert orch.ledger.get_position("binance:SOLUSDT:07 macd breakout").quantity == 0.0


def test_exit_signal_without_position_sends_skip_telegram(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLOWED_SYMBOLS", "")
    monkeypatch.setenv("POSITION_SIZE_MODE", "fixed")

    orch = Orchestrator.__new__(Orchestrator)
    orch.idempotency = MagicMock()
    orch.idempotency.is_seen.return_value = False
    orch.telegram = MagicMock()
    orch.sheets_logger = MagicMock()
    orch.webhook_secret = "test_secret"
    orch._thread_pool = SimpleNamespace(submit=lambda fn: fn())
    orch._is_duplicate_signal = lambda *args, **kwargs: False
    orch._is_symbol_in_cooldown = lambda *args, **kwargs: False
    orch._is_candle_locked = lambda *args, **kwargs: False
    orch.exchange_hl = None
    orch.exchange_lighter = None
    orch.exchange_binance = MagicMock()
    orch.exchange_binance.get_mainnet_mark_price.return_value = 81.0
    orch.analytics = MagicMock()
    orch.circuit_breaker = None
    orch.processed_count = 0
    orch.MAX_QTY = {"SOLUSDT": 1.0}
    orch._mark_symbol_traded = MagicMock()
    orch._set_candle_lock = MagicMock()
    orch.allow_real = True
    orch.daily_loss_limit = -50.0
    orch.ledger_path = str(tmp_path / "ledger_state.json")
    orch.dlq_path = str(tmp_path / "dead_letter.jsonl")
    orch.ledger = PositionLedger(orch.ledger_path)

    event = {
        "signal_id": "SIG-NO-POSITION",
        "payload": {
            "exchange": "binance",
            "strategy": "07_MACD_Breakout",
            "symbol": "SOLUSDT",
            "action": "SELL",
            "price": 0.0,
            "quantity": 0.003,
            "secret": "test_secret",
            "is_exit": True,
        },
    }

    assert orch.handle_signal(event) is True
    orch.exchange_binance.execute_futures_order.assert_not_called()
    orch.telegram.send.assert_called()
    assert "Exit signal received" in orch.telegram.send.call_args.kwargs["message"]
