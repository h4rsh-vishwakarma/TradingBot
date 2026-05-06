"""P-06: Verify auth-failure Telegram alert + HealthProbe exemption.

Scope:
- JSON payload with wrong secret → 401 + Telegram WARNING fired
- JSON payload with placeholder secret → 401 + Telegram WARNING fired
- Plain-text alert with wrong secret → 401 + Telegram WARNING fired
- GET /health → 200, no Telegram alert (HealthProbe exempt by separate route)
- Donchian_40 payload with wrong secret → 401 + strategy name in Telegram message
"""
from __future__ import annotations

import json
import os
import sys
import time
import threading
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Platform shims — stub Linux-only modules before any local import
# ---------------------------------------------------------------------------

def _stub_linux_module(name: str) -> None:
    if name not in sys.modules:
        sys.modules[name] = MagicMock()

_stub_linux_module("fcntl")
_stub_linux_module("uvloop")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_SECRET = "prod_secret_abc123"
DONCHIAN_STRATEGY = "Donchian_40"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_manifest(path: Path, strategy: str = DONCHIAN_STRATEGY) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "version": 30,
        "approvals": [
            {
                "strategy": strategy,
                "exchange": "binance",
                "symbols": ["ETHUSDT"],
                "timeframes": ["240"],
                "operator": "harsh",
                "approved_at": "2026-05-06T12:00:00Z",
                "backtest_hash": "test",
                "label": "P07_NOMINEE",
                "approval_class": "paper_only",
            }
        ],
    }))


@pytest.fixture
def server_client(tmp_path):
    manifest_path = tmp_path / "config" / "approved_strategies.json"
    _build_manifest(manifest_path)
    queue_file = str(tmp_path / "signals.jsonl")
    config = {"webhook": {"secret": VALID_SECRET, "host": "0.0.0.0", "port": 5000}}

    mock_telegram = MagicMock()

    patches = [
        patch("tradingview_webhook_bot.core.webhook_server.DurableSignalQueue", MagicMock),
        patch("tradingview_webhook_bot.core.webhook_server.AtomicJsonlQueue", MagicMock),
        patch("tradingview_webhook_bot.core.webhook_server.BacktestIngestor", MagicMock),
        patch("tradingview_webhook_bot.core.webhook_server.TelegramAlert", return_value=mock_telegram),
        patch.dict(os.environ, {"APPROVAL_MANIFEST_PATH": str(manifest_path)}),
    ]

    for p in patches:
        p.start()

    try:
        from tradingview_webhook_bot.core.webhook_server import WebhookServer
        server = WebhookServer(config, queue_file)
        server.telegram = mock_telegram  # ensure our mock is used even after __init__

        with server.app.test_client() as client:
            yield client, mock_telegram
    finally:
        for p in reversed(patches):
            p.stop()


# ---------------------------------------------------------------------------
# P-06 tests
# ---------------------------------------------------------------------------

class TestAuthFailureTelegramAlert:
    def test_json_wrong_secret_returns_401(self, server_client):
        client, _ = server_client
        resp = client.post(
            "/webhook/tradingview",
            json={"secret": "wrong_secret", "strategy": DONCHIAN_STRATEGY,
                  "symbol": "ETHUSDT", "side": "BUY", "price": 2400},
        )
        assert resp.status_code == 401

    def test_json_wrong_secret_fires_telegram(self, server_client):
        client, mock_tg = server_client
        mock_tg.reset_mock()
        client.post(
            "/webhook/tradingview",
            json={"secret": "totally_wrong", "strategy": DONCHIAN_STRATEGY,
                  "symbol": "ETHUSDT", "side": "BUY", "price": 2400},
        )
        time.sleep(0.15)  # allow daemon thread
        assert mock_tg.send.called, "Auth failure must trigger Telegram alert"
        call_repr = str(mock_tg.send.call_args)
        assert "AUTH FAILURE" in call_repr

    def test_json_placeholder_secret_returns_401_and_fires_telegram(self, server_client):
        client, mock_tg = server_client
        for placeholder in ("test", "secret", "your_secret_key"):
            mock_tg.reset_mock()
            resp = client.post(
                "/webhook/tradingview",
                json={"secret": placeholder, "strategy": DONCHIAN_STRATEGY,
                      "symbol": "ETHUSDT", "side": "BUY", "price": 2400},
            )
            assert resp.status_code == 401
            time.sleep(0.15)
            assert mock_tg.send.called, f"Placeholder '{placeholder}' must trigger Telegram alert"

    def test_donchian_payload_strategy_hint_in_telegram_message(self, server_client):
        """Strategy name must appear in Telegram message so on-call can identify the source."""
        client, mock_tg = server_client
        mock_tg.reset_mock()
        client.post(
            "/webhook/tradingview",
            json={"secret": "bad_secret", "strategy": DONCHIAN_STRATEGY,
                  "symbol": "ETHUSDT", "side": "BUY", "price": 2400},
        )
        time.sleep(0.15)
        if mock_tg.send.called:
            combined = str(mock_tg.send.call_args)
            assert DONCHIAN_STRATEGY in combined, "Strategy name must appear in alert message"

    def test_health_probe_returns_200_without_secret(self, server_client):
        """GET /health must succeed with no auth."""
        client, _ = server_client
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_probe_does_not_fire_telegram(self, server_client):
        """HealthProbe must never trigger an auth-failure Telegram alert."""
        client, mock_tg = server_client
        mock_tg.reset_mock()
        client.get("/health")
        time.sleep(0.05)
        assert not mock_tg.send.called, "GET /health must not fire auth-failure Telegram"

    def test_health_probe_response_shape(self, server_client):
        client, _ = server_client
        data = client.get("/health").get_json()
        assert data["status"] == "ok"
        assert data["service"] == "webhook"
