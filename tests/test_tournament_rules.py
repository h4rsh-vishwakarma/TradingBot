import pandas as pd

from tradingview_webhook_bot.tournament_rules import (
    apply_tournament_rules,
    build_tournament_change_message,
    classify_tournament_entry,
    filter_auto_trade_eligible,
)


def test_classify_auto_trade_eligible_strategy():
    result = classify_tournament_entry(
        daily_roi=0.75,
        gross_dd=-18.0,
        net_dd=-22.0,
        win_rate=48.0,
        sharpe=3.2,
    )

    assert result.auto_trade_eligible is True
    assert "ALPHA" in result.tier


def test_classify_ineligible_strategy_due_to_low_roi():
    result = classify_tournament_entry(
        daily_roi=0.30,
        gross_dd=-10.0,
        net_dd=-12.0,
        win_rate=52.0,
        sharpe=3.1,
    )

    assert result.auto_trade_eligible is False
    assert result.tier == "⚖️ AVERAGE"
    assert "below minimum" in result.auto_trade_reason


def test_classify_ineligible_strategy_due_to_high_ndd():
    result = classify_tournament_entry(
        daily_roi=0.90,
        gross_dd=-20.0,
        net_dd=-35.0,
        win_rate=55.0,
        sharpe=4.0,
    )

    assert result.auto_trade_eligible is False
    assert result.tier == "⚖️ AVERAGE"
    assert "Net DD" in result.auto_trade_reason


def test_apply_rules_and_filter_auto_trade_eligible():
    df = pd.DataFrame(
        [
            {"Symbol": "BTCUSDT", "Strategy": "A", "Daily_ROI_%": 0.7, "Gross_DD_%": -18, "Net_DD_%": -20},
            {"Symbol": "ETHUSDT", "Strategy": "B", "Daily_ROI_%": 0.2, "Gross_DD_%": -10, "Net_DD_%": -12},
            {"Symbol": "SOLUSDT", "Strategy": "C", "Daily_ROI_%": 0.9, "Gross_DD_%": -22, "Net_DD_%": -36},
        ]
    )

    ranked = apply_tournament_rules(df)
    eligible = filter_auto_trade_eligible(ranked)

    assert list(eligible["Strategy"]) == ["A"]
    assert ranked.loc[ranked["Strategy"] == "A", "Auto_Trade_Eligible"].iloc[0] == "YES"
    assert ranked.loc[ranked["Strategy"] == "B", "Tier"].iloc[0] == "⚖️ AVERAGE"
    assert ranked.loc[ranked["Strategy"] == "C", "Tier"].iloc[0] == "⚖️ AVERAGE"


def test_build_change_message_for_tournament_updates():
    previous_df = pd.DataFrame(
        [
            {"Symbol": "BTCUSDT", "Strategy": "A", "Daily_ROI_%": 0.4, "Gross_DD_%": -18, "Net_DD_%": -20},
            {"Symbol": "ETHUSDT", "Strategy": "B", "Daily_ROI_%": 0.8, "Gross_DD_%": -12, "Net_DD_%": -18},
        ]
    )
    current_df = pd.DataFrame(
        [
            {"Symbol": "BTCUSDT", "Strategy": "A", "Daily_ROI_%": 0.6, "Gross_DD_%": -18, "Net_DD_%": -20},
            {"Symbol": "XRPUSDT", "Strategy": "C", "Daily_ROI_%": 0.9, "Gross_DD_%": -14, "Net_DD_%": -16},
        ]
    )

    message = build_tournament_change_message(previous_df, current_df, "Rule Update")

    assert message is not None
    assert "Rule Update" in message
    assert "BTCUSDT" in message
    assert "XRPUSDT" in message
