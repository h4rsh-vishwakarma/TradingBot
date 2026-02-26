# 📖 Trading Bot Operational Runbook

**System Name:** Multi-Strategy Crypto Trading Bot
**Primary Maintainer:** Harsh
**Version:** 2.6.0

---

## 🛠 1. Service Management
The bot runs as two independent systemd services for modularity and crash-protection.

### Webhook Server (Receiver)
Handles incoming TradingView signals and validates them via Pydantic.
* **Restart**: `sudo systemctl restart tv-webhook`
* **Stop**: `sudo systemctl stop tv-webhook`
* **Status**: `sudo systemctl status tv-webhook`

### Trading Engine (Consumer)
Processes the queue, manages risk, and executes trades on Binance.
* **Restart**: `sudo systemctl restart tv-engine`
* **Stop**: `sudo systemctl stop tv-engine`
* **Status**: `sudo systemctl status tv-engine`

---

## 🔍 2. Monitoring & Logs
Use these commands to check the real-time health of the bot.

* **View Live Signal Traffic**: `sudo journalctl -u tv-webhook -f`
* **View Live Trading Logs**: `sudo journalctl -u tv-engine -f`
* **Check Performance/PnL**: Send `/status` to the Telegram Bot.

---

## 📂 3. Critical Data Locations
* **Signal Queue**: `storage/signals.jsonl` (All incoming signals).
* **Position Ledger**: `storage/ledger_state.json` (Active positions and realized PnL).
* **Duplicate Prevention**: `storage/idempotency.db` (SQLite database for preventing double trades).
* **Secrets**: `.env` file in the root directory.

---

## 🚨 4. Emergency Procedures

### Immediate Shutdown
If the market is volatile or the bot is behaving unexpectedly:
1.  **Telegram**: Send the `/stop` command to the bot.
2.  **CLI**: Run `sudo systemctl stop tv-engine`.

### Handling Reconciliation Drift
If you receive a **"🚨 RECONCILIATION ALERT"** on Telegram:
1.  Check the difference between the local Ledger and Binance.
2.  The bot will log the exact drift in `storage/recon_incidents.jsonl`.
3.  Manually close the extra position on Binance if necessary to align with the Ledger.

### Queue Corruption
If the bot crashes due to malformed data:
1.  The system automatically moves bad signals to `dlq.jsonl` (Dead Letter Queue).
2.  Inspect `dlq.jsonl` to see which TradingView alert was malformed.

---

## 🧪 5. Verification & Testing
Before resuming trading after an update, always run the math audit:
```bash
source venv/bin/activate
export PYTHONPATH=$PYTHONPATH:.
python3 test_ledger.py

Verify that the output says: "✅ TEST PASSED: Ledger math is correct!".

##🔐 6. Security Maintenance
Rotate Secrets: Change the WEBHOOK_SECRET in .env every 90 days.

Update IP: If the server IP changes, update the Webhook URL in all TradingView Alerts.


## 7. Trading Modes & Safety Gate
Bot mein ek built-in safety mechanism hai jo accidental real trades ko rokta hai. Isse .env file ke zariye control kiya jata hai.

A. Operational ModesModeALLOW_REAL_TRADESRUN_MODEDescriptionDevelopmentfalsedevelopmentSirf logs aur ledger update honge. No real trades.StagingfalseproductionProduction environment mein test run (Dry Run).Live TradingtrueproductionREAL MONEY ACTIVE. Bot Binance/Exchange par orders bhejega.


B. How to Enable Real Trading
Agar aapko ledger trading se real trading par switch karna hai:

Stop the Engine:

Bash
sudo systemctl stop tv-engine
Update .env Configuration:
nano .env

Plaintext
ALLOW_REAL_TRADES=true
RUN_MODE=production
Verify Secrets: Ensure BINANCE_API_KEY aur BINANCE_SECRET sahi hain.

Restart & Monitor:

Bash
sudo systemctl start tv-engine
# Monitor logs for the 'REAL TRADES ACTIVE' flag
sudo journalctl -u tv-engine -f
7. Reconciliation & Maintenance
Bot har /status request par internal ledger aur exchange balance ko match karta hai.

Manual Recon: Telegram par /status command bhejein.

Drift Alert: Agar ⚠️ Drift Alert aata hai, toh iska matlab hai manual intervention zaroori hai (Internal ledger aur real balance mismatch hai).

Log Rotation: Alerts aur signals storage/*.jsonl mein save hote hain. Mahine mein ek baar purane logs ko archive karne ki salah di jati hai.
