# Strategy Promotion Criteria

> Canonical document for moving strategies from Garima research lane into
> Harsh's .
>
> Last updated: 2026-04-29
> Owners: Garima (research output) + Harsh (manifest authority) + Sainath (final sign-off)

---

## Promotion Ladder



No step may be skipped. Research-lane evidence does not substitute for
paper-window evidence on the production exchange.

---

## Gate 1 — Backtest Provenance (required before paper_only entry)

| Requirement | Value |
|-------------|-------|
| Fixed notional per trade | 00 |
| Slippage | 0.1% per side |
| Commission | 0.04% taker (Binance Futures) |
| Out-of-sample split | 30% held out (time-ordered, no leakage) |
| Minimum total trades (full period) | 100 |
| Minimum OOS trades | 30 |
| OOS Sharpe | ≥ 0.5 |
| OOS Profit Factor | ≥ 1.05 |
| Max drawdown (full period) | ≤ 25% |
| Lookahead bias | Must be explicitly verified absent |
| Backtest hash | Required in manifest  field |

Garima's  uses a stricter threshold (Sharpe ≥ 0.8,
DSR_TCA > 0) — strategies that clear auto_discovery automatically satisfy Gate 1.

---

## Gate 2 — Paper Window (required before candidate_for_tiny_capital)

| Requirement | Value |
|-------------|-------|
| Minimum paper-window duration | 7 days |
| Minimum bot-visible signals | 5 |
| Minimum closed paper trades | 5 (4H strategies), 10 (1H), 20 (15m) |
| Signal source | Must arrive via TradingView webhook on production server |
| Exchange | Must execute on the same Binance Futures endpoint (testnet) |
| Paper P&L vs backtest OOS | Must be within ±40% of expected OOS daily ROI |

These are also the same thresholds enforced by ============================================================
  GO-LIVE GATE CHECK
============================================================

  [PASS] CI has no '|| true' bypass
  [PASS] Webhook auth is strict -- TRADINGVIEW_AUTH_MODE=secret
  [FAIL] WEBHOOK_SECRET is configured -- length=0
  [FAIL] STOP_LOSS_PCT is set -- value=NOT SET
  [FAIL] STOP_LOSS_PCT is safe (0.5�5.0%) -- value=0.0 � must be between 0.5 and 5.0
  [FAIL] TAKE_PROFIT_PCT is set -- value=NOT SET
  [FAIL] Circuit breaker daily loss configured -- CB_DAILY_LOSS_PCT=NOT SET
  [FAIL] Circuit breaker consecutive losses configured -- CB_MAX_CONSECUTIVE_LOSSES=NOT SET
  [FAIL] DAILY_LOSS_LIMIT is set -- value=NOT SET
  [FAIL] Leverage is configured -- value=NOT SET
  [PASS] GO_LIVE_GATE.md exists
  [FAIL] Pytest suite is discoverable -- FFFFFFFF................ssss............................................ [ 88%]
.........                                                                [100%]
================================== FAILURES ===================================
________________ TestWebhookToQueue.test_json_signal_enqueued _________________

self = <tests.test_integration_flow.TestWebhookToQueue object at 0x000001767932FD90>

    def test_json_signal_enqueued(self):
        """JSON webhook signal gets parsed and enqueued."""
        with patch.dict(os.environ, {"WEBHOOK_SECRET": "test_secret_123", "TRADINGVIEW_AUTH_MODE": "secret"}):
>           from tradingview_webhook_bot.core.webhook_server import WebhookServer

tests\test_integration_flow.py:113: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
tradingview_webhook_bot\core\webhook_server.py:28: in <module>
    from storage.jsonl_queue import AtomicJsonlQueue
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

    import json
    import os
>   import fcntl
E   ModuleNotFoundError: No module named 'fcntl'

tradingview_webhook_bot\storage\jsonl_queue.py:3: ModuleNotFoundError
_____________ TestWebhookToQueue.test_plain_text_signal_enqueued ______________

self = <tests.test_integration_flow.TestWebhookToQueue object at 0x000001767AD5AC10>

    def test_plain_text_signal_enqueued(self):
        """Plain text TradingView alert gets parsed and enqueued."""
        with patch.dict(os.environ, {"WEBHOOK_SECRET": "test_secret_123", "TRADINGVIEW_AUTH_MODE": "secret"}):
>           from tradingview_webhook_bot.core.webhook_server import WebhookServer

tests\test_integration_flow.py:141: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
tradingview_webhook_bot\core\webhook_server.py:28: in <module>
    from storage.jsonl_queue import AtomicJsonlQueue
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

    import json
    import os
>   import fcntl
E   ModuleNotFoundError: No module named 'fcntl'

tradingview_webhook_bot\storage\jsonl_queue.py:3: ModuleNotFoundError
_______________ TestWebhookToQueue.test_invalid_secret_rejected _______________

self = <tests.test_integration_flow.TestWebhookToQueue object at 0x000001767AD99480>

    def test_invalid_secret_rejected(self):
        """Wrong secret returns 401."""
        with patch.dict(os.environ, {"WEBHOOK_SECRET": "test_secret_123", "TRADINGVIEW_AUTH_MODE": "secret"}):
>           from tradingview_webhook_bot.core.webhook_server import WebhookServer

tests\test_integration_flow.py:159: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
tradingview_webhook_bot\core\webhook_server.py:28: in <module>
    from storage.jsonl_queue import AtomicJsonlQueue
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

    import json
    import os
>   import fcntl
E   ModuleNotFoundError: No module named 'fcntl'

tradingview_webhook_bot\storage\jsonl_queue.py:3: ModuleNotFoundError
____________ TestWebhookToQueue.test_missing_json_secret_rejected _____________

self = <tests.test_integration_flow.TestWebhookToQueue object at 0x000001767AD99940>

    def test_missing_json_secret_rejected(self):
        """Missing secret returns 401."""
        with patch.dict(os.environ, {"WEBHOOK_SECRET": "test_secret_123", "TRADINGVIEW_AUTH_MODE": "secret"}):
>           from tradingview_webhook_bot.core.webhook_server import WebhookServer

tests\test_integration_flow.py:227: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
tradingview_webhook_bot\core\webhook_server.py:28: in <module>
    from storage.jsonl_queue import AtomicJsonlQueue
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

    import json
    import os
>   import fcntl
E   ModuleNotFoundError: No module named 'fcntl'

tradingview_webhook_bot\storage\jsonl_queue.py:3: ModuleNotFoundError
_ TestWebhookToQueue.test_secret_and_signature_mode_rejects_missing_signature _

self = <tests.test_integration_flow.TestWebhookToQueue object at 0x000001767B62C950>

    def test_secret_and_signature_mode_rejects_missing_signature(self):
        """Configured signature mode rejects requests without X-Signature."""
        with patch.dict(os.environ, {"WEBHOOK_SECRET": "test_secret_123", "TRADINGVIEW_AUTH_MODE": "secret_and_signature"}):
>           from tradingview_webhook_bot.core.webhook_server import WebhookServer

tests\test_integration_flow.py:268: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
tradingview_webhook_bot\core\webhook_server.py:28: in <module>
    from storage.jsonl_queue import AtomicJsonlQueue
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

    import json
    import os
>   import fcntl
E   ModuleNotFoundError: No module named 'fcntl'

tradingview_webhook_bot\storage\jsonl_queue.py:3: ModuleNotFoundError
___ TestWebhookToQueue.test_secretless_order_fill_unknown_strategy_rejected ___

self = <tests.test_integration_flow.TestWebhookToQueue object at 0x000001767B5F87C0>

    def test_secretless_order_fill_unknown_strategy_rejected(self):
        """P-06: secretless TV order-fill for a strategy not in manifest returns 403."""
        with patch.dict(os.environ, {"WEBHOOK_SECRET": "test_secret_123", "TRADINGVIEW_AUTH_MODE": "secret"}):
>           from tradingview_webhook_bot.core.webhook_server import WebhookServer

tests\test_integration_flow.py:249: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
tradingview_webhook_bot\core\webhook_server.py:28: in <module>
    from storage.jsonl_queue import AtomicJsonlQueue
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

    import json
    import os
>   import fcntl
E   ModuleNotFoundError: No module named 'fcntl'

tradingview_webhook_bot\storage\jsonl_queue.py:3: ModuleNotFoundError
___________________ TestWebhookToQueue.test_health_endpoint ___________________

self = <tests.test_integration_flow.TestWebhookToQueue object at 0x000001767B5F89E0>

    def test_health_endpoint(self):
        """Health endpoint returns 200."""
        with patch.dict(os.environ, {"WEBHOOK_SECRET": "test_secret_123", "TRADINGVIEW_AUTH_MODE": "secret"}):
>           from tradingview_webhook_bot.core.webhook_server import WebhookServer

tests\test_integration_flow.py:291: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
tradingview_webhook_bot\core\webhook_server.py:28: in <module>
    from storage.jsonl_queue import AtomicJsonlQueue
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

    import json
    import os
>   import fcntl
E   ModuleNotFoundError: No module named 'fcntl'

tradingview_webhook_bot\storage\jsonl_queue.py:3: ModuleNotFoundError
__________________ TestWebhookToQueue.test_metrics_endpoint ___________________

self = <tests.test_integration_flow.TestWebhookToQueue object at 0x0000017679360750>

    def test_metrics_endpoint(self):
        """Metrics endpoint returns Prometheus format."""
        with patch.dict(os.environ, {"WEBHOOK_SECRET": "test_secret_123", "TRADINGVIEW_AUTH_MODE": "secret"}):
>           from tradingview_webhook_bot.core.webhook_server import WebhookServer

tests\test_integration_flow.py:304: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
tradingview_webhook_bot\core\webhook_server.py:28: in <module>
    from storage.jsonl_queue import AtomicJsonlQueue
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

    import json
    import os
>   import fcntl
E   ModuleNotFoundError: No module named 'fcntl'

tradingview_webhook_bot\storage\jsonl_queue.py:3: ModuleNotFoundError
============================== warnings summary ===============================
tests/test_integration_flow.py: 14 warnings
tests/test_orchestrator_flow.py: 18 warnings
  D:\tradingview_webhook_bot\tradingview_webhook_bot\ledger\positions.py:103: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
    today = datetime.utcnow().strftime('%Y-%m-%d')

tests/test_integration_flow.py: 5 warnings
tests/test_orchestrator_flow.py: 6 warnings
  D:\tradingview_webhook_bot\tradingview_webhook_bot\ledger\positions.py:132: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
    "timestamp": datetime.utcnow().isoformat(),

tests/test_integration_flow.py::TestMultiExchangePositions::test_aggregate_pnl_across_exchanges
tests/test_orchestrator_flow.py::TestLedger::test_daily_pnl_tracking
tests/test_orchestrator_flow.py::TestSafetyGateLogic::test_daily_pnl_blocks_when_exceeded
  D:\tradingview_webhook_bot\tradingview_webhook_bot\ledger\positions.py:85: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
    today = datetime.utcnow().strftime('%Y-%m-%d')

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ===========================
FAILED tests/test_integration_flow.py::TestWebhookToQueue::test_json_signal_enqueued
FAILED tests/test_integration_flow.py::TestWebhookToQueue::test_plain_text_signal_enqueued
FAILED tests/test_integration_flow.py::TestWebhookToQueue::test_invalid_secret_rejected
FAILED tests/test_integration_flow.py::TestWebhookToQueue::test_missing_json_secret_rejected
FAILED tests/test_integration_flow.py::TestWebhookToQueue::test_secret_and_signature_mode_rejects_missing_signature
FAILED tests/test_integration_flow.py::TestWebhookToQueue::test_secretless_order_fill_unknown_strategy_rejected
FAILED tests/test_integration_flow.py::TestWebhookToQueue::test_health_endpoint
FAILED tests/test_integration_flow.py::TestWebhookToQueue::test_metrics_endpoint
  [FAIL] Ledger state file exists -- D:\tradingview_webhook_bot\tradingview_webhook_bot\storage\ledger_state.json
  [FAIL] Idempotency DB exists -- D:\tradingview_webhook_bot\tradingview_webhook_bot\storage\idempotency.db
  [PASS] Approval manifest is populated -- 30 strategies approved
  [PASS] Manifest entries have provenance (hash + notes) -- All entries have backtest_hash and notes
  [PASS] Manifest scope is explicit and limited -- 2 candidate_for_tiny_capital; 28 paper_only
  [PASS] TradingView inventory report refreshed -- D:\tradingview_webhook_bot\storage\reports\tv_inventory_report.csv
  [FAIL] Candidate paper-lane inventory verified -- CCI Trend:ETHUSDT=MISSING; Donchian Trend:ETHUSDT=MISSING
  [FAIL] Paper window duration complete -- Day 23 of 7; 0 daily reports present
  [FAIL] No critical reconciler drifts during paper window -- 0 critical SIDE_MISMATCH drift(s) across 0 recon snapshot(s)
  [FAIL] Execution-plane freeze intact -- D:\tradingview_webhook_bot\storage\reports\paper_validation\execution_freeze_latest.json missing
  [PASS] Dead letter queue is clean -- Clean
  [FAIL] Signal pipeline active (last signal < 48h) -- signal_queue.db missing
  [FAIL] Approved-lane signals fired during paper window -- signal_queue.db missing
  [FAIL] No stale non-lane positions open -- stale_position_gate error: [Errno 2] No such file or directory: 'D:\\tradingview_webhook_bot\\tradingview_webhook_bot\\storage\\ledger_state.json'
  [FAIL] Candidates have min closed paper trades (4H=5,1H=10,15m=20) -- execution_metrics.jsonl missing � cannot verify closed-trade count
  [FAIL] Decision-lane ETHUSDT signal active (<72h) -- No ETHUSDT decision-lane signal ever recorded (queue DB empty, metrics file missing)
  [PASS] Candidate family/symbol concentration within limits -- families=cci:1, donchian:1
  [PASS] Decision-lane candidates not in BLOCKED_STRATEGY_NAMES -- BLOCKED_STRATEGY_NAMES=''

============================================================
  VERDICT: NO-GO  (20 of 30 gates FAILED)

    FAIL: WEBHOOK_SECRET is configured -- length=0
    FAIL: STOP_LOSS_PCT is set -- value=NOT SET
    FAIL: STOP_LOSS_PCT is safe (0.5�5.0%) -- value=0.0 � must be between 0.5 and 5.0
    FAIL: TAKE_PROFIT_PCT is set -- value=NOT SET
    FAIL: Circuit breaker daily loss configured -- CB_DAILY_LOSS_PCT=NOT SET
    FAIL: Circuit breaker consecutive losses configured -- CB_MAX_CONSECUTIVE_LOSSES=NOT SET
    FAIL: DAILY_LOSS_LIMIT is set -- value=NOT SET
    FAIL: Leverage is configured -- value=NOT SET
    FAIL: Pytest suite is discoverable -- FFFFFFFF................ssss............................................ [ 88%]
.........                                                                [100%]
================================== FAILURES ===================================
________________ TestWebhookToQueue.test_json_signal_enqueued _________________

self = <tests.test_integration_flow.TestWebhookToQueue object at 0x000001767932FD90>

    def test_json_signal_enqueued(self):
        """JSON webhook signal gets parsed and enqueued."""
        with patch.dict(os.environ, {"WEBHOOK_SECRET": "test_secret_123", "TRADINGVIEW_AUTH_MODE": "secret"}):
>           from tradingview_webhook_bot.core.webhook_server import WebhookServer

tests\test_integration_flow.py:113: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
tradingview_webhook_bot\core\webhook_server.py:28: in <module>
    from storage.jsonl_queue import AtomicJsonlQueue
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

    import json
    import os
>   import fcntl
E   ModuleNotFoundError: No module named 'fcntl'

tradingview_webhook_bot\storage\jsonl_queue.py:3: ModuleNotFoundError
_____________ TestWebhookToQueue.test_plain_text_signal_enqueued ______________

self = <tests.test_integration_flow.TestWebhookToQueue object at 0x000001767AD5AC10>

    def test_plain_text_signal_enqueued(self):
        """Plain text TradingView alert gets parsed and enqueued."""
        with patch.dict(os.environ, {"WEBHOOK_SECRET": "test_secret_123", "TRADINGVIEW_AUTH_MODE": "secret"}):
>           from tradingview_webhook_bot.core.webhook_server import WebhookServer

tests\test_integration_flow.py:141: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
tradingview_webhook_bot\core\webhook_server.py:28: in <module>
    from storage.jsonl_queue import AtomicJsonlQueue
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

    import json
    import os
>   import fcntl
E   ModuleNotFoundError: No module named 'fcntl'

tradingview_webhook_bot\storage\jsonl_queue.py:3: ModuleNotFoundError
_______________ TestWebhookToQueue.test_invalid_secret_rejected _______________

self = <tests.test_integration_flow.TestWebhookToQueue object at 0x000001767AD99480>

    def test_invalid_secret_rejected(self):
        """Wrong secret returns 401."""
        with patch.dict(os.environ, {"WEBHOOK_SECRET": "test_secret_123", "TRADINGVIEW_AUTH_MODE": "secret"}):
>           from tradingview_webhook_bot.core.webhook_server import WebhookServer

tests\test_integration_flow.py:159: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
tradingview_webhook_bot\core\webhook_server.py:28: in <module>
    from storage.jsonl_queue import AtomicJsonlQueue
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

    import json
    import os
>   import fcntl
E   ModuleNotFoundError: No module named 'fcntl'

tradingview_webhook_bot\storage\jsonl_queue.py:3: ModuleNotFoundError
____________ TestWebhookToQueue.test_missing_json_secret_rejected _____________

self = <tests.test_integration_flow.TestWebhookToQueue object at 0x000001767AD99940>

    def test_missing_json_secret_rejected(self):
        """Missing secret returns 401."""
        with patch.dict(os.environ, {"WEBHOOK_SECRET": "test_secret_123", "TRADINGVIEW_AUTH_MODE": "secret"}):
>           from tradingview_webhook_bot.core.webhook_server import WebhookServer

tests\test_integration_flow.py:227: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
tradingview_webhook_bot\core\webhook_server.py:28: in <module>
    from storage.jsonl_queue import AtomicJsonlQueue
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

    import json
    import os
>   import fcntl
E   ModuleNotFoundError: No module named 'fcntl'

tradingview_webhook_bot\storage\jsonl_queue.py:3: ModuleNotFoundError
_ TestWebhookToQueue.test_secret_and_signature_mode_rejects_missing_signature _

self = <tests.test_integration_flow.TestWebhookToQueue object at 0x000001767B62C950>

    def test_secret_and_signature_mode_rejects_missing_signature(self):
        """Configured signature mode rejects requests without X-Signature."""
        with patch.dict(os.environ, {"WEBHOOK_SECRET": "test_secret_123", "TRADINGVIEW_AUTH_MODE": "secret_and_signature"}):
>           from tradingview_webhook_bot.core.webhook_server import WebhookServer

tests\test_integration_flow.py:268: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
tradingview_webhook_bot\core\webhook_server.py:28: in <module>
    from storage.jsonl_queue import AtomicJsonlQueue
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

    import json
    import os
>   import fcntl
E   ModuleNotFoundError: No module named 'fcntl'

tradingview_webhook_bot\storage\jsonl_queue.py:3: ModuleNotFoundError
___ TestWebhookToQueue.test_secretless_order_fill_unknown_strategy_rejected ___

self = <tests.test_integration_flow.TestWebhookToQueue object at 0x000001767B5F87C0>

    def test_secretless_order_fill_unknown_strategy_rejected(self):
        """P-06: secretless TV order-fill for a strategy not in manifest returns 403."""
        with patch.dict(os.environ, {"WEBHOOK_SECRET": "test_secret_123", "TRADINGVIEW_AUTH_MODE": "secret"}):
>           from tradingview_webhook_bot.core.webhook_server import WebhookServer

tests\test_integration_flow.py:249: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
tradingview_webhook_bot\core\webhook_server.py:28: in <module>
    from storage.jsonl_queue import AtomicJsonlQueue
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

    import json
    import os
>   import fcntl
E   ModuleNotFoundError: No module named 'fcntl'

tradingview_webhook_bot\storage\jsonl_queue.py:3: ModuleNotFoundError
___________________ TestWebhookToQueue.test_health_endpoint ___________________

self = <tests.test_integration_flow.TestWebhookToQueue object at 0x000001767B5F89E0>

    def test_health_endpoint(self):
        """Health endpoint returns 200."""
        with patch.dict(os.environ, {"WEBHOOK_SECRET": "test_secret_123", "TRADINGVIEW_AUTH_MODE": "secret"}):
>           from tradingview_webhook_bot.core.webhook_server import WebhookServer

tests\test_integration_flow.py:291: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
tradingview_webhook_bot\core\webhook_server.py:28: in <module>
    from storage.jsonl_queue import AtomicJsonlQueue
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

    import json
    import os
>   import fcntl
E   ModuleNotFoundError: No module named 'fcntl'

tradingview_webhook_bot\storage\jsonl_queue.py:3: ModuleNotFoundError
__________________ TestWebhookToQueue.test_metrics_endpoint ___________________

self = <tests.test_integration_flow.TestWebhookToQueue object at 0x0000017679360750>

    def test_metrics_endpoint(self):
        """Metrics endpoint returns Prometheus format."""
        with patch.dict(os.environ, {"WEBHOOK_SECRET": "test_secret_123", "TRADINGVIEW_AUTH_MODE": "secret"}):
>           from tradingview_webhook_bot.core.webhook_server import WebhookServer

tests\test_integration_flow.py:304: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
tradingview_webhook_bot\core\webhook_server.py:28: in <module>
    from storage.jsonl_queue import AtomicJsonlQueue
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

    import json
    import os
>   import fcntl
E   ModuleNotFoundError: No module named 'fcntl'

tradingview_webhook_bot\storage\jsonl_queue.py:3: ModuleNotFoundError
============================== warnings summary ===============================
tests/test_integration_flow.py: 14 warnings
tests/test_orchestrator_flow.py: 18 warnings
  D:\tradingview_webhook_bot\tradingview_webhook_bot\ledger\positions.py:103: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
    today = datetime.utcnow().strftime('%Y-%m-%d')

tests/test_integration_flow.py: 5 warnings
tests/test_orchestrator_flow.py: 6 warnings
  D:\tradingview_webhook_bot\tradingview_webhook_bot\ledger\positions.py:132: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
    "timestamp": datetime.utcnow().isoformat(),

tests/test_integration_flow.py::TestMultiExchangePositions::test_aggregate_pnl_across_exchanges
tests/test_orchestrator_flow.py::TestLedger::test_daily_pnl_tracking
tests/test_orchestrator_flow.py::TestSafetyGateLogic::test_daily_pnl_blocks_when_exceeded
  D:\tradingview_webhook_bot\tradingview_webhook_bot\ledger\positions.py:85: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
    today = datetime.utcnow().strftime('%Y-%m-%d')

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ===========================
FAILED tests/test_integration_flow.py::TestWebhookToQueue::test_json_signal_enqueued
FAILED tests/test_integration_flow.py::TestWebhookToQueue::test_plain_text_signal_enqueued
FAILED tests/test_integration_flow.py::TestWebhookToQueue::test_invalid_secret_rejected
FAILED tests/test_integration_flow.py::TestWebhookToQueue::test_missing_json_secret_rejected
FAILED tests/test_integration_flow.py::TestWebhookToQueue::test_secret_and_signature_mode_rejects_missing_signature
FAILED tests/test_integration_flow.py::TestWebhookToQueue::test_secretless_order_fill_unknown_strategy_rejected
FAILED tests/test_integration_flow.py::TestWebhookToQueue::test_health_endpoint
FAILED tests/test_integration_flow.py::TestWebhookToQueue::test_metrics_endpoint
    FAIL: Ledger state file exists -- D:\tradingview_webhook_bot\tradingview_webhook_bot\storage\ledger_state.json
    FAIL: Idempotency DB exists -- D:\tradingview_webhook_bot\tradingview_webhook_bot\storage\idempotency.db
    FAIL: Candidate paper-lane inventory verified -- CCI Trend:ETHUSDT=MISSING; Donchian Trend:ETHUSDT=MISSING
    FAIL: Paper window duration complete -- Day 23 of 7; 0 daily reports present
    FAIL: No critical reconciler drifts during paper window -- 0 critical SIDE_MISMATCH drift(s) across 0 recon snapshot(s)
    FAIL: Execution-plane freeze intact -- D:\tradingview_webhook_bot\storage\reports\paper_validation\execution_freeze_latest.json missing
    FAIL: Signal pipeline active (last signal < 48h) -- signal_queue.db missing
    FAIL: Approved-lane signals fired during paper window -- signal_queue.db missing
    FAIL: No stale non-lane positions open -- stale_position_gate error: [Errno 2] No such file or directory: 'D:\\tradingview_webhook_bot\\tradingview_webhook_bot\\storage\\ledger_state.json'
    FAIL: Candidates have min closed paper trades (4H=5,1H=10,15m=20) -- execution_metrics.jsonl missing � cannot verify closed-trade count
    FAIL: Decision-lane ETHUSDT signal active (<72h) -- No ETHUSDT decision-lane signal ever recorded (queue DB empty, metrics file missing)
============================================================
gate #16 and [auto_promote] FREEZE ACTIVE � checkpoint in progress. No promotions written. Set AUTO_PROMOTE_FREEZE=false to override..

---

## Gate 3 — Human Review (required before candidate_for_tiny_capital with real capital)

1. Sainath reviews the backtest hash + OOS metrics.
2. Harsh verifies TradingView alert is correctly wired and signals are flowing.
3. Manifest entry is updated with  and .
4.  must return VERDICT: GO (all 30 gates pass).
5.  6-step checklist must be completed.

AUTO_PROMOTED entries (set by ) skip step 1–2 above only if
 is explicitly set. The default is  (frozen).

---

## Canonical Repository

- **Harsh execution repo** (source of truth for manifest): 
- **Garima research repo** (source of truth for discoveries):  on GitHub
- **Nomination path**: Garima posts discovery hash + metrics → Harsh adds  entry →
  paper window runs →  or manual promotion to  →
  Sainath review → 

---

## What Is NOT Sufficient for Promotion

- Backtest profit alone (without OOS split and hash)
- Paper sim engine results (these use different SL/TP/notional than the live strategy)
- Garima's  results alone (they satisfy Gate 1 only)
- Runtime logs or Telegram reports without corresponding committed evidence
