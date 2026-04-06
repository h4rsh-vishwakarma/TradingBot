from __future__ import annotations

import json

from scripts.verify_tv_inventory import build_inventory_report


def test_build_inventory_report_matches_generated_webhook_script(tmp_path):
    manifest_path = tmp_path / "approved.json"
    strategies_dir = tmp_path / "strategies"
    generated_dir = tmp_path / "generated"
    strategies_dir.mkdir()
    generated_dir.mkdir()

    manifest_path.write_text(
        json.dumps(
            {
                "approvals": [
                    {
                        "strategy": "Aggressive Entry",
                        "exchange": "binance",
                        "symbols": ["SUIUSDT"],
                        "timeframes": ["4h"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    pine = generated_dir / "SUIUSDT_Aggressive_Entry_4h_alpha_webhook.pine"
    pine.write_text(
        '// demo\nalertcondition(longCond, "Webhook BUY", \'{"secret":"x"}\')\n'
        'alertcondition(shortCond, "Webhook SELL", \'{"secret":"x"}\')\n',
        encoding="utf-8",
    )

    report = build_inventory_report(manifest_path, strategies_dir, generated_dir)
    assert len(report) == 1
    row = report.iloc[0]
    assert row["Status"] == "READY"
    assert row["Webhook BUY"] == "YES"
    assert row["Webhook SELL"] == "YES"
