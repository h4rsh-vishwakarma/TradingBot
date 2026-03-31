import os
import tempfile
from unittest.mock import MagicMock, patch

from tradingview_webhook_bot.core.orchestrator import Orchestrator


def _build_orchestrator():
    orch = Orchestrator.__new__(Orchestrator)
    orch.idempotency = MagicMock()
    orch.idempotency.is_seen.return_value = False
    orch.telegram = MagicMock()
    orch.sheets_logger = MagicMock()
    orch.webhook_secret = "test_secret"
    orch._thread_pool = None
    orch._is_duplicate_signal = lambda *args, **kwargs: False
    orch._is_symbol_in_cooldown = lambda *args, **kwargs: False
    orch._is_candle_locked = lambda *args, **kwargs: False
    return orch


def test_orchestrator_sends_auto_reject_alert_for_unranked_strategy():
    orch = _build_orchestrator()
    orch.check_tournament_alpha = lambda symbol, strategy: (
        False,
        "Strategy OtherStrategy for SOLUSDT not in Leaderboard.",
        "NONE",
    )

    event = {
        "signal_id": "SIG-REJECT-001",
        "payload": {
            "strategy": "OtherStrategy",
            "symbol": "SOLUSDT",
            "action": "BUY",
            "price": 92.5,
            "quantity": 1.0,
            "secret": "test_secret",
        },
    }

    assert orch.handle_signal(event) is True

    kwargs = orch.telegram.send.call_args.kwargs
    assert kwargs["title"] == "Auto Rejected"
    assert "OtherStrategy" in kwargs["message"]
    assert "No auto-trade executed" in kwargs["message"]


def test_orchestrator_sends_auto_reject_alert_for_average_strategy():
    orch = _build_orchestrator()
    orch.check_tournament_alpha = lambda symbol, strategy: (
        True,
        "ROI below 0.5% threshold.",
        "AVERAGE",
    )

    event = {
        "signal_id": "SIG-AVG-001",
        "payload": {
            "strategy": "AverageStrategy",
            "symbol": "ETHUSDT",
            "action": "SELL",
            "price": 2010.0,
            "quantity": 0.1,
            "secret": "test_secret",
        },
    }

    assert orch.handle_signal(event) is True

    kwargs = orch.telegram.send.call_args.kwargs
    assert kwargs["title"] == "Auto Rejected"
    assert "Manual review required" in kwargs["message"]


def test_orchestrator_sends_match_error_alert_for_payload_validation_failure():
    orch = _build_orchestrator()
    orch.check_tournament_alpha = lambda symbol, strategy: (
        True,
        "Verified ALPHA: Direct Execution",
        "ALPHA",
    )

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
    assert kwargs["title"] == "Strategy Match Error"
    assert "payload_validation" in kwargs["message"]


def test_webhook_sends_alert_for_unrecognized_plain_text_strategy():
    with patch.dict(os.environ, {"WEBHOOK_SECRET": "test_secret_123"}):
        from tradingview_webhook_bot.core.webhook_server import WebhookServer

        tf = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        try:
            server = WebhookServer(
                config={"webhook": {"secret": "test_secret_123"}},
                signals_queue_file=tf.name,
            )
            server.telegram.send = MagicMock(return_value=True)
            client = server.app.test_client()

            resp = client.post(
                "/webhook/tradingview",
                data="Broken TradingView alert format without bot fields",
                content_type="text/plain",
            )

            assert resp.status_code == 200
            kwargs = server.telegram.send.call_args.kwargs
            assert kwargs["title"] == "TradingView Script Error"
            assert "did not match the bot parser" in kwargs["message"]
        finally:
            tf.close()
            os.unlink(tf.name)
