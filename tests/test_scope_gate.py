"""
P-01 regression: manifest gate must hard-reject (403) non-manifest strategies.

Demo_Momentum_Test incident: ungoverned strategy executed via silent 200 pass-through.
The old allowlist check had two bugs:
  1. Returned 200 (not 403) for non-manifest strategies — invisible to callers.
  2. Used `if _approved_names and ...` — empty-set bypass when manifest failed to load.
Fixed: non-manifest strategy → 403; manifest load failure → fail-closed 403.
"""
import io
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MANIFEST_WITH_CCI = {
    "version": 19,
    "updated_at": "2026-01-01T00:00:00Z",
    "approvals": [
        {
            "strategy": "CCI Trend",
            "exchange": "binance",
            "symbols": ["ETHUSDT"],
            "timeframes": ["240"],
            "operator": "harsh",
            "approved_at": "2026-01-01T00:00:00Z",
            "backtest_hash": "abc123",
            "label": "ALPHA",
            "notes": "test",
            "approval_class": "paper_only",
        }
    ],
}

MANIFEST_EMPTY = {
    "version": 19,
    "updated_at": "2026-01-01T00:00:00Z",
    "approvals": [],
}


def _open_with_manifest(manifest_data):
    """Returns open() replacement that serves manifest_data for approved_strategies.json."""
    import builtins
    _real_open = builtins.open
    manifest_str = json.dumps(manifest_data)

    def _fake_open(path, *args, **kwargs):
        if "approved_strategies.json" in str(path):
            return io.StringIO(manifest_str)
        return _real_open(path, *args, **kwargs)

    return _fake_open


def _open_failing_manifest():
    """Returns open() replacement that raises OSError for the manifest file."""
    import builtins
    _real_open = builtins.open

    def _fake_open(path, *args, **kwargs):
        if "approved_strategies.json" in str(path):
            raise OSError("Simulated manifest read failure")
        return _real_open(path, *args, **kwargs)

    return _fake_open


@pytest.fixture
def scope_client(tmp_path):
    storage = tmp_path / "storage"
    storage.mkdir()
    queue_jsonl = str(storage / "signals.jsonl")

    config = {
        "webhook": {"host": "127.0.0.1", "port": 5001, "secret": "test-secret-scope"},
        "trading": {
            "symbols_allowed": ["ETHUSDT", "SOLUSDT"],
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
        "storage": {"signals_queue": queue_jsonl},
    }

    with patch.dict(os.environ, {
        "WEBHOOK_SECRET": "test-secret-scope",
        "TRADINGVIEW_AUTH_MODE": "secret",
        "USE_DURABLE_QUEUE": "false",
    }):
        from tradingview_webhook_bot.core.webhook_server import WebhookServer
        server = WebhookServer(config, queue_jsonl)
        server.app.config["TESTING"] = True
        yield server.app.test_client()


def _post_signal(client, strategy, symbol="SOLUSDT", manifest=MANIFEST_WITH_CCI):
    with patch("builtins.open", side_effect=_open_with_manifest(manifest)):
        return client.post(
            "/webhook/tradingview",
            data=json.dumps({
                "secret": "test-secret-scope",
                "strategy": strategy,
                "symbol": symbol,
                "side": "BUY",
                "price": "150.0",
                "quantity": "0.003",
            }),
            content_type="application/json",
        )


class TestManifestScopeGate:
    def test_non_manifest_strategy_returns_403(self, scope_client):
        """Demo_Momentum_Test (not in manifest) must be hard-rejected with 403."""
        resp = _post_signal(scope_client, strategy="Demo_Momentum_Test")
        assert resp.status_code == 403, (
            f"Non-manifest strategy must return 403, got {resp.status_code}. "
            f"Body: {resp.get_data(as_text=True)[:200]}"
        )
        body = resp.get_json()
        assert body.get("message") in ("Strategy not authorized", "Test/demo strategies not permitted in production")

    def test_manifest_strategy_passes_gate(self, scope_client):
        """CCI Trend (in manifest) must not be rejected at the manifest gate."""
        resp = _post_signal(scope_client, strategy="CCI Trend", symbol="ETHUSDT")
        assert resp.status_code not in (403, 500), (
            f"Manifest strategy must pass gate, got {resp.status_code}. "
            f"Body: {resp.get_data(as_text=True)[:200]}"
        )

    def test_manifest_load_failure_rejects_all(self, scope_client):
        """If manifest cannot be loaded, fail closed — reject all signals with 403."""
        with patch("builtins.open", side_effect=_open_failing_manifest()):
            resp = scope_client.post(
                "/webhook/tradingview",
                data=json.dumps({
                    "secret": "test-secret-scope",
                    "strategy": "CCI Trend",
                    "symbol": "ETHUSDT",
                    "side": "BUY",
                    "price": "2500.0",
                }),
                content_type="application/json",
            )
        assert resp.status_code == 403, (
            f"Manifest load failure must fail closed (403), got {resp.status_code}. "
            f"Body: {resp.get_data(as_text=True)[:200]}"
        )

    def test_empty_manifest_rejects_all(self, scope_client):
        """Empty approvals list must reject all strategies — no bypass via empty set."""
        resp = _post_signal(scope_client, strategy="CCI Trend", symbol="ETHUSDT", manifest=MANIFEST_EMPTY)
        assert resp.status_code == 403, (
            f"Empty manifest must reject all strategies (403), got {resp.status_code}. "
            f"Body: {resp.get_data(as_text=True)[:200]}"
        )

    def test_wrong_secret_rejected_before_manifest_check(self, scope_client):
        """Wrong secret must be rejected with 401 regardless of manifest contents."""
        with patch("builtins.open", side_effect=_open_with_manifest(MANIFEST_WITH_CCI)):
            resp = scope_client.post(
                "/webhook/tradingview",
                data=json.dumps({
                    "secret": "WRONG_SECRET",
                    "strategy": "CCI Trend",
                    "symbol": "ETHUSDT",
                    "side": "BUY",
                    "price": "2500.0",
                }),
                content_type="application/json",
            )
        assert resp.status_code == 401, (
            f"Wrong secret must return 401, got {resp.status_code}"
        )
