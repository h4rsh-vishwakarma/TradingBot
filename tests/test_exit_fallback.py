import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from tradingview_webhook_bot.core.orchestrator import Orchestrator
from tradingview_webhook_bot.ledger.positions import PositionLedger


def _approved_manifest(tmp_path, approval_class="candidate_for_tiny_capital"):
    path = tmp_path / "approved_strategies.json"
    path.write_text(json.dumps({
        "version": 1,
        "updated_at": "2026-04-06T00:00:00Z",
        "approvals": [
            {
                "strategy": "07_MACD_Breakout",
                "exchange": "binance",
                "symbols": ["SOLUSDT"],
                "timeframes": ["*"],
                "operator": "tester",
                "approved_at": "2026-04-06T00:00:00Z",
                "backtest_hash": "sha256:test",
                "label": "APPROVED_MANIFEST",
                "approval_class": approval_class,
            }
        ],
    }), encoding="utf-8")
    return str(path)


def _build_orchestrator(tmp_path, approval_class="candidate_for_tiny_capital"):
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
    orch.exchange_binance.place_stop_loss.return_value = {"status": "SUCCESS"}
    orch.exchange_binance.place_take_profit.return_value = {"status": "SUCCESS"}
    orch.analytics = MagicMock()
    orch.circuit_breaker = None
    orch.processed_count = 0
    orch.MAX_QTY = {"SOLUSDT": 1.0}
    orch._persist_exec_lock = MagicMock()
    orch._set_candle_lock = MagicMock()
    orch._mark_symbol_traded = MagicMock()
    orch.allow_real = True
    orch.daily_loss_limit = -50.0
    orch.ledger_path = str(tmp_path / "ledger_state.json")
    orch.dlq_path = str(tmp_path / "dead_letter.jsonl")
    orch.execution_metrics_path = str(tmp_path / "execution_metrics.jsonl")
    orch.ledger = PositionLedger(orch.ledger_path)
    orch.require_approval_manifest = True
    orch.approval_manifest_path = _approved_manifest(tmp_path, approval_class=approval_class)
    orch._notify_signal_decision = Orchestrator._notify_signal_decision.__get__(orch, Orchestrator)
    orch.check_strategy_approval = Orchestrator.check_strategy_approval.__get__(orch, Orchestrator)
    orch._load_approval_manifest = Orchestrator._load_approval_manifest.__get__(orch, Orchestrator)
    orch._normalize_strategy = Orchestrator._normalize_strategy
    return orch


def test_exit_signal_falls_back_to_aggregate_position(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLOWED_SYMBOLS", "")
    monkeypatch.setenv("POSITION_SIZE_MODE", "fixed")

    orch = _build_orchestrator(tmp_path)
    orch.ledger.update_position_manually("binance:SOLUSDT", -2.0, avg_price=80.0)
    orch.ledger.update_position_manually("binance:SOLUSDT:07_MACD_Breakout", 0.0)

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
    assert orch.ledger.get_position("binance:SOLUSDT:07_MACD_Breakout").quantity == 0.0


def test_unapproved_strategy_is_blocked_by_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLOWED_SYMBOLS", "")
    monkeypatch.setenv("POSITION_SIZE_MODE", "fixed")

    orch = _build_orchestrator(tmp_path)
    event = {
        "signal_id": "SIG-BLOCKED-001",
        "payload": {
            "exchange": "binance",
            "strategy": "UnknownStrategy",
            "symbol": "SOLUSDT",
            "action": "BUY",
            "price": 81.0,
            "quantity": 0.1,
            "secret": "test_secret",
        },
    }

    assert orch.handle_signal(event) is True
    orch.exchange_binance.execute_futures_order.assert_not_called()
    assert orch.telegram.send.call_args.kwargs["title"] == "Signal Blocked"
    assert "not approved in the live manifest" in orch.telegram.send.call_args.kwargs["message"]


def test_paper_only_strategy_executes_when_present_in_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLOWED_SYMBOLS", "")
    monkeypatch.setenv("POSITION_SIZE_MODE", "fixed")

    orch = _build_orchestrator(tmp_path, approval_class="paper_only")
    event = {
        "signal_id": "SIG-PAPER-ONLY-001",
        "payload": {
            "exchange": "binance",
            "strategy": "07_MACD_Breakout",
            "symbol": "SOLUSDT",
            "action": "BUY",
            "price": 81.0,
            "quantity": 0.1,
            "secret": "test_secret",
        },
    }

    assert orch.handle_signal(event) is True
    orch.exchange_binance.execute_futures_order.assert_called_once_with(
        "SOLUSDT", "BUY", 0.1, 81.0, signal_id="SIG-PAPER-ONLY-001"
    )
    if orch.telegram.send.call_args is not None:
        assert orch.telegram.send.call_args.kwargs.get("title") != "Signal Blocked"
