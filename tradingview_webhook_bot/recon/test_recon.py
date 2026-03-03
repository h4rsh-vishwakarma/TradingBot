from tradingview_webhook_bot.recon.reconciler import Reconciler

def test_drift_detection():
    recon = Reconciler(tolerance=0.01)
    
    # 1. Test Synced (Difference within tolerance)
    report = recon.detect_qty_drift(1.0, 1.005)
    assert report["is_synced"] is True
    
    # 2. Test Out of Sync (Large difference)
    report = recon.detect_qty_drift(1.0, 1.5)
    assert report["is_synced"] is False
    assert report["severity"] == "CRITICAL"

def test_incident_formatting():
    recon = Reconciler()
    report = recon.detect_qty_drift(1.0, 2.0)
    incident_msg = recon.format_incident("BTCUSDT", report)
    assert "DRIFT DETECTED" in incident_msg
    assert "BTCUSDT" in incident_msg
