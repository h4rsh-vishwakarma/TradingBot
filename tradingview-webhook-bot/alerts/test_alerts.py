import os
import json
from tradingview_webhook_bot.alerts.router import AlertRouter

def test_alert_routing_to_file(tmp_path):
    log_file = tmp_path / "alerts.jsonl"
    router = AlertRouter(str(log_file))
    
    # Send an alert
    router.send("Test Alert", severity="WARNING")
    
    # Verify file exists and contains the alert
    assert log_file.exists()
    with open(log_file, 'r') as f:
        data = json.loads(f.readline())
        assert data["message"] == "Test Alert"
        assert data["severity"] == "WARNING"
