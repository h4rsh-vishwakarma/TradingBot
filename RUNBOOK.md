---

# 📘 Trading Bot System Runbook

This document provides the operational procedures for managing, monitoring, and troubleshooting the **Risk-Aware Hybrid Trading Bot**.

---

## 🚀 1. System Architecture & Workflow

The bot operates on a **Decentralized Modular Architecture**:

1. **Ingestion:** `webhook_server.py` receives the signal.
2. **Validation:** `orchestrator.py` checks the signal against `BacktestEngine` and `PositionLedger`.
3. **Execution:** `binance_client.py` executes Market Orders with 4-layer price extraction.
4. **Logging:** `sheets_logger.py` and Telegram alerts provide real-time reporting.

---

## 🛠️ 2. Daily Operations & Commands

### **Monitoring Logs**

To see real-time trade execution and hybrid scoring:

```bash
# Core Orchestrator Logs (Execution & Risk Gates)
journalctl -u trading_orchestrator -f

# Webhook Server Logs (Incoming Traffic)
journalctl -u trading_webhook -f

```

### **Service Management**

```bash
# Restart the entire system after an update
sudo systemctl restart trading_webhook
sudo systemctl restart trading_orchestrator

# Stop all trading immediately
sudo systemctl stop trading_orchestrator

```

### **Emergency Kill Switch**

If the market goes haywire or the bot malfunctions:

```bash
python3 scripts/kill_switch.py

```

*Note: This will close all open positions on Binance and stop the orchestrator.*

---

## 🧠 3. Managing the Hybrid Engine

### **Updating Backtest Data**

The bot uses CSV files in `backtesting/A_Leaderboard/backtest_imports/` to calculate Confidence Scores.

1. Export a "Trade List" CSV from TradingView.
2. Upload it to the folder.
3. **Naming Convention:** Ensure the filename contains the **Strategy Name** and **Symbol** (e.g., `SMC_BTC_Report.csv`).

### **Adjusting Risk Thresholds**

Edit `backtesting/engine.py`:

* `self.min_win_rate`: Default is **0.54**. Increase to **0.60** for more conservative trading.

---

## 📉 4. Ledger & PnL Management

### **Ledger State**

Located at: `tradingview_webhook_bot/storage/ledger_state.json`.

* The bot automatically updates this file after every fill.
* **Manual Reset:** If you want to clear "Today's PnL" manually, delete this file and restart the orchestrator.

### **Reconciliation**

If the bot's ledger differs from your actual Binance balance:

```bash
python3 -m tradingview_webhook_bot.recon.reconciler

```

---

## 🔍 5. Troubleshooting (FAQ)

| Issue | Root Cause | Solution |
| --- | --- | --- |
| **Price is 0.0** | Binance API lag or empty fills | Check `orchestrator.py` logs; ensure Layer-4 ticker fallback is active. |
| **Hybrid Rejected** | Low Backtest WR or bad Live streak | Check if the correct CSV is in `backtest_imports`. |
| **Duplicate Trade** | Idempotency trigger | Check `idempotency.db`; ensure TradingView `signal_id` is unique. |
| **No File Found** | Fuzzy Matcher fail | Ensure filename has the base symbol (e.g., 'btc' or 'eth'). |

---

## 📈 6. Deployment (Final Step)

### **Nginx Reverse Proxy**

To allow TradingView to reach the bot via HTTPS:

1. Ensure Nginx is running: `sudo systemctl status nginx`
2. Check SSL expiry: `sudo certbot certificates`

---

## ✅ 7. Pre-Flight Checklist (Before going Live)

* [ ] `ALLOW_REAL_TRADES` is set to `true` in `.env`.
* [ ] Backtest CSVs are uploaded for all traded pairs.
* [ ] Telegram Bot is active and sending heartbeats.
* [ ] Google Sheets API credentials are valid.

---

