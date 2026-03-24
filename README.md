# TradingView Webhook Trading Bot

**Automated Multi-Strategy Crypto Trading Platform**
**Server:** `ubuntu@15.207.152.119` (AWS ap-south-1)
**Status:** Operational (March 2026)

---

## Overview

Production-grade automated trading system that receives TradingView webhook alerts, validates them through a multi-layer safety pipeline, and executes trades on Binance Futures. Features a daily grid-search tournament that auto-discovers the best-performing strategies and deploys them.

**Core Loop:**
1. TradingView Pine Script strategies fire webhook alerts on each candle close
2. Webhook server validates, normalizes, and queues signals
3. Orchestrator checks leaderboard tier, deduplicates, applies safety gates
4. Binance Futures order executes with quantity caps and position tracking
5. Telegram alerts + Google Sheets logging for full observability

---

## Architecture

```
TradingView Alerts (11 Pine Scripts)
          |
          v  HTTP POST (JSON / Plain Text)
+---------+----------+
|  Nginx (port 443)  |
|  rate-limit + SSL  |
+---------+----------+
          |
          v  proxy_pass :5000
+---------+----------+
|  Gunicorn (4w/4t)  |    trading_webhook.service
|  webhook_server.py |
+---------+----------+
          |
          v  signals.jsonl (append-only queue)
+---------+----------+
|   Orchestrator     |    trading_orchestrator.service
|   orchestrator.py  |
|                    |
|  1. Idempotency    |  - deduplicate by signal_id
|  2. Tier Check     |  - must be ALPHA in tournament_winners.csv
|  3. Signal Dedup   |  - same strategy+symbol+side within 120s
|  4. Symbol Cooldown|  - 300s between trades per symbol
|  5. Candle Lock    |  - first signal wins per hourly candle
|  6. Safety Gate    |  - daily loss limit, position conflict
|  7. Qty Cap        |  - SOL:1, ETH:0.05, BTC:0.003
+---------+----------+
          |
          v
+---------+----------+
|  Binance Futures   |    Testnet (ALLOW_REAL_TRADES=true)
|  binance_client.py |    Mainnet price authority
+---------+----------+
          |
          v
+----+----+----+-----+
|Telegram |Sheets|Ledger|
| alerts  | log  |state |
+---------+------+------+
```

---

## Active Strategies (Top 11 from Tournament)

| Rank | Strategy | Symbol | Daily ROI | Gross DD | Net DD | Tier |
|------|----------|--------|-----------|----------|--------|------|
| 1 | OPTIMIZED_SOLUSDT (Bollinger) | SOLUSDT | 2.61% | -65.22% | -96.76% | ALPHA++ |
| 2 | Reversed BarUpDn Strategy | SOLUSDT | 2.55% | -65.64% | -98.0% | ALPHA++ |
| 3 | SMC Strategy [LuxAlgo] | SOLUSDT | 2.16% | -59.6% | -82.61% | ALPHA++ |
| 4 | Reverse Liquidity Trap | SOLUSDT | 2.13% | -61.47% | -78.71% | ALPHA++ |
| 5 | MVO Momentum Variance | SOLUSDT | 1.72% | -58.82% | -79.06% | ALPHA++ |
| 6 | Institutional Flow Hybrid | SOLUSDT | 1.62% | -65.28% | -82.6% | ALPHA++ |
| 7 | OBV + WaveTrend Volume Scalper | SOLUSDT | 1.56% | -63.61% | -89.91% | ALPHA++ |
| 8 | ML Lorentzian Classification | SOLUSDT | 1.33% | -25.96% | -28.29% | ALPHA |
| 9 | Reversed BarUpDn Strategy | ETHUSDT | 1.27% | -51.78% | -57.65% | ALPHA |
| 10 | OPTIMIZED_SOLUSDT (Bollinger) | ETHUSDT | 1.25% | -47.33% | -60.36% | ALPHA |
| 11 | Mean Reversion Scalper Hybrid | SOLUSDT | 1.22% | -22.23% | -24.16% | ALPHA |

Rankings update daily at 00:15 UTC via `strategy_tournament.py`.

---

## Services

| Service | Port | Description | Command |
|---------|------|-------------|---------|
| `trading_webhook` | 5000 | Gunicorn webhook receiver (4 workers, gthread) | `sudo systemctl status trading_webhook` |
| `trading_orchestrator` | - | Signal consumer + trade executor | `sudo systemctl status trading_orchestrator` |
| `hl_mirror` | - | Hyperliquid lead trader mirror (optional) | `sudo systemctl status hl_mirror` |
| `telegram_bot` | - | Telegram backtest bot (separate project) | `sudo systemctl status telegram_bot` |

**Cron Jobs:**

| Schedule | Script | Purpose |
|----------|--------|---------|
| `0 0 * * *` | `fetch_historical_data.py` | Download 3-year OHLCV for BTC/ETH/SOL |
| `0 0:15 * * *` | `strategy_tournament.py` | Grid-search optimization, output winners CSV |
| `0 9 * * *` | `script_vault.py` | Deploy top strategies to Telegram |
| `0 * * * *` | `auto_injector.py` | Hourly heartbeat health check |

---

## Project Structure

```
tradingview_webhook_bot/
|-- wsgi.py                          # Gunicorn entry point
|-- config/
|   |-- settings.json                # Symbols, risk params, webhook config
|   |-- strategy_config.json         # Dynamic mode, min tier, emergency stop
|-- tradingview_webhook_bot/         # Main Python package
|   |-- core/
|   |   |-- orchestrator.py          # Signal pipeline + trade execution
|   |   |-- webhook_server.py        # Flask webhook receiver
|   |   |-- signal_processor.py      # Signal normalization
|   |   |-- risk_manager.py          # Position limits, exposure
|   |   |-- circuit_breaker.py       # Daily loss limit enforcement
|   |   |-- schemas.py               # Pydantic signal models
|   |   |-- script_vault.py          # Pine Script generator + Telegram dispatch
|   |-- exchange/
|   |   |-- binance_client.py        # Binance Futures order execution
|   |   |-- price_provider.py        # Live price resolution
|   |   |-- hl_client.py             # Hyperliquid client (optional)
|   |   |-- hl_mirror.py             # Lead trader mirror (optional)
|   |-- ledger/
|   |   |-- positions.py             # Position state + PnL tracking
|   |-- storage/
|   |   |-- jsonl_queue.py           # Append-only signal queue
|   |   |-- jsonl_consumer.py        # Offset-based queue consumer
|   |   |-- idempotency_store.py     # SQLite dedup store
|   |   |-- sheets_logger.py         # Google Sheets trade logger
|   |-- alerts/
|   |   |-- telegram_alerts.py       # Telegram notifications
|   |   |-- email_notifier.py        # Email alerts (optional)
|   |-- utils/
|       |-- health_checker.py        # Component health + Prometheus metrics
|       |-- signal_archiver.py       # Log rotation for signal files
|-- backtesting/
|   |-- engine.py                    # Backtest confidence scoring
|   |-- A_Leaderboard/               # Ingested TV backtest CSVs
|   |-- pine/                        # 40+ Pine Script strategy folders
|-- scripts/
|   |-- strategy_tournament.py       # Daily grid-search optimizer
|   |-- fetch_historical_data.py     # Binance OHLCV downloader
|   |-- auto_injector.py             # Hourly heartbeat scanner
|   |-- kill_switch.py               # Emergency stop all trading
|   |-- emergency_stop.sh            # Shell-level kill switch
|-- storage/
|   |-- backtest_data/               # 3-year 15m candles (BTC/ETH/SOL)
|   |-- reports/tournament_winners.csv
|-- strategies/                      # Reference Pine scripts
|-- deploy/
|   |-- nginx/                       # Nginx proxy configs
|   |-- systemd/                     # Service unit files
|   |-- deploy.sh                    # Automated deployment
```

---

## Setup

### Prerequisites

- Ubuntu 22.04 LTS (AWS EC2)
- Python 3.10+
- Binance Futures API keys
- Telegram Bot Token
- Google Service Account (for Sheets logging)

### Installation

```bash
# Clone
cd /home/ubuntu
git clone <repo_url> tradingview_webhook_bot
cd tradingview_webhook_bot

# Virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r tradingview_webhook_bot/requirements.txt

# Environment config
sudo mkdir -p /etc/tradingbot
sudo cp .env.example /etc/tradingbot/env_vars
sudo nano /etc/tradingbot/env_vars  # Fill in API keys
```

### Configuration

**`/etc/tradingbot/env_vars`** (required):
```bash
# Core
WEBHOOK_SECRET=your_secret_here
PORT=5000
RUN_MODE=production
ALLOW_REAL_TRADES=true

# Binance
BINANCE_API_KEY=your_key
BINANCE_API_SECRET=your_secret
BINANCE_TESTNET=true

# Telegram
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id

# Risk
MAX_NOTIONAL_PER_TRADE=500.0
DAILY_LOSS_LIMIT=-50.0
```

### Deploy Services

```bash
# Copy service files
sudo cp deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload

# Start services
sudo systemctl enable --now trading_webhook
sudo systemctl enable --now trading_orchestrator

# Setup cron
crontab -e  # Add entries from setup_cron.sh

# Verify
curl http://127.0.0.1:5000/health
sudo journalctl -u trading_orchestrator -f
```

---

## Signal Flow (Webhook JSON Format)

TradingView sends this JSON on each alert:

```json
{
  "secret": "squeeze_tradingview_cluster_2026_secure",
  "strategy": "Machine_Learning_Lorentzian_Classification",
  "side": "BUY",
  "symbol": "SOLUSDT",
  "timeframe": "1h",
  "price": 90.28,
  "quantity": 0.003,
  "exchange": "binance"
}
```

The system also handles TradingView plain-text alerts and auto-extracts fields.

---

## Safety Pipeline

Signals pass through 7 layers before execution:

1. **Idempotency** - SQLite store prevents duplicate signal_id processing
2. **Leaderboard Tier** - Strategy must be ALPHA or ALPHA++ in daily tournament
3. **Signal Dedup** - Same strategy+symbol+side blocked within 120s window
4. **Symbol Cooldown** - 300s minimum between trades on same symbol
5. **Candle Lock** - First signal per hourly candle wins; opposite direction blocked
6. **Safety Gate** - Daily PnL limit (-$50), no duplicate positions
7. **Quantity Cap** - Hard limits: SOL 1.0, ETH 0.05, BTC 0.003

---

## Monitoring

**Telegram Alerts:**
- Trade executions (BUY/SELL with price and PnL)
- Safety gate blocks (position conflicts, loss limits)
- Hourly heartbeat (service health, webhook status)

**Google Sheets:**
- Live trade log with signal_id, strategy, PnL
- Blocked trade log with rejection reason

**Logs:**
```bash
# Webhook server logs
sudo journalctl -u trading_webhook -f

# Orchestrator logs
sudo journalctl -u trading_orchestrator -f

# Heartbeat scan
tail -f /home/ubuntu/tradingview_webhook_bot/auto_scan.log
```

**Health Check:**
```bash
curl http://127.0.0.1:5000/health
# {"service":"trading_webhook","status":"ok","timestamp":"..."}
```

---

## Operations

### Restart Services
```bash
sudo systemctl restart trading_webhook trading_orchestrator
```

### Emergency Stop
```bash
bash scripts/emergency_stop.sh
# or
python3 scripts/kill_switch.py
```

### Check Positions
```bash
cat tradingview_webhook_bot/storage/ledger_state.json | python3 -m json.tool
```

### View Trade History
```bash
# Last 10 trades from ledger
python3 -c "
import json
with open('tradingview_webhook_bot/storage/ledger_state.json') as f:
    data = json.load(f)
for t in data.get('trade_history', [])[-10:]:
    print(f\"{t['timestamp'][:19]}  {t['symbol']:20s}  PnL: \${t['pnl']:>8.2f}\")
"
```

### Force Tournament Rerun
```bash
cd /home/ubuntu/tradingview_webhook_bot
venv/bin/python3 scripts/strategy_tournament.py
```

---

## Recent Changes

### March 23-24, 2026
- Fixed flip-flop trading (multiple strategies contradicting on same candle)
- Added candle lock system (first signal wins per hourly candle)
- Added symbol cooldown (300s between trades per symbol)
- Capped max quantity per symbol (prevents oversized positions)
- Fixed strategy name matching (`_normalize()` strips all special chars)
- Fixed heartbeat alert checking wrong process name
- Cleaned stale ledger entries and freed disk space (91% -> 80%)

### March 21, 2026
- Deployed Alpha Engine v10.0 with 11 strategies
- ADX > 25 filter + 4% trailing stop on all strategies
- Grid-search tournament with 7-combo parameter optimization

---

## License

Proprietary and confidential. All rights reserved.
