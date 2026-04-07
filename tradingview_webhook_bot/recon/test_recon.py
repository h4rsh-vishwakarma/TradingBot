from tradingview_webhook_bot.ledger.positions import PositionLedger
from tradingview_webhook_bot.recon.reconciler import Reconciler


def test_drift_detection():
    recon = Reconciler(tolerance=0.01)

    report = recon.detect_qty_drift(1.0, 1.005)
    assert report["is_synced"] is True

    report = recon.detect_qty_drift(1.0, 1.5)
    assert report["is_synced"] is False
    assert report["severity"] == "HIGH"
    assert report["drift_type"] == "POSITION_MISMATCH"


def test_incident_formatting():
    recon = Reconciler()
    report = recon.detect_qty_drift(1.0, 2.0)
    incident_msg = recon.format_incident("BTCUSDT", report)
    assert "DRIFT FIXED" in incident_msg
    assert "BTCUSDT" in incident_msg
    assert "POSITION_MISMATCH" in incident_msg


def test_detect_qty_drift_unexpected_flat():
    recon = Reconciler(tolerance=0.01)
    report = recon.detect_qty_drift(0.75, 0.0)
    assert report["drift_type"] == "UNEXPECTED_FLAT"
    assert report["severity"] == "HIGH"


def test_detect_qty_drift_side_mismatch():
    recon = Reconciler(tolerance=0.01)
    report = recon.detect_qty_drift(1.0, -1.0)
    assert report["drift_type"] == "SIDE_MISMATCH"
    assert report["severity"] == "CRITICAL"


def test_reconcile_clears_strategy_children(tmp_path):
    ledger = PositionLedger(str(tmp_path / "ledger.json"))
    ledger.update_position_manually("binance:SUIUSDT", -674.5, avg_price=0.86)
    ledger.update_position_manually("binance:SUIUSDT:cci trend", -278.2, avg_price=0.88)

    recon = Reconciler(ledger=ledger)
    alerts = recon.reconcile_with_exchange({
        "binance:SUIUSDT": {"quantity": -674.5, "entry_price": 0.8646}
    })

    assert alerts
    assert ledger.get_position("binance:SUIUSDT").quantity == -674.5
    assert ledger.get_position("binance:SUIUSDT").avg_price == 0.8646
    assert ledger.get_position("binance:SUIUSDT:cci trend").quantity == 0.0
