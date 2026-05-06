"""Integration tests for scripts/paper_sim_engine.py (paper PnL tracker)."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import paper_sim_engine as pse


# ─── helpers ───────────────────────────────────────────────────────────────────

def _make_db(db_path: Path, rows: list[tuple]) -> None:
    """Build a minimal signal_queue.db for testing."""
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
        for i, (payload_dict, status, created_at) in enumerate(rows, start=1):
            conn.execute(
                "INSERT INTO signals (signal_id, payload, status, created_at) VALUES (?,?,?,?)",
                (f"TV-{i}", json.dumps(payload_dict), status, created_at),
            )
        conn.commit()


def _make_manifest(path: Path, approvals: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "approvals": approvals}))


def _kline(open_=2000, high=2100, low=1900, close=2050):
    """Return a minimal Binance kline row."""
    return [0, str(open_), str(high), str(low), str(close), "100", 0, "0", 0, "0", "0", "0"]


# ─── _determine_action ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("payload,expected", [
    ({"action": "buy"},        "long"),
    ({"action": "LONG"},       "long"),
    ({"action": "entry_long"}, "long"),
    ({"action": "sell"},       "short"),
    ({"action": "SHORT"},      "short"),
    ({"action": "entry_short"},"short"),
    ({"action": "exit"},       "exit"),
    ({"action": "close"},      "exit"),
    ({"signal": "flat"},       "exit"),
    ({"side": "buy"},          "long"),
    ({},                       None),
])
def test_determine_action(payload, expected):
    assert pse._determine_action(payload) == expected


# ─── _tf_to_interval ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("tf,expected", [
    ("240", "4h"),
    ("60",  "1h"),
    ("15",  "15m"),
    ("1d",  "1d"),
    ("D",   "1d"),
    ("5",   "5m"),
    ("120", "2h"),
])
def test_tf_to_interval(tf, expected):
    assert pse._tf_to_interval(tf) == expected


# ─── _extract_payload ──────────────────────────────────────────────────────────

def test_extract_payload_nested():
    raw = json.dumps({"payload": {"strategy": "Donchian_40", "action": "buy"}})
    result = pse._extract_payload(raw)
    assert result["strategy"] == "Donchian_40"


def test_extract_payload_flat():
    raw = json.dumps({"strategy": "Test", "action": "sell"})
    result = pse._extract_payload(raw)
    assert result["strategy"] == "Test"


def test_extract_payload_invalid_json():
    result = pse._extract_payload("not-json")
    assert result == {}


# ─── _simulate_trade — long TP hit ─────────────────────────────────────────────

def test_simulate_trade_long_tp(monkeypatch):
    # TP hit on first candle: high (2200) > tp_price (entry*1.04 = 2080)
    monkeypatch.setattr(pse, "_binance_klines", lambda *a, **kw: [
        _kline(open_=2000, high=2200, low=1990, close=2100),
    ])
    result = pse._simulate_trade(
        entry_price=2000.0, side="long", symbol="ETHUSDT",
        interval="4h", entry_ts_ms=0, sl_pct=2.0, tp_pct=4.0, notional=500.0,
    )
    assert result["exit_reason"] == "TP"
    assert result["exit_price"] == pytest.approx(2000 * 1.04, rel=1e-6)
    assert result["pnl_usd"] > 0
    assert result["bars_held"] == 1


# ─── _simulate_trade — long SL hit ─────────────────────────────────────────────

def test_simulate_trade_long_sl(monkeypatch):
    # SL hit: low (1900) < sl_price (2000*0.98 = 1960)
    monkeypatch.setattr(pse, "_binance_klines", lambda *a, **kw: [
        _kline(open_=2000, high=2010, low=1900, close=1950),
    ])
    result = pse._simulate_trade(
        entry_price=2000.0, side="long", symbol="ETHUSDT",
        interval="4h", entry_ts_ms=0, sl_pct=2.0, tp_pct=4.0, notional=500.0,
    )
    assert result["exit_reason"] == "SL"
    assert result["exit_price"] == pytest.approx(2000 * 0.98, rel=1e-6)
    assert result["pnl_usd"] < 0


# ─── _simulate_trade — short TP hit ────────────────────────────────────────────

def test_simulate_trade_short_tp(monkeypatch):
    # Short TP: low (1850) < tp_price (2000*0.96=1920)
    monkeypatch.setattr(pse, "_binance_klines", lambda *a, **kw: [
        _kline(open_=2000, high=2010, low=1850, close=1900),
    ])
    result = pse._simulate_trade(
        entry_price=2000.0, side="short", symbol="ETHUSDT",
        interval="4h", entry_ts_ms=0, sl_pct=2.0, tp_pct=4.0, notional=500.0,
    )
    assert result["exit_reason"] == "TP"
    assert result["pnl_usd"] > 0


# ─── _simulate_trade — timeout ─────────────────────────────────────────────────

def test_simulate_trade_timeout(monkeypatch):
    # Neither SL nor TP hit — exit at last close
    flat_candle = _kline(open_=2000, high=2005, low=1995, close=2002)
    monkeypatch.setattr(pse, "_binance_klines", lambda *a, **kw: [flat_candle] * 3)
    result = pse._simulate_trade(
        entry_price=2000.0, side="long", symbol="ETHUSDT",
        interval="4h", entry_ts_ms=0, sl_pct=2.0, tp_pct=4.0, notional=500.0,
        max_candles=3,
    )
    assert "timeout" in result["exit_reason"]
    assert result["bars_held"] == 3


# ─── _simulate_trade — no kline data ──────────────────────────────────────────

def test_simulate_trade_no_data(monkeypatch):
    monkeypatch.setattr(pse, "_binance_klines", lambda *a, **kw: [])
    result = pse._simulate_trade(
        entry_price=2000.0, side="long", symbol="ETHUSDT",
        interval="4h", entry_ts_ms=0,
    )
    assert result["exit_reason"] == "no_data"
    assert result["pnl_usd"] == 0.0


# ─── _load_signals ─────────────────────────────────────────────────────────────

def test_load_signals_filters_by_cutoff(tmp_path, monkeypatch):
    db = tmp_path / "signal_queue.db"
    now = time.time()
    old_ts = now - 40 * 86400   # 40 days ago — outside 30d window
    new_ts = now - 5 * 86400    # 5 days ago — inside window

    _make_db(db, [
        ({"strategy": "OldStrat", "action": "buy"}, "completed", old_ts),
        ({"strategy": "NewStrat", "action": "buy"}, "completed", new_ts),
    ])
    monkeypatch.setattr(pse, "SIGNAL_DB", db)

    signals = pse._load_signals(days=30)
    strats = [s["strategy"] for s in signals]
    assert "NewStrat" in strats
    assert "OldStrat" not in strats


def test_load_signals_missing_db(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(pse, "SIGNAL_DB", tmp_path / "nonexistent.db")
    with caplog.at_level("ERROR"):
        signals = pse._load_signals(days=30)
    assert signals == []


# ─── _load_paper_only_approvals ────────────────────────────────────────────────

def test_load_paper_only_approvals(tmp_path, monkeypatch):
    manifest = tmp_path / "approved_strategies.json"
    _make_manifest(manifest, [
        {"strategy": "Alpha", "approval_class": "paper_only"},
        {"strategy": "Beta",  "approval_class": "candidate_for_tiny_capital"},
    ])
    monkeypatch.setattr(pse, "MANIFEST_PATH", manifest)

    approvals = pse._load_paper_only_approvals()
    assert len(approvals) == 1
    assert approvals[0]["strategy"] == "Alpha"


def test_load_paper_only_approvals_bad_manifest(tmp_path, monkeypatch, caplog):
    bad_manifest = tmp_path / "bad.json"
    bad_manifest.write_text("not json")
    monkeypatch.setattr(pse, "MANIFEST_PATH", bad_manifest)

    with caplog.at_level("ERROR"):
        approvals = pse._load_paper_only_approvals()
    assert approvals == []


# ─── auto_promote freeze layers ────────────────────────────────────────────────

def test_auto_promote_env_freeze(monkeypatch):
    """Layer 1: env_var freeze blocks promotion."""
    import scripts.auto_promote as ap
    monkeypatch.setenv("AUTO_PROMOTE_FREEZE", "true")
    frozen, reason = ap._is_frozen()
    assert frozen is True
    assert "env_vars" in reason


def test_auto_promote_manifest_freeze(tmp_path, monkeypatch):
    """Layer 3: manifest-level flag blocks promotion when env_var + sentinel are clear."""
    import scripts.auto_promote as ap
    monkeypatch.setenv("AUTO_PROMOTE_FREEZE", "false")

    # Place manifest in tmp_path so sentinel file lookup also lands in tmp_path (no sentinel)
    manifest = tmp_path / "approved_strategies.json"
    manifest.write_text(json.dumps({
        "version": 29,
        "governance": {"auto_promote_frozen": True, "freeze_reason": "test freeze"},
        "approvals": [],
    }))
    monkeypatch.setattr(ap, "MANIFEST_PATH", manifest)

    frozen, reason = ap._is_frozen()
    assert frozen is True
    assert "test freeze" in reason


def test_auto_promote_not_frozen(tmp_path, monkeypatch):
    """All layers clear → not frozen."""
    import scripts.auto_promote as ap
    monkeypatch.setenv("AUTO_PROMOTE_FREEZE", "false")

    manifest = tmp_path / "approved_strategies.json"
    manifest.write_text(json.dumps({
        "version": 29,
        "governance": {"auto_promote_frozen": False},
        "approvals": [],
    }))
    monkeypatch.setattr(ap, "MANIFEST_PATH", manifest)

    frozen, _ = ap._is_frozen()
    assert frozen is False
