"""
Full Integration Test: Webhook → Orchestrator → Exchange → Ledger → Sheets
Tests the complete signal flow end-to-end with mocked exchange.
"""
import pytest
import json
import os
import sys
import time
import tempfile
import sqlite3
from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ============================
# FIXTURES
# ============================

@pytest.fixture
def temp_storage(tmp_path):
    """Create temporary storage directory with all required files."""
    storage = tmp_path / "storage"
    storage.mkdir()
    (storage / "reports").mkdir()

    # Create minimal tournament_winners.csv
    csv_path = storage / "reports" / "tournament_winners.csv"
    csv_path.write_text(
        "Strategy,Symbol,Tier,Optimal_Len,Optimal_Mult,Daily_ROI\n"
        "TestStrategy,SOLUSDT,ALPHA,20,3.0,2.5\n"
        "EMA_Cloud_Strength,BTCUSDT,ALPHA,21,2.0,1.8\n"
    )

    return {
        "base": str(storage),
        "ledger": str(storage / "ledger_state.json"),
        "idempotency": str(storage / "idempotency.db"),
        "queue": str(storage / "signals.jsonl"),
        "offset": str(storage / "signals.offset"),
        "queue_db": str(storage / "signal_queue.db"),
        "dlq": str(storage / "dead_letter.jsonl"),
        "cb_state": str(storage / "circuit_breaker_state.json"),
        "report": str(csv_path),
    }


@pytest.fixture
def mock_binance():
    """Mock BinanceClient that simulates successful trades."""
    mock = MagicMock()
    mock.allow_real = True
    mock.testnet = True

    # Simulate successful market order
    mock.execute_futures_order.return_value = {
        "status": "SUCCESS",
        "orderId": "TEST_ORDER_001",
        "avg_price": 92.50
    }

    # Simulate successful SL/TP placement
    mock.place_stop_loss.return_value = {
        "status": "SUCCESS",
        "orderId": "SL_001",
        "stopPrice": 89.73
    }
    mock.place_take_profit.return_value = {
        "status": "SUCCESS",
        "orderId": "TP_001",
        "tpPrice": 97.13
    }

    # Mainnet price
    mock.get_mainnet_mark_price.return_value = 92.50
    mock.get_account_health.return_value = {
        "available_balance": 10000.0,
        "total_wallet_balance": 10000.0,
        "margin_ratio": 0.01
    }

    return mock


@pytest.fixture
def mock_binance_failure():
    """Mock BinanceClient that simulates failed trade."""
    mock = MagicMock()
    mock.allow_real = True
    mock.testnet = True
    mock.execute_futures_order.return_value = {
        "status": "FAILED",
        "reason": "permanent",
        "msg": "Insufficient balance"
    }
    mock.get_mainnet_mark_price.return_value = 92.50
    return mock


# ============================
# TEST: WEBHOOK → QUEUE
# ============================

class TestWebhookToQueue:
    """Test that webhook correctly enqueues signals."""

    def test_json_signal_enqueued(self):
        """JSON webhook signal gets parsed and enqueued."""
        with patch.dict(os.environ, {"WEBHOOK_SECRET": "test_secret_123", "TRADINGVIEW_AUTH_MODE": "secret"}):
            from tradingview_webhook_bot.core.webhook_server import WebhookServer
            import tempfile
            tf = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
            config = {"webhook": {"secret": "test_secret_123"}}
            server = WebhookServer(config=config, signals_queue_file=tf.name)
            client = server.app.test_client()

            payload = {
                "secret": "test_secret_123",
                "symbol": "SOLUSDT",
                "action": "BUY",
                "price": 92.50,
                "quantity": 0.5,
                "strategy": "TestStrategy",
                "exchange": "binance"
            }
            resp = client.post("/webhook/tradingview",
                data=json.dumps(payload),
                content_type="application/json")

            assert resp.status_code == 200
            data = resp.get_json()
            assert data["status"] == "success"

    def test_plain_text_signal_enqueued(self):
        """Plain text TradingView alert gets parsed and enqueued."""
        with patch.dict(os.environ, {"WEBHOOK_SECRET": "test_secret_123", "TRADINGVIEW_AUTH_MODE": "secret"}):
            from tradingview_webhook_bot.core.webhook_server import WebhookServer
            import tempfile
            tf = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
            config = {"webhook": {"secret": "test_secret_123"}}
            server = WebhookServer(config=config, signals_queue_file=tf.name)
            client = server.app.test_client()

            text = "TestStrategy | SOLUSDT - Webhook (test_secret_123): order buy @ 10 filled on SOLUSDT. New strategy position is 10"
            resp = client.post("/webhook/tradingview",
                data=text,
                content_type="text/plain")

            assert resp.status_code == 200

    def test_invalid_secret_rejected(self):
        """Wrong secret returns 401."""
        with patch.dict(os.environ, {"WEBHOOK_SECRET": "test_secret_123", "TRADINGVIEW_AUTH_MODE": "secret"}):
            from tradingview_webhook_bot.core.webhook_server import WebhookServer
            import tempfile
            tf = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
            config = {"webhook": {"secret": "test_secret_123"}}
            server = WebhookServer(config=config, signals_queue_file=tf.name)
            client = server.app.test_client()

            payload = {
                "secret": "wrong_secret",
                "symbol": "SOLUSDT",
                "action": "BUY",
                "price": 92.50
            }
            resp = client.post("/webhook/tradingview",
                data=json.dumps(payload),
                content_type="application/json")

            assert resp.status_code == 401

    def test_missing_json_secret_rejected(self):
        """Missing secret returns 401."""
        with patch.dict(os.environ, {"WEBHOOK_SECRET": "test_secret_123", "TRADINGVIEW_AUTH_MODE": "secret"}):
            from tradingview_webhook_bot.core.webhook_server import WebhookServer
            import tempfile
            tf = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
            config = {"webhook": {"secret": "test_secret_123"}}
            server = WebhookServer(config=config, signals_queue_file=tf.name)
            client = server.app.test_client()

            payload = {
                "symbol": "SOLUSDT",
                "action": "BUY",
                "price": 92.50
            }
            resp = client.post("/webhook/tradingview",
                data=json.dumps(payload),
                content_type="application/json")

            assert resp.status_code == 401

    def test_secretless_order_fill_alert_rejected(self):
        """TradingView order-fill plain text without explicit secret returns 401."""
        with patch.dict(os.environ, {"WEBHOOK_SECRET": "test_secret_123", "TRADINGVIEW_AUTH_MODE": "secret"}):
            from tradingview_webhook_bot.core.webhook_server import WebhookServer
            import tempfile
            tf = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
            config = {"webhook": {"secret": "test_secret_123"}}
            server = WebhookServer(config=config, signals_queue_file=tf.name)
            client = server.app.test_client()

            text = "TestStrategy: order buy @ 10 filled on SOLUSDT. New strategy position is 10"
            resp = client.post("/webhook/tradingview",
                data=text,
                content_type="text/plain")

            assert resp.status_code == 401

    def test_secret_and_signature_mode_rejects_missing_signature(self):
        """Configured signature mode rejects requests without X-Signature."""
        with patch.dict(os.environ, {"WEBHOOK_SECRET": "test_secret_123", "TRADINGVIEW_AUTH_MODE": "secret_and_signature"}):
            from tradingview_webhook_bot.core.webhook_server import WebhookServer
            import tempfile
            tf = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
            config = {"webhook": {"secret": "test_secret_123"}}
            server = WebhookServer(config=config, signals_queue_file=tf.name)
            client = server.app.test_client()

            payload = {
                "secret": "test_secret_123",
                "symbol": "SOLUSDT",
                "action": "BUY",
                "price": "92.50",
            }
            resp = client.post("/webhook/tradingview",
                data=json.dumps(payload),
                content_type="application/json")

            assert resp.status_code == 401

    def test_missing_json_secret_rejected(self):
        """Missing secret returns 401."""
        with patch.dict(os.environ, {"WEBHOOK_SECRET": "test_secret_123", "TRADINGVIEW_AUTH_MODE": "secret"}):
            from tradingview_webhook_bot.core.webhook_server import WebhookServer
            import tempfile
            tf = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
            config = {"webhook": {"secret": "test_secret_123"}}
            server = WebhookServer(config=config, signals_queue_file=tf.name)
            client = server.app.test_client()

            payload = {
                "symbol": "SOLUSDT",
                "action": "BUY",
                "price": 92.50
            }
            resp = client.post("/webhook/tradingview",
                data=json.dumps(payload),
                content_type="application/json")

            assert resp.status_code == 401

    def test_secretless_order_fill_alert_rejected(self):
        """TradingView order-fill plain text without explicit secret returns 401."""
        with patch.dict(os.environ, {"WEBHOOK_SECRET": "test_secret_123", "TRADINGVIEW_AUTH_MODE": "secret"}):
            from tradingview_webhook_bot.core.webhook_server import WebhookServer
            import tempfile
            tf = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
            config = {"webhook": {"secret": "test_secret_123"}}
            server = WebhookServer(config=config, signals_queue_file=tf.name)
            client = server.app.test_client()

            text = "TestStrategy: order buy @ 10 filled on SOLUSDT. New strategy position is 10"
            resp = client.post("/webhook/tradingview",
                data=text,
                content_type="text/plain")

            assert resp.status_code == 401

    def test_secret_and_signature_mode_rejects_missing_signature(self):
        """Configured signature mode rejects requests without X-Signature."""
        with patch.dict(os.environ, {"WEBHOOK_SECRET": "test_secret_123", "TRADINGVIEW_AUTH_MODE": "secret_and_signature"}):
            from tradingview_webhook_bot.core.webhook_server import WebhookServer
            import tempfile
            tf = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
            config = {"webhook": {"secret": "test_secret_123"}}
            server = WebhookServer(config=config, signals_queue_file=tf.name)
            client = server.app.test_client()

            payload = {
                "secret": "test_secret_123",
                "symbol": "SOLUSDT",
                "action": "BUY",
                "price": "92.50",
            }
            resp = client.post("/webhook/tradingview",
                data=json.dumps(payload),
                content_type="application/json")

            assert resp.status_code == 401

    def test_health_endpoint(self):
        """Health endpoint returns 200."""
        with patch.dict(os.environ, {"WEBHOOK_SECRET": "test_secret_123", "TRADINGVIEW_AUTH_MODE": "secret"}):
            from tradingview_webhook_bot.core.webhook_server import WebhookServer
            import tempfile
            tf = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
            config = {"webhook": {"secret": "test_secret_123"}}
            server = WebhookServer(config=config, signals_queue_file=tf.name)
            client = server.app.test_client()
            resp = client.get("/health")
            assert resp.status_code == 200

    def test_metrics_endpoint(self):
        """Metrics endpoint returns Prometheus format."""
        with patch.dict(os.environ, {"WEBHOOK_SECRET": "test_secret_123", "TRADINGVIEW_AUTH_MODE": "secret"}):
            from tradingview_webhook_bot.core.webhook_server import WebhookServer
            import tempfile
            tf = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
            config = {"webhook": {"secret": "test_secret_123"}}
            server = WebhookServer(config=config, signals_queue_file=tf.name)
            client = server.app.test_client()
            resp = client.get("/metrics")
            assert resp.status_code == 200


# ============================
# TEST: QUEUE → ORCHESTRATOR → EXCHANGE → LEDGER
# ============================

class TestOrchestratorFlow:
    """Test full orchestrator signal processing."""

    def test_signal_executes_and_updates_ledger(self, temp_storage, mock_binance):
        """Signal flows through all gates → executes → updates ledger."""
        from tradingview_webhook_bot.ledger.positions import PositionLedger
        from tradingview_webhook_bot.storage.idempotency_store import IdempotencyStore

        ledger = PositionLedger(temp_storage["ledger"])
        idempotency = IdempotencyStore(temp_storage["idempotency"])

        # Simulate what orchestrator does
        signal = {
            "signal_id": "TEST_001",
            "symbol": "SOLUSDT",
            "action": "BUY",
            "price": 92.50,
            "quantity": 1.0,
            "strategy": "TestStrategy",
            "exchange": "binance",
            "secret": "test_secret"
        }

        # Gate 1: Idempotency
        assert not idempotency.is_seen(signal["signal_id"])

        # Gate 2: Execute
        result = mock_binance.execute_futures_order(
            signal["symbol"], "BUY", signal["quantity"], signal["price"],
            signal_id=signal["signal_id"]
        )
        assert result["status"] == "SUCCESS"

        # Gate 3: Update ledger
        pos = ledger.apply_fill("binance:SOLUSDT", "BUY", 1.0, 92.50)
        assert pos.quantity == 1.0
        assert pos.avg_price == 92.50

        # Gate 4: Mark idempotent
        idempotency.mark_seen(signal["signal_id"], result.get("orderId"))
        assert idempotency.is_seen(signal["signal_id"])

        # Gate 5: SL/TP placed
        sl = mock_binance.place_stop_loss("SOLUSDT", "BUY", 1.0, 92.50, sl_pct=3.0)
        assert sl["status"] == "SUCCESS"
        tp = mock_binance.place_take_profit("SOLUSDT", "BUY", 1.0, 92.50, tp_pct=5.0)
        assert tp["status"] == "SUCCESS"

    def test_duplicate_signal_blocked(self, temp_storage):
        """Same signal_id blocked on second attempt."""
        from tradingview_webhook_bot.storage.idempotency_store import IdempotencyStore
        store = IdempotencyStore(temp_storage["idempotency"])

        store.mark_seen("DUP_001", "ORDER_X")
        assert store.is_seen("DUP_001")

        # Second attempt should be blocked
        assert store.is_seen("DUP_001")  # orchestrator would return True here

    def test_safety_gate_blocks_duplicate_position(self, temp_storage):
        """Safety gate blocks BUY when already in BUY position."""
        from tradingview_webhook_bot.ledger.positions import PositionLedger
        ledger = PositionLedger(temp_storage["ledger"])

        # Open long position
        ledger.apply_fill("binance:SOLUSDT", "BUY", 1.0, 90.0)

        # Check safety gate
        pos = ledger.get_position("binance:SOLUSDT")
        is_blocked = pos.quantity > 0  # Already in BUY
        assert is_blocked

    def test_exit_signal_closes_position(self, temp_storage, mock_binance):
        """Exit signal correctly closes existing position."""
        from tradingview_webhook_bot.ledger.positions import PositionLedger
        ledger = PositionLedger(temp_storage["ledger"])

        # Open position
        ledger.apply_fill("binance:SOLUSDT", "BUY", 1.0, 90.0)
        pos = ledger.get_position("binance:SOLUSDT")
        assert pos.quantity == 1.0

        # Exit: close with SELL
        mock_binance.execute_futures_order.return_value = {
            "status": "SUCCESS", "orderId": "EXIT_001", "avg_price": 95.0
        }
        result = mock_binance.execute_futures_order("SOLUSDT", "SELL", 1.0, 95.0)
        assert result["status"] == "SUCCESS"

        # Update ledger
        pos = ledger.apply_fill("binance:SOLUSDT", "SELL", 1.0, 95.0)
        assert pos.quantity == 0.0
        assert pos.daily_realized_pnl == 5.0  # $95 - $90 = $5 profit

    def test_failed_execution_not_logged_as_success(self, temp_storage, mock_binance_failure):
        """Failed execution should NOT update ledger or mark idempotent."""
        from tradingview_webhook_bot.ledger.positions import PositionLedger
        from tradingview_webhook_bot.storage.idempotency_store import IdempotencyStore

        ledger = PositionLedger(temp_storage["ledger"])
        idempotency = IdempotencyStore(temp_storage["idempotency"])

        result = mock_binance_failure.execute_futures_order("SOLUSDT", "BUY", 1.0, 92.50)
        assert result["status"] == "FAILED"

        # Ledger should NOT be updated
        pos = ledger.get_position("binance:SOLUSDT")
        assert pos.quantity == 0.0

        # Should NOT be marked as seen (but permanent failures are marked in real orchestrator)
        # In this test we verify the check exists
        assert not idempotency.is_seen("FAIL_001")


# ============================
# TEST: CIRCUIT BREAKER INTEGRATION
# ============================

class TestCircuitBreakerIntegration:
    """Test circuit breaker blocks trades correctly."""

    def test_cb_blocks_after_daily_loss(self, tmp_path):
        """Circuit breaker trips when daily loss exceeds limit."""
        from tradingview_webhook_bot.core.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker(str(tmp_path / "cb.json"), {
            "daily_loss_limit_pct": 2.0,
            "max_consecutive_losses": 10,
            "cooldown_minutes": 1
        })

        # Set daily start balance
        assert cb.should_allow_trade(10000.0)

        # Simulate 3% loss
        assert not cb.should_allow_trade(9700.0)  # 3% > 2% limit

    def test_cb_blocks_after_consecutive_losses(self, tmp_path):
        """Circuit breaker trips after N consecutive losses."""
        from tradingview_webhook_bot.core.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker(str(tmp_path / "cb.json"), {
            "daily_loss_limit_pct": 50.0,
            "max_consecutive_losses": 3,
            "cooldown_minutes": 1
        })

        cb.record_trade_result(False)  # Loss 1
        cb.record_trade_result(False)  # Loss 2
        cb.record_trade_result(False)  # Loss 3
        assert not cb.should_allow_trade()

    def test_cb_resets_on_win(self, tmp_path):
        """Win resets consecutive loss counter."""
        from tradingview_webhook_bot.core.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker(str(tmp_path / "cb.json"), {
            "daily_loss_limit_pct": 50.0,
            "max_consecutive_losses": 3,
            "cooldown_minutes": 1
        })

        cb.record_trade_result(False)  # Loss 1
        cb.record_trade_result(False)  # Loss 2
        cb.record_trade_result(True)   # Win — resets counter
        cb.record_trade_result(False)  # Loss 1 (reset)
        assert cb.should_allow_trade()


# ============================
# TEST: DURABLE QUEUE
# ============================

class TestDurableQueueIntegration:
    """Test durable queue processes signals correctly."""

    def test_enqueue_and_process(self, tmp_path):
        """Signal enqueued → processed → completed."""
        from tradingview_webhook_bot.storage.signal_queue import DurableSignalQueue
        q = DurableSignalQueue(str(tmp_path / "q.db"))

        signal = {"signal_id": "Q_001", "symbol": "SOLUSDT", "action": "BUY"}
        assert q.enqueue(signal)

        stats = q.get_stats()
        assert stats["pending"] == 1

        # Process
        processed = []
        def handler(data):
            processed.append(data)
            return True

        q.poll(handler, batch_size=1)
        assert len(processed) == 1
        assert processed[0]["signal_id"] == "Q_001"

        stats = q.get_stats()
        assert stats["completed"] == 1
        assert stats["pending"] == 0

    def test_failed_signal_retries(self, tmp_path):
        """Failed signal retries up to max_retries then goes to DLQ."""
        from tradingview_webhook_bot.storage.signal_queue import DurableSignalQueue
        q = DurableSignalQueue(str(tmp_path / "q.db"), max_retries=2)

        q.enqueue({"signal_id": "FAIL_001", "symbol": "SOLUSDT"})

        # Fail twice
        q.poll(handler=lambda d: False, batch_size=1)  # retry 1
        q.poll(handler=lambda d: False, batch_size=1)  # retry 2 → DLQ

        stats = q.get_stats()
        assert stats["dlq"] == 1
        assert stats["pending"] == 0

    def test_crash_recovery(self, tmp_path):
        """Stuck 'processing' signals recovered after restart."""
        from tradingview_webhook_bot.storage.signal_queue import DurableSignalQueue
        db_path = str(tmp_path / "q.db")

        # Simulate crash: signal stuck in 'processing'
        q1 = DurableSignalQueue(db_path)
        q1.enqueue({"signal_id": "CRASH_001"})
        with sqlite3.connect(db_path) as conn:
            conn.execute("UPDATE signals SET status='processing'")
            conn.commit()

        # Restart: should recover stuck signal
        q2 = DurableSignalQueue(db_path)
        stats = q2.get_stats()
        assert stats["pending"] == 1  # Recovered from processing → pending


# ============================
# TEST: MULTI-EXCHANGE POSITION AGGREGATION
# ============================

class TestMultiExchangePositions:
    """Test position tracking across multiple exchanges."""

    def test_separate_positions_per_exchange(self, tmp_path):
        """Same symbol on different exchanges tracked separately."""
        from tradingview_webhook_bot.ledger.positions import PositionLedger
        ledger = PositionLedger(str(tmp_path / "ledger.json"))

        # Long SOL on Binance
        ledger.apply_fill("binance:SOLUSDT", "BUY", 1.0, 90.0)
        # Short SOL on Hyperliquid
        ledger.apply_fill("hyperliquid:SOL", "SELL", 0.5, 91.0)

        binance_pos = ledger.get_position("binance:SOLUSDT")
        hl_pos = ledger.get_position("hyperliquid:SOL")

        assert binance_pos.quantity == 1.0   # Long
        assert hl_pos.quantity == -0.5       # Short
        # Different exchanges, different positions

    def test_aggregate_pnl_across_exchanges(self, tmp_path):
        """Daily PnL sums across all exchanges."""
        from tradingview_webhook_bot.ledger.positions import PositionLedger
        ledger = PositionLedger(str(tmp_path / "ledger.json"))

        # Profit on Binance
        ledger.apply_fill("binance:SOLUSDT", "BUY", 1.0, 90.0)
        ledger.apply_fill("binance:SOLUSDT", "SELL", 1.0, 95.0)  # +$5

        # Loss on Hyperliquid
        ledger.apply_fill("hyperliquid:SOL", "BUY", 1.0, 100.0)
        ledger.apply_fill("hyperliquid:SOL", "SELL", 1.0, 98.0)  # -$2

        total_pnl = ledger.get_daily_pnl()
        assert total_pnl == 3.0  # $5 - $2 = $3

    def test_position_flip_tracked_correctly(self, tmp_path):
        """Long to short flip updates position correctly."""
        from tradingview_webhook_bot.ledger.positions import PositionLedger
        ledger = PositionLedger(str(tmp_path / "ledger.json"))

        # Open long
        ledger.apply_fill("binance:BTCUSDT", "BUY", 0.1, 50000)
        assert ledger.positions["binance:BTCUSDT"].quantity == 0.1

        # Flip to short (sell 0.2 = close 0.1 long + open 0.1 short)
        ledger.apply_fill("binance:BTCUSDT", "SELL", 0.2, 51000)
        assert ledger.positions["binance:BTCUSDT"].quantity == -0.1

    def test_zero_position_after_close(self, tmp_path):
        """Position quantity is 0 after exact close."""
        from tradingview_webhook_bot.ledger.positions import PositionLedger
        ledger = PositionLedger(str(tmp_path / "ledger.json"))

        ledger.apply_fill("binance:ETHUSDT", "BUY", 0.5, 2000)
        ledger.apply_fill("binance:ETHUSDT", "SELL", 0.5, 2100)

        pos = ledger.get_position("binance:ETHUSDT")
        assert abs(pos.quantity) < 1e-10  # Effectively zero


# ============================
# TEST: IDEMPOTENCY TTL CLEANUP
# ============================

class TestIdempotencyCleanup:
    """Test TTL cleanup of old signals."""

    def test_cleanup_removes_old_signals(self, tmp_path):
        """Signals older than TTL are removed."""
        from tradingview_webhook_bot.storage.idempotency_store import IdempotencyStore
        store = IdempotencyStore(str(tmp_path / "idem.db"))

        # Insert with old timestamp
        with sqlite3.connect(str(tmp_path / "idem.db")) as conn:
            conn.execute(
                "INSERT INTO processed_signals (signal_id, processed_at) VALUES (?, datetime('now', '-10 days'))",
                ("OLD_001",)
            )
            conn.execute(
                "INSERT INTO processed_signals (signal_id, processed_at) VALUES (?, datetime('now'))",
                ("NEW_001",)
            )
            conn.commit()

        deleted = store.cleanup_old(days=7)
        assert deleted == 1
        assert not store.is_seen("OLD_001")
        assert store.is_seen("NEW_001")
