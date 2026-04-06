from __future__ import annotations

import pandas as pd

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

