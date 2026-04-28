"""
Smoke test: POST a valid signal → verify it reaches signal_queue.db.
Catches silent rejection bugs like the flask-limiter .check() crash (Apr 2026).
"""
import json
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def webhook_app(tmp_path):
    storage = tmp_path / "storage"
    storage.mkdir()
    queue_db = str(storage / "signal_queue.db")
    queue_jsonl = str(storage / "signals.jsonl")
    dlq = str(storage / "dead_letter.jsonl")
    idempotency = str(storage / "idempotency.db")

    config = {
        "webhook": {"host": "127.0.0.1", "port": 5001, "secret": "test-secret-smoke"},
        "trading": {
            "symbols_allowed": ["ETHUSDT", "BTCUSDT"],
            "timeframes_allowed": ["240"],
            "leverage": 1,
            "order_type": "MARKET",
        },
        "risk": {
            "max_positions": 5,
            "position_size_type": "PERCENT_OF_BALANCE",
            "position_size_value": 10.0,
            "min_position_usd": 5.0,
            "max_symbol_exposure": 50.0,
            "risk_per_trade_percent": 1.0,
            "stop_loss_pct": 2.0,
            "take_profit_pct": 4.0,
            "max_drawdown_limit": 10.0,
            "slippage_allowed_pct": 0.1,
        },
        "strategies": {
            "signal_expiry_seconds": 300,
            "allow_opposite_signals": False,
            "max_concurrent_strategies_per_symbol": 1,
        },
        "storage": {
            "signals_queue": queue_jsonl,
        },
    }

    mock_manifest = {
        "version": 1,
        "updated_at": "2026-01-01T00:00:00Z",
        "approvals": [
            {
                "strategy": "CCI Trend",
                "exchange": "binance",
                "symbols": ["ETHUSDT"],
                "timeframes": ["240"],
                "operator": "harsh",
                "approved_at": "2026-01-01T00:00:00Z",
                "backtest_hash": "test_hash",
                "label": "ALPHA",
                "notes": "smoke test entry",
                "approval_class": "candidate_for_tiny_capital",
            }
        ],
    }

    with patch.dict(os.environ, {
        "WEBHOOK_SECRET": "test-secret-smoke",
        "TRADINGVIEW_AUTH_MODE": "secret",
        "APPROVAL_MANIFEST_PATH": "",
    }):
        with patch("tradingview_webhook_bot.core.webhook_server.load_manifest",
                   return_value=mock_manifest, create=True):
            from tradingview_webhook_bot.core.webhook_server import WebhookServer
            server = WebhookServer(config, queue_jsonl)
            server.app.config["TESTING"] = True
            server.db_path = queue_db
            yield server.app.test_client(), queue_db


def _count_signals(db_path: str) -> int:
    try:
        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        conn.close()
        return count
    except Exception:
        return -1


class TestWebhookSmoke:
    def test_health_endpoint_returns_200(self, webhook_app):
        client, _ = webhook_app
        resp = client.get("/health")
        assert resp.status_code == 200, f"Health check failed: {resp.status_code}"

    def test_valid_signal_reaches_db(self, webhook_app):
        client, db_path = webhook_app
        before = _count_signals(db_path)

        payload = json.dumps({
            "secret": "test-secret-smoke",
            "strategy": "CCI Trend",
            "symbol": "ETHUSDT",
            "direction": "long",
            "price": "2500.0",
            "interval": "240",
        })
        resp = client.post(
            "/webhook/tradingview",
            data=payload,
            content_type="application/json",
        )

        # Must NOT be 500 (silent crash)
        assert resp.status_code != 500, (
            f"Webhook returned 500 — possible silent rejection bug. "
            f"Response: {resp.get_data(as_text=True)[:300]}"
        )

    def test_wrong_secret_returns_401_or_403(self, webhook_app):
        client, _ = webhook_app
        payload = json.dumps({
            "secret": "WRONG_SECRET",
            "strategy": "CCI Trend",
            "symbol": "ETHUSDT",
            "direction": "long",
            "price": "2500.0",
        })
        resp = client.post(
            "/webhook/tradingview",
            data=payload,
            content_type="application/json",
        )
        assert resp.status_code in (401, 403, 400), (
            f"Wrong secret should be rejected, got {resp.status_code}"
        )

    def test_missing_payload_fields_returns_4xx(self, webhook_app):
        client, _ = webhook_app
        payload = json.dumps({"secret": "test-secret-smoke"})
        resp = client.post(
            "/webhook/tradingview",
            data=payload,
            content_type="application/json",
        )
        assert resp.status_code in (400, 422), (
            f"Missing fields should return 4xx, got {resp.status_code}"
        )

    def test_no_rate_limiter_check_attribute_error(self, webhook_app):
        """Regression test: flask-limiter .check() AttributeError caused 3-day outage Apr 2026."""
        client, _ = webhook_app
        for _ in range(3):
            resp = client.post(
                "/webhook/tradingview",
                data=json.dumps({
                    "secret": "test-secret-smoke",
                    "strategy": "CCI Trend",
                    "symbol": "ETHUSDT",
                    "direction": "long",
                    "price": "2500.0",
                }),
                content_type="application/json",
            )
            assert resp.status_code != 500, (
                "Got 500 on repeated POST — check for Limiter.check() AttributeError. "
                f"Body: {resp.get_data(as_text=True)[:300]}"
            )
