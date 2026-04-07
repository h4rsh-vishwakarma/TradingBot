import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from tradingview_webhook_bot.core.orchestrator import Orchestrator


def _build_orchestrator(tmp_path):
    manifest_path = tmp_path / "approved_strategies.json"
    manifest_path.write_text(json.dumps({
        "version": 1,
        "updated_at": "2026-04-06T00:00:00Z",
        "approvals": [
            {
                "strategy": "LiveStrategy",
                "exchange": "binance",
                "symbols": ["BTCUSDT"],
                "timeframes": ["*"],
                "operator": "tester",
                "approved_at": "2026-04-06T00:00:00Z",
                "backtest_hash": "sha256:test",
                "label": "APPROVED_MANIFEST",
            }
        ],
    }), encoding="utf-8")

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
    orch.exchange_binance.get_mainnet_mark_price.return_value = 85000.0
    orch.exchange_binance.execute_futures_order.return_value = {"status": "SUCCESS", "avg_price": 85000.0}
    orch.analytics = MagicMock()
    orch.circuit_breaker = None
    orch.processed_count = 0
    orch.DEDUP_WINDOW_SECONDS = 120
    orch.MAX_QTY = {"BTCUSDT": 1.0}
    orch.allow_real = True
    orch.daily_loss_limit = -50.0
    orch.ledger_path = str(tmp_path / "ledger_state.json")
    orch.dlq_path = str(tmp_path / "dead_letter.jsonl")
    orch.approval_manifest_path = str(manifest_path)
    orch.require_approval_manifest = True
    orch._notify_signal_decision = Orchestrator._notify_signal_decision.__get__(orch, Orchestrator)
    return orch


def test_orchestrator_sends_signal_blocked_for_unapproved_strategy(tmp_path):
    orch = _build_orchestrator(tmp_path)
    event = {
        "signal_id": "SIG-REJECT-001",
        "payload": {
            "strategy": "OtherStrategy",
            "symbol": "BTCUSDT",
            "action": "BUY",
            "price": 85000.0,
            "quantity": 0.01,
            "secret": "test_secret",
        },
    }

    assert orch.handle_signal(event) is True
    kwargs = orch.telegram.send.call_args.kwargs
    assert kwargs["title"] == "Signal Blocked"
    assert "not approved in the live manifest" in kwargs["message"]


def test_orchestrator_sends_signal_blocked_for_payload_validation_failure(tmp_path):
    orch = _build_orchestrator(tmp_path)
    event = {
        "signal_id": "SIG-PARSE-001",
        "payload": {
            "strategy": "LiveStrategy",
            "symbol": "BTCUSDT",
            "action": "HOLD",
            "price": 85000.0,
            "quantity": 0.01,
            "secret": "test_secret",
        },
    }

    assert orch.handle_signal(event) is True
    kwargs = orch.telegram.send.call_args.kwargs
    assert kwargs["title"] == "Signal Blocked"
    assert "Data parsing error" in kwargs["message"]


def test_orchestrator_blocks_symbol_not_in_allowlist(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLOWED_SYMBOLS", "ETHUSDT")
    orch = _build_orchestrator(tmp_path)
    event = {
        "signal_id": "SIG-ALLOWLIST-001",
        "payload": {
            "strategy": "LiveStrategy",
            "symbol": "BTCUSDT",
            "action": "BUY",
            "price": 85000.0,
            "quantity": 0.01,
            "secret": "test_secret",
        },
    }

    assert orch.handle_signal(event) is True
    kwargs = orch.telegram.send.call_args.kwargs
    assert kwargs["title"] == "Signal Blocked"
    assert "ALLOWED_SYMBOLS" in kwargs["message"]


def test_orchestrator_skips_duplicate_signal_with_deterministic_reason(tmp_path, monkeypatch):
    monkeypatch.delenv("ALLOWED_SYMBOLS", raising=False)
    orch = _build_orchestrator(tmp_path)
    orch._is_duplicate_signal = lambda *args, **kwargs: True
    event = {
        "signal_id": "SIG-DUP-001",
        "payload": {
            "strategy": "LiveStrategy",
            "symbol": "BTCUSDT",
            "action": "BUY",
            "price": 85000.0,
            "quantity": 0.01,
            "secret": "test_secret",
        },
    }

    assert orch.handle_signal(event) is True
    kwargs = orch.telegram.send.call_args.kwargs
    assert kwargs["title"] == "Signal Skipped"
    assert "Duplicate BUY signal" in kwargs["message"]


def test_orchestrator_blocks_strategy_cooldown_with_deterministic_reason(tmp_path, monkeypatch):
    monkeypatch.delenv("ALLOWED_SYMBOLS", raising=False)
    orch = _build_orchestrator(tmp_path)
    orch._is_symbol_in_cooldown = lambda *args, **kwargs: True
    event = {
        "signal_id": "SIG-COOLDOWN-001",
        "payload": {
            "strategy": "LiveStrategy",
            "symbol": "BTCUSDT",
            "action": "BUY",
            "price": 85000.0,
            "quantity": 0.01,
            "secret": "test_secret",
        },
    }

    assert orch.handle_signal(event) is True
    kwargs = orch.telegram.send.call_args.kwargs
    assert kwargs["title"] == "Signal Blocked"
    assert "Cooldown active" in kwargs["message"]
