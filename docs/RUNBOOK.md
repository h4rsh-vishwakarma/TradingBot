# 📘 Trading Bot Operational Runbook

### 1. Incident: Trade Execution Failed
* **Symptom**: `trade_fail` event in logs or Telegram alert.
* **Steps**:
    1. Check `bot.log` for Binance API errors (e.g., Insufficient Balance).
    2. Verify API Keys are still active in Binance Dashboard.
    3. Manually check the position on Binance Testnet.

### 2. Incident: Reconciler Mismatch
* **Symptom**: Reconciler logs a position that isn't in the local database.
* **Steps**:
    1. Pause the `signal_processor`.
    2. Close the ghost position manually on Binance if it shouldn't exist.
    3. Restart bot and monitor the next signal.

### 3. Incident: Webhook Down
* **Symptom**: No signals received even when TradingView sends alerts.
* **Steps**:
    1. Check if `webhook_server.py` is running.
    2. Verify Ngrok/Public URL is still active.
    3. Restart Flask server.