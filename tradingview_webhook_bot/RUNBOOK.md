# 🛡️ Trading Bot Production Runbook (2026 Edition)

This document contains all operational procedures, maintenance commands, and troubleshooting steps for the Trading Bot Orchestrator.

---

## 🚀 1. Quick Service Management
Use these commands to manage the background services.

| Action | Webhook Server (Port 80) | Orchestrator (Engine) |
| :--- | :--- | :--- |
| **Start** | `sudo systemctl start trading_webhook` | `sudo systemctl start trading_orchestrator` |
| **Stop** | `sudo systemctl stop trading_webhook` | `sudo systemctl stop trading_orchestrator` |
| **Restart** | `sudo systemctl restart trading_webhook` | `sudo systemctl restart trading_orchestrator` |
| **Status** | `systemctl status trading_webhook` | `systemctl status trading_orchestrator` |

---

## 📊 2. Monitoring & Auditing

### **A. Check Real-time Logs**
Follow the logs to see trades happening live:
```bash
# Orchestrator Logs (Trades & Logic)
journalctl -u trading_orchestrator -f -n 50

# Webhook Logs (Incoming Signals)
journalctl -u trading_webhook -f -n 50
B. Inspect Local Ledger (PnL)
To see the bot's internal view of your positions:

```Bash
cat storage/ledger_state.json | jq
# C. Check Idempotency (Duplicate Prevention)
Verify which signals have already been processed:

```Bash
sqlite3 storage/idempotency.db "SELECT * FROM processed_signals ORDER BY processed_at DESC LIMIT 10;"
#🛠️ 3. Common Troubleshooting
Error: 502 Bad Gateway (Nginx)
If the webhook returns 502, Gunicorn is likely down.

Check if the socket/port is active: sudo netstat -tulpn | grep 80

Restart the webhook: sudo systemctl restart trading_webhook

Error: Trade Failed (Binance Notional)
If logs show Order's notional must be no smaller than 100:

Cause: Quantity is too small.

Fix: Increase quantity in TradingView alert so that Price x Qty > $100.

Error: High Queue Lag
If you see 🐢 HIGH QUEUE LAG in logs:

Cause: Orchestrator is processing slower than signals are arriving.

Fix: Check CPU usage with top. Restart the orchestrator to clear memory.

#🔄 4. Maintenance & Manual Sync
Force Reconcile (Binance vs Ledger)
If the bot's position doesn't match your Binance app:

```Bash
# Run the manual reconciliation script
/home/ubuntu/tradingview_webhook_bot/venv/bin/python3 scripts/reconcile_now.py
Clear Signal Queue
If you want to wipe the history and start fresh:

```Bash
sudo systemctl stop trading_orchestrator
rm storage/signals.jsonl storage/signals.offset
touch storage/signals.jsonl
sudo systemctl start trading_orchestrator
#🔒 5. Security Checklist
Rotate Secret: If WEBHOOK_SECRET is leaked, change it in .env and restart both services.

API Keys: Never commit .env to GitHub. It is already in .gitignore.

GitHub Actions: Ensure all CI runs stay "Green". If a test fails, do not deploy that version.

Maintained by: AnythingAi 
Developed by : Harsh Vishwakarma
Last Updated: March 2026


###Folder Structure


### **Final Words of Advice:**
1.  **Retention:** Maine GitHub history delete karne ka tarika bata diya hai, use periodic karte rahein.
2.  **Backup:** Har hafte `storage/` folder ka ek copy apne local machine par le liya karein (Safety first!).
3.  **Telegram:** Bot ko humesha "Pinned" rakhein taaki koi bhi critical failure alert miss na ho.

**Bhai, aapka bot ab ready hai market fadhne ke liye! 🚀 Koi bhi naya feature ya change c
