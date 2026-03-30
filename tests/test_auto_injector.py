import sqlite3
from pathlib import Path

from scripts import auto_injector


def _build_signal_db(db_path: Path, created_at_values):
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE signals (
                id INTEGER PRIMARY KEY,
                signal_id TEXT,
                payload TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                retries INTEGER DEFAULT 0,
                created_at REAL,
                processed_at REAL,
                error TEXT
            )
            """
        )
        for idx, created_at in enumerate(created_at_values, start=1):
            conn.execute(
                """
                INSERT INTO signals (signal_id, payload, status, created_at)
                VALUES (?, '{}', 'completed', ?)
                """,
                (f"TV-{idx}", created_at),
            )
        conn.commit()


def test_recent_signal_activity_detects_quiet_hour(tmp_path, monkeypatch):
    db_path = tmp_path / "signal_queue.db"
    _build_signal_db(db_path, [])
    monkeypatch.setattr(auto_injector, "SIGNAL_DB_PATH", db_path)

    has_recent_signals, detail = auto_injector.check_recent_signal_activity(lookback_minutes=60)

    assert has_recent_signals is False
    assert "No queued signals" in detail


def test_recent_signal_activity_detects_live_signals(tmp_path, monkeypatch):
    db_path = tmp_path / "signal_queue.db"
    recent_timestamp = auto_injector.datetime.utcnow().timestamp() - 120
    _build_signal_db(db_path, [recent_timestamp])
    monkeypatch.setattr(auto_injector, "SIGNAL_DB_PATH", db_path)

    has_recent_signals, detail = auto_injector.check_recent_signal_activity(lookback_minutes=60)

    assert has_recent_signals is True
    assert "queued signal" in detail


def test_run_scan_sends_quiet_hour_confirmation(monkeypatch):
    sent_messages = []

    monkeypatch.setattr(auto_injector, "check_webhook_server", lambda: True)
    monkeypatch.setattr(auto_injector, "check_systemd_service", lambda service_name, process_fallback="": True)
    monkeypatch.setattr(auto_injector, "check_dashboard_server", lambda: True)
    monkeypatch.setattr(auto_injector, "check_data_freshness", lambda: (True, "Fresh (1.0h ago)"))
    monkeypatch.setattr(auto_injector, "check_dlq", lambda: 0)
    monkeypatch.setattr(
        auto_injector,
        "check_recent_signal_activity",
        lambda lookback_minutes=60: (False, "No queued signals in last 60m"),
    )
    monkeypatch.setattr(
        auto_injector,
        "assess_tradingview_feed",
        lambda: ("warn", "Quiet market: no signals in last 60m (last 2026-03-28 11:00:00 UTC)"),
    )
    monkeypatch.setattr(auto_injector, "send_alert", sent_messages.append)

    auto_injector.run_scan()

    assert len(sent_messages) == 1
    assert "HOURLY LIVE CONFIRMATION" in sent_messages[0]
    assert "✅ <b>Webhook:</b> UP" in sent_messages[0]
    assert "✅ <b>Orchestrator:</b> RUNNING" in sent_messages[0]
    assert "✅ <b>Dashboard:</b> UP" in sent_messages[0]
    assert "⚠️ <b>TradingView Feed:</b> Quiet market" in sent_messages[0]
    assert "No queued signals in last 60m" in sent_messages[0]


def test_run_scan_alerts_when_signal_db_is_missing(monkeypatch):
    sent_messages = []

    monkeypatch.setattr(auto_injector, "check_webhook_server", lambda: True)
    monkeypatch.setattr(auto_injector, "check_systemd_service", lambda service_name, process_fallback="": True)
    monkeypatch.setattr(auto_injector, "check_dashboard_server", lambda: True)
    monkeypatch.setattr(auto_injector, "check_data_freshness", lambda: (True, "Fresh (1.0h ago)"))
    monkeypatch.setattr(auto_injector, "check_dlq", lambda: 0)
    monkeypatch.setattr(
        auto_injector,
        "check_recent_signal_activity",
        lambda lookback_minutes=60: (
            False,
            "signal_queue.db missing (/tmp/missing.db)",
        ),
    )
    monkeypatch.setattr(
        auto_injector,
        "assess_tradingview_feed",
        lambda: ("down", "signal_queue.db missing (/tmp/missing.db)"),
    )
    monkeypatch.setattr(auto_injector, "send_alert", sent_messages.append)

    auto_injector.run_scan()

    assert len(sent_messages) == 1
    assert "HOURLY HEARTBEAT ALERT" in sent_messages[0]
    assert "Signal activity check issue" in sent_messages[0]
    assert "❌ <b>Signal Queue DB:</b> signal_queue.db missing (/tmp/missing.db)" in sent_messages[0]


def test_run_scan_alerts_when_tradingview_feed_looks_stuck(monkeypatch):
    sent_messages = []

    monkeypatch.setattr(auto_injector, "check_webhook_server", lambda: True)
    monkeypatch.setattr(auto_injector, "check_systemd_service", lambda service_name, process_fallback="": True)
    monkeypatch.setattr(auto_injector, "check_dashboard_server", lambda: True)
    monkeypatch.setattr(auto_injector, "check_data_freshness", lambda: (True, "Fresh (1.0h ago)"))
    monkeypatch.setattr(auto_injector, "check_dlq", lambda: 0)
    monkeypatch.setattr(
        auto_injector,
        "check_recent_signal_activity",
        lambda lookback_minutes=60: (False, "No queued signals in last 60m"),
    )
    monkeypatch.setattr(
        auto_injector,
        "assess_tradingview_feed",
        lambda: ("down", "TradingView feed may be stuck: no signals for 240m (last 2026-03-28 08:00:00 UTC)"),
    )
    monkeypatch.setattr(auto_injector, "send_alert", sent_messages.append)

    auto_injector.run_scan()

    assert len(sent_messages) == 1
    assert "HOURLY HEARTBEAT ALERT" in sent_messages[0]
    assert "TradingView feed may be stuck" in sent_messages[0]
    assert "❌ <b>TradingView Feed:</b>" in sent_messages[0]
