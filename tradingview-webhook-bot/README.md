# 📡 TradingView Webhook Trading Bot - Technical Documentation

**Project:** Multi-Strategy TradingView Signal Trading Bot (Production Grade)  
**Last Updated:** February 25, 2026  
**Status:** Active Deployment (Branch: `harsh`)  
**Server:** `ubuntu@ip-172-31-11-197`

---

## 📚 Table of Contents
1. [New Production Features](#-new-production-features)
2. [System Architecture](#-system-architecture)
3. [Setup & Deployment](#-setup--deployment)
4. [Signal Validation (Pydantic v2)](#-signal-validation-pydantic-v2)
5. [Deterministic Position Ledger](#-deterministic-position-ledger)
6. [CI/CD & Automation](#-cicd--automation)
7. [File Structure](#-file-structure)
8. [Monitoring & Runbook](#-monitoring--runbook)

---

## 🚀 New Production Features
The system has been hardened with the following enterprise-grade features:

* **Pydantic v2 Schemas**: Strict "Type-Safe" validation for all incoming signals. Malformed data is rejected at the gateway before reaching the engine.
* **Deterministic Ledger**: Advanced accounting using **Weighted Average Entry Price (WAEP)** and **Realized PnL** with JSON persistence.
* **GitHub Actions CI**: Automated testing pipeline that audits Ledger math and Schema integrity on every push to the `harsh` branch.
* **Atomic JSONL Storage**: Crash-safe signal queuing with offset management to ensure no signal is ever lost or double-processed.
* **Interactive Telegram Control**: Real-time status reports (`/status`) and emergency stop (`/stop`) capabilities.

---

## 🏗 System Architecture
The bot operates on a decoupled architecture to ensure maximum uptime and reliability:



* **Webhook Server (Flask/Gunicorn)**: Receives, validates, and enqueues signals.
* **JSONL Queue**: Serves as a persistent buffer between the web and the trading engine.
* **Orchestrator (The Engine)**: Consumes signals, manages risk, executes trades on Binance, and maintains the Ledger.
* **Reconciliation Loop**: Periodically audits the local Ledger against actual Binance positions to detect "drift".

---

## ⚙️ Setup & Deployment

### 1. Installation
```bash
# Navigate to project root
cd /home/ubuntu/Multi-Strategy-Crypto-Trading-Systems
source venv/bin/activate

# Install Production Requirements
pip install pydantic flask gunicorn python-dotenv ccxt

2. Service Management (Systemd)
The bot is managed as two independent background services:

Webhook Server (The Receiver):

Bash
sudo systemctl restart tv-webhook
sudo systemctl status tv-webhook
Trading Engine (The Consumer):

Bash
sudo systemctl restart tv-engine
sudo systemctl status tv-engine
📡 Signal Validation (Pydantic v2)
Every signal must conform to the schemas/models.py contract. If a field like quantity is missing or price is negative, the server rejects the request with a 422 Unprocessable Entity error.

Valid Payload Example:

JSON
{
  "symbol": "BTCUSDT",
  "action": "BUY",
  "quantity": 0.01,
  "price": 60000.0,
  "secret": "your_secure_secret"
}
📊 Deterministic Position Ledger
The Ledger tracks your true trading performance independently of the exchange:

WAEP Calculation: Correctly averages multiple entries into a single position.

Realized PnL: Subtracts trading fees from gross profit to provide net PnL.

State Persistence: State is saved in storage/ledger_state.json. If the bot restarts, it resumes with exactly the same PnL and position data.

Run Math Audit:

Bash
export PYTHONPATH=$PYTHONPATH:.
python3 test_ledger.py
🤖 CI/CD & Automation
We utilize GitHub Actions (.github/workflows/main.yml) to maintain code quality.

Triggers: Active on push to harsh and main branches.

Automated Steps:

Sets up Python 3.12 environment.

Installs all production dependencies.

Ledger Integrity Test: Executes test_ledger.py to ensure math logic hasn't regressed.

📁 File Structure
```
/home/ubuntu/Multi-Strategy-Crypto-Trading-Systems/
├── schemas/
│   └── models.py             # Pydantic validation rules
├── tradingview-webhook-bot/
│   ├── storage/              # Offset & Idempotency logic
│   ├── ledger/
│   │   └── positions.py      # PnL & WAEP Accounting
│   ├── recon/
│   │   └── reconciler.py     # Drift Audit Engine
│   └── tradingview_webhook_server.py
├── .github/workflows/
│   └── main.yml              # GitHub Actions CI config
├── storage/
│   ├── signals.jsonl         # Signal Buffer (Queue)
│   ├── ledger_state.json     # Persisted PnL Data
│   └── idempotency.db        # Duplicate trade protection
└── enhanced_trading_bot_remote.py # Main Bot Orchestrator
```
🛠 Monitoring & Runbook
Log Inspection
Bash
# Monitor Webhook Traffic
sudo journalctl -u tv-webhook -f

# Monitor Trade Executions
sudo journalctl -u tv-engine -f
Emergency Procedures
Stop Engine: Send /stop via Telegram or run sudo systemctl stop tv-engine.

Data Recovery: If the queue becomes corrupted, the bot will automatically move malformed signals to a Dead Letter Queue (dlq.jsonl) to prevent a total crash.

Developed by: Harsh

Version: 2.6.0 (Production Stable)

Environment: Binance Futures Testnet (Mainnet Price Authority)
