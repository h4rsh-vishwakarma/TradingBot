from __future__ import annotations

from pathlib import Path

import pandas as pd

from tradingview_webhook_bot.alpha_engine import AlphaCriteria, build_alpha_reports, generate_alpha_pine_scripts


def test_build_alpha_reports_qualifies_strategy(tmp_path):
    input_dir = tmp_path / "backtest_results"
    report_dir = tmp_path / "reports"
    input_dir.mkdir()
    report_dir.mkdir()

    frame = pd.DataFrame(
        [
            {"Trade #": 1, "Type": "Open Long", "Date and time": "2026-01-01 00:00:00", "Net P&L USDT": 0, "Net P&L %": 0},
            {"Trade #": 1, "Type": "Close Long", "Date and time": "2026-01-05 00:00:00", "Net P&L USDT": 2200, "Net P&L %": 22},
            {"Trade #": 2, "Type": "Open Long", "Date and time": "2026-01-06 00:00:00", "Net P&L USDT": 0, "Net P&L %": 0},
            {"Trade #": 2, "Type": "Close Long", "Date and time": "2026-01-09 00:00:00", "Net P&L USDT": -150, "Net P&L %": -1.5},
            {"Trade #": 3, "Type": "Open Short", "Date and time": "2026-01-10 00:00:00", "Net P&L USDT": 0, "Net P&L %": 0},
            {"Trade #": 3, "Type": "Close Short", "Date and time": "2026-01-14 00:00:00", "Net P&L USDT": 1800, "Net P&L %": 18},
            {"Trade #": 4, "Type": "Open Long", "Date and time": "2026-01-15 00:00:00", "Net P&L USDT": 0, "Net P&L %": 0},
            {"Trade #": 4, "Type": "Close Long", "Date and time": "2026-01-18 00:00:00", "Net P&L USDT": -50, "Net P&L %": -0.5},
        ]
    )
    frame.to_csv(input_dir / "Aggressive_Entry_4h_BINANCE_SUIUSDT_2026-04-06.csv", index=False)

    reports = build_alpha_reports(
        input_folder=input_dir,
        report_dir=report_dir,
        initial_capital=10_000,
        criteria=AlphaCriteria(min_roi_per_day_pct=1.0, max_gross_drawdown_pct=15.0, max_net_drawdown_pct=15.0),
    )

    assert len(reports["all"]) == 1
    assert len(reports["alpha"]) == 1
    row = reports["alpha"].iloc[0]
    assert row["Symbol"] == "SUIUSDT"
    assert row["Timeframe"] == "4h"
    assert row["Alpha_Qualified"] == "YES"
    assert row["ROI_Per_Day_Pct"] > 1.0
    assert abs(row["Gross_Drawdown_Percent"]) < 15.0
    assert abs(row["Net_Drawdown_Percent"]) < 15.0
    assert (report_dir / "alpha_candidates.csv").exists()
    assert (report_dir / "alpha_best_per_symbol.csv").exists()


def test_generate_alpha_pine_scripts_adds_secretful_alerts(tmp_path):
    strategies_dir = tmp_path / "strategies"
    output_dir = tmp_path / "generated"
    strategies_dir.mkdir()
    output_dir.mkdir()

    pine_source = """//@version=5
strategy("Demo", overlay=true)
longCond = close > open
shortCond = close < open
alertcondition(longCond, "OLD BUY", '{"symbol":"{{ticker}}","action":"buy"}')
alertcondition(shortCond, "OLD SELL", '{"symbol":"{{ticker}}","action":"sell"}')
"""
    source_path = strategies_dir / "SUIUSDT_Aggressive_Entry_4h.pine"
    source_path.write_text(pine_source, encoding="utf-8")

    alpha_candidates = pd.DataFrame(
        [
            {
                "Strategy": "Aggressive Entry's Alpha",
                "Symbol": "SUIUSDT",
                "Timeframe": "4h",
                "ROI_Per_Day_Pct": 1.2345,
                "Gross_Drawdown_Percent": -10.0,
                "Net_Drawdown_Percent": -8.0,
                "SL_Pct": 0.5,
                "TP_Pct": 12.0,
                "Trail_Pct": 0.0,
            }
        ]
    )

    generated = generate_alpha_pine_scripts(
        alpha_candidates=alpha_candidates,
        strategies_dir=strategies_dir,
        output_dir=output_dir,
        webhook_secret="strict_secret_123",
    )

    assert len(generated) == 1
    row = generated.iloc[0]
    assert row["Webhook_Ready"] == "YES"
    generated_path = Path(row["Generated_Pine_Script"])
    assert generated_path.exists()
    text = generated_path.read_text(encoding="utf-8")
    assert 'strict_secret_123' in text
    assert '"is_exit":false' in text
    assert 'Webhook BUY' in text
    assert 'Webhook SELL' in text
    assert 'OLD BUY' not in text
    assert 'OLD SELL' not in text
    assert "Entry\\'s Alpha" in text


def test_build_alpha_reports_writes_headered_empty_best_csv(tmp_path):
    input_dir = tmp_path / "backtest_results"
    report_dir = tmp_path / "reports"
    input_dir.mkdir()
    report_dir.mkdir()

    frame = pd.DataFrame(
        [
            {"Trade #": 1, "Type": "Open Long", "Date and time": "2026-01-01 00:00:00", "Net P&L USDT": 0, "Net P&L %": 0},
            {"Trade #": 1, "Type": "Close Long", "Date and time": "2026-06-01 00:00:00", "Net P&L USDT": 50, "Net P&L %": 0.5},
        ]
    )
    frame.to_csv(input_dir / "Slow_Strategy_4h_BINANCE_BTCUSDT_2026-04-06.csv", index=False)

    reports = build_alpha_reports(
        input_folder=input_dir,
        report_dir=report_dir,
        initial_capital=10_000,
        criteria=AlphaCriteria(min_roi_per_day_pct=1.0, max_gross_drawdown_pct=15.0, max_net_drawdown_pct=15.0),
    )

    assert len(reports["all"]) == 1
    assert reports["alpha"].empty
    best_csv = report_dir / "alpha_best_per_symbol.csv"
    assert best_csv.exists()
    best_df = pd.read_csv(best_csv)
    assert best_df.empty
    assert list(best_df.columns) == list(reports["all"].columns)
