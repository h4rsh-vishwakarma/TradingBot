# 🤖 Pro-Grade Binance Futures Trading Bot

A robust, fault-tolerant automated trading engine built with **Python**, **Flask**, and **Streamlit**. This system is designed for high reliability, ensuring exactly-once order execution and real-time state monitoring.

---

## 🚀 Key Technical Features

### 1. Exactly-Once Execution (Idempotency)
To prevent duplicate trades during network retries or multiple signal triggers, the bot employs a dual-layer idempotency strategy:
* **Local Tier**: A SQLite-based `IdempotencyStore` tracks `signal_id`s to skip duplicates before they reach the execution logic.
* **Exchange Tier**: Generates **Deterministic Client Order IDs** (`{signal_id}:{venue}:{leg}:{attempt}`) passed directly to Binance. If a retry occurs, Binance recognizes the ID and prevents a second order from opening.

### 2. Atomic Data Integrity
The system uses **Atomic JSONL Queueing** with exclusive file locking (`portalocker`). This ensures that even if multiple Webhook signals arrive at the exact same millisecond, the data is written safely without corruption or data loss.

### 3. Automated State Reconciliation
A background **Reconciler** monitor audits the exchange state every 15 seconds. It compares active positions on Binance against local expectations, triggering alerts if "drift" (unexpected positions) is detected.

### 4. Full Audit Trail (Event Logging)
Every trade follows a strict event chain recorded in a central `event_logs.jsonl`:
`signal_received` ➔ `order_submitted` ➔ `order_ack` ➔ `position_snapshot`.

### 5. Operational Alerts
Integrated **Telegram Alerts Router** with:
* **Local Fallback**: All alerts are saved locally if the network fails.
* **Rate Limiting**: Prevents notification spam by limiting duplicate alerts within a 60-second window.

---

## 🛠️ Tech Stack
* **Backend**: Python 3.x, Flask (Webhook Server)
* **Infrastructure**: SQLite3, JSONL (Atomic Queue)
* **UI/Ops**: Streamlit (Live Dashboard), Telegram API
* **Trading**: Binance Futures API (`python-binance`)

---

## 📂 Project Structure
```text
├── alerts/             # Telegram router & alert logic
├── bot/                # Binance client & order execution
├── core/               
│   ├── signal_processor.py # Main execution engine
│   ├── reconciler.py       # 15s state auditor
│   └── webhook_server.py   # Atomic signal receiver
├── storage/            # JSONL logs & Idempotency DB (Local only)
├── ui.py               # Streamlit monitoring dashboard
└── .env                # API Keys (Protected via .gitignore)
```
---
🔧 Setup & Installation
Clone the repo:

Bash
git clone [https://github.com/h4rsh-vishwakarma/TradingBot.git](https://github.com/h4rsh-vishwakarma/TradingBot.git)
cd TradingBot
Install Dependencies:

Bash
pip install -r requirements.txt
Configure Environment:
Create a .env file and add:

Code snippet
BINANCE_API_KEY=your_key
BINANCE_API_SECRET=your_secret
TELEGRAM_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
Launch the System:
Run the master startup script or launch components individually:

PowerShell
python -m core.webhook_server    # Terminal 1
python -m core.signal_processor  # Terminal 2
python -m core.reconciler        # Terminal 3
streamlit run ui.py              # Terminal 4
📘 Operational Runbook
Trade Failure: Check storage/event_logs.jsonl for the specific trade_fail event data.

Position Drift: If the Reconciler alerts an unknown position, verify against the Binance Testnet dashboard immediately.

Webhook Issues: Ensure the public URL (Ngrok) matches the TradingView Alert URL.

---
---

### 💡 Why this README works:
* **Keywords**: It uses terms like "Idempotency," "Atomic," and "Reconciliation"—these are high-level engineering concepts that prove you aren't just a beginner.
* **Structure**: It clearly explains *how* the bot works, not just *what* it does.
* **Visuals**: It uses a clean folder tree and formatted code blocks .

**Would you like me to also generate the `requirements.txt` content so you can finalize y


