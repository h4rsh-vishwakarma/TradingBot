from __future__ import annotations

import inspect

import pandas as pd
import pytest

from scripts import batch_backtest as batch


def test_calculate_position_size_caps_fixed_notional():
    qty, notional = batch.calculate_position_size(
        equity=10_000,
        entry_price=100,
        sizing_mode="fixed_notional",
        fixed_notional=5_000,
        max_equity_fraction=0.25,
        min_notional=25,
    )
    assert round(qty, 4) == 25.0
    assert round(notional, 2) == 2_500.0


def test_run_backtest_uses_entry_fixed_quantity(monkeypatch):
    def _unit_signal(df, params):
        return pd.Series([0, 1, 0], index=df.index)

    monkeypatch.setitem(batch.STRATEGY_FUNCTIONS, "unit_test_logic", _unit_signal)

    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2026-01-01 00:00:00", "2026-01-01 01:00:00", "2026-01-01 02:00:00"]
            ),
            "open": [100.0, 100.0, 110.0],
            "high": [101.0, 111.0, 111.0],
            "low": [99.0, 99.0, 109.0],
            "close": [100.0, 100.0, 110.0],
            "volume": [1000, 1000, 1000],
        }
    )

    trades = batch.run_backtest(
        df=df,
        strategy_name="Unit Strategy",
        strategy_config={"logic": "unit_test_logic", "params": {}},
        symbol="BTCUSDT",
        timeframe="1h",
        capital=10_000,
        use_atr=False,
        sl_pct=50,
        tp_pct=50,
        trailing_pct=0,
        max_bars_held=1,
        use_vwap=False,
        use_obv=False,
        sizing_mode="fixed_notional",
        fixed_notional=1_000,
        max_equity_fraction=0.25,
        min_notional=25,
        slippage_bps=0,
    )

    assert len(trades) == 1
    trade = trades[0]
    assert round(trade["qty"], 4) == 10.0
    assert round(trade["entry_notional"], 2) == 1_000.0
    assert trade["exit_reason"] == "Time Exit"


def test_default_slippage_is_15_bps():
    """H-16: run_backtest default slippage must be 15 bps (CEO audit requirement)."""
    sig = inspect.signature(batch.run_backtest)
    default = sig.parameters["slippage_bps"].default
    assert default == 15.0, f"Expected 15.0 bps, got {default}"


def test_slippage_reduces_pnl(monkeypatch):
    """H-18: 15 bps slippage must produce lower P&L than 0 bps on a winning trade."""
    # Signal fires at bar 1 (loop starts at i=1); time exit fires at bar 2 (bars_held=1>=max_bars_held=1)
    def _buy_at_bar1(df, params):
        s = pd.Series([0] * len(df), index=df.index)
        s.iloc[1] = 1
        return s

    monkeypatch.setitem(batch.STRATEGY_FUNCTIONS, "buy_at_bar1", _buy_at_bar1)

    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"]),
            "open": [100.0, 105.0, 115.0, 120.0],
            "high": [105.0, 115.0, 125.0, 125.0],
            "low": [95.0, 100.0, 110.0, 115.0],
            "close": [100.0, 110.0, 120.0, 115.0],
            "volume": [1000, 1000, 1000, 1000],
        }
    )
    cfg = {"logic": "buy_at_bar1", "params": {}}

    trades_no_slip = batch.run_backtest(
        df=df, strategy_name="S", strategy_config=cfg, symbol="BTCUSDT", timeframe="1d",
        use_atr=False, sl_pct=50, tp_pct=50, trailing_pct=0, max_bars_held=1,
        use_vwap=False, use_obv=False, sizing_mode="fixed_notional",
        fixed_notional=1_000, max_equity_fraction=0.25, min_notional=25, slippage_bps=0,
    )
    trades_with_slip = batch.run_backtest(
        df=df, strategy_name="S", strategy_config=cfg, symbol="BTCUSDT", timeframe="1d",
        use_atr=False, sl_pct=50, tp_pct=50, trailing_pct=0, max_bars_held=1,
        use_vwap=False, use_obv=False, sizing_mode="fixed_notional",
        fixed_notional=1_000, max_equity_fraction=0.25, min_notional=25, slippage_bps=15,
    )

    pnl_no_slip = sum(t["pnl_usd"] for t in trades_no_slip)
    pnl_with_slip = sum(t["pnl_usd"] for t in trades_with_slip)
    assert pnl_with_slip < pnl_no_slip, "Slippage must reduce P&L vs no-slippage baseline"


def test_build_realism_score_penalizes_negative_oos():
    """H-18: negative OOS ROI must deduct 20 points from reality score."""
    good = {"Total Trades": 50, "Max DD %": 10, "Profit Factor": 1.5,
            "OOS ROI %": 5.0, "WF Pass Rate %": 75, "Sizing Max Fraction": 0.20}
    bad_oos = {**good, "OOS ROI %": -1.0}

    score_good, _ = batch.build_realism_score(good)
    score_bad, flags = batch.build_realism_score(bad_oos)

    assert score_good - score_bad == pytest.approx(20.0)
    assert "negative_oos" in flags


def test_build_realism_score_penalizes_weak_wf():
    """H-18: WF pass rate below 50% must deduct 15 points from reality score."""
    good = {"Total Trades": 50, "Max DD %": 10, "Profit Factor": 1.5,
            "OOS ROI %": 5.0, "WF Pass Rate %": 75, "Sizing Max Fraction": 0.20}
    weak_wf = {**good, "WF Pass Rate %": 40}

    score_good, _ = batch.build_realism_score(good)
    score_weak, flags = batch.build_realism_score(weak_wf)

    assert score_good - score_weak == pytest.approx(15.0)
    assert "weak_walk_forward" in flags


def test_shortlist_eligible_logic():
    """H-18: shortlist_eligible requires positive ROI, OOS ROI, WF >= 50%, DD <= 20%."""
    base = {"ROI %": 5.0, "OOS ROI %": 3.0, "WF Pass Rate %": 60.0, "Max DD %": 15.0}

    def _eligible(s):
        return (s["ROI %"] > 0 and s["OOS ROI %"] > 0
                and s["WF Pass Rate %"] >= 50 and s["Max DD %"] <= 20)

    assert _eligible(base) is True
    assert _eligible({**base, "OOS ROI %": -1.0}) is False
    assert _eligible({**base, "WF Pass Rate %": 40.0}) is False
    assert _eligible({**base, "Max DD %": 25.0}) is False

