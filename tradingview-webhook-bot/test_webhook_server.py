import os
import pytest
from tradingview_webhook_bot.tradingview_webhook_server import create_app

@pytest.fixture
def client(tmp_path):
    # Create a temp queue path for testing
    queue_file = tmp_path / "test_signals.jsonl"
    
    # Pass config directly to the app
    app = create_app({
        "WEBHOOK_SECRET": "test_key",
        "QUEUE_PATH": str(queue_file)
    })
    
    app.queue_file = queue_file # Attach for easy access in tests
    with app.test_client() as client:
        yield client

def test_webhook_unauthorized(client):
    response = client.post('/webhook/tradingview', json={"test": "data"})
    assert response.status_code == 401

def test_webhook_success(client):
    headers = {"X-Webhook-Secret": "test_key"}
    payload = {"symbol": "BTCUSDT", "action": "buy"}
    
    response = client.post('/webhook/tradingview', json=payload, headers=headers)
    
    assert response.status_code == 202
    # Verify the file was actually written to the temp path
    assert os.path.exists(client.application.config["QUEUE_PATH"])
