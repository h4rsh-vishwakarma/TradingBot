# TradingView Webhook Trading Bot

**Automated Multi-Strategy Crypto Trading Platform**
**Server:** `ubuntu@15.207.152.119` (AWS ap-south-1)
**Status:** Pre-production hardened / Paper validation active (April 2026)

---

## Overview

Production-grade automated trading system that receives TradingView webhook alerts, validates them through a multi-layer safety pipeline, and executes trades on Binance Futures. Features a daily grid-search tournament that auto-discovers the best-performing strategies and deploys them.

The repository also includes a separately runnable AWS analytics pipeline for
public Binance historical klines. It provides checksum-based ingestion, Glue
5.0/PySpark validation and quarantine, partitioned Parquet, Glue Data Catalog,
Athena queries, CloudWatch monitoring, and Terraform infrastructure. Start with
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and
[`docs/RUN_DATA_LAKE.md`](docs/RUN_DATA_LAKE.md).

**Core Loop:**
1. TradingView Pine Script strategies fire webhook alerts on each candle close
2. Webhook server validates, normalizes, and queues signals
3. Orchestrator checks leaderboard tier, deduplicates, applies safety gates
4. Binance Futures order executes with quantity caps and position tracking
5. Telegram alerts + Google Sheets logging for full observability

---

## Architecture

```
TradingView Alerts (7 Approved Strategies)
          |
          v  HTTP POST (JSON / Plain Text)
+---------+----------+
|  Nginx (port 443)  |
|  rate-limit + SSL  |
+---------+----------+
          |
          v  proxy_pass :5000
+---------+----------+
|  Gunicorn (2w/2t)  |    trading_webhook.service
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

| Strategy | Symbol | Timeframe | Daily ROI | Gross DD | Sharpe | OOS ROI | Tier | Manifest |
|----------|--------|-----------|-----------|----------|--------|---------|------|----------|
| CCI Trend | ETHUSDT | 4h | 5.91% | -2.82% | 0.69 | 3.1% | ALPHA | Approved |
| Donchian Trend | ETHUSDT | 4h | 3.26% | -5.77% | 0.41 | 4.65% | ALPHA | Approved |
| 44_PSAR_Volume_Surge | BTCUSDT | 4h | 1.19% | -26.65% | 5.53 | 0.767% | ALPHA | Approved |
| 56_PSAR_Volume_Tight | ETHUSDT, BTCUSDT | 4h | 1.148% | -29.72% | 5.35 | 0.691% | ALPHA | Approved |
| 57_PSAR_Volume_Ultra | ETHUSDT | 4h | 1.19% | -26.65% | 5.53 | 0.767% | ALPHA | Approved |
| L_X | ETHUSDT, BTCUSDT | 4h | - | - | - | - | Pine-only | Approved |
| Long | ETHUSDT, BTCUSDT | 4h | - | - | - | - | Pine-only | Approved |

Tournament runs daily at 00:15 UTC (`strategy_tournament.py`), scanning 85+ strategies across 11 symbols.
Top 3 per symbol dispatched to Telegram at 09:00 UTC (`script_vault.py`).

---

## Services

| Service | Port | Description | Command |
|---------|------|-------------|---------|
| `trading_webhook` | 5000 | Gunicorn webhook receiver (2 workers, 2 threads, gthread) | `sudo systemctl status trading_webhook` |
| `trading_orchestrator` | - | Signal consumer + trade executor | `sudo systemctl status trading_orchestrator` |
| `trading_dashboard` | 8501 | Streamlit health dashboard | `sudo systemctl status trading_dashboard` |
| `hl_mirror` | - | Hyperliquid lead trader mirror (optional) | `sudo systemctl status hl_mirror` |
| `telegram_bot` | - | Telegram backtest bot (separate project) | `sudo systemctl status telegram_bot` |

**Cron Jobs:**

| Schedule (UTC) | Script | Purpose |
|:-:|--------|---------|
| `0 0 * * *` | `fetch_historical_data.py` | Download 3-year OHLCV (7 symbols) |
| `0:15 * * *` | `strategy_tournament.py` | Grid-search tournament (85 strategies x 11 symbols) |
| `0 1 * * *` | `generate_pine_scripts.py` | Auto-generate Pine scripts for ALPHA++ |
| `0 9 * * *` | `script_vault.py` | Dispatch top 3 per symbol to Telegram |
| `0 * * * *` | `auto_injector.py` | Hourly heartbeat health check |
| `*/15 * * * *` | `export_logs.py` | Refresh dashboard audit CSV |
| `2:30 * * *` | `verify_tv_inventory.py` | Inventory verification against manifest |
| `2:30 * * *` | `daily_paper_report.py` | Paper validation daily report |
| `2:35 * * *` | `daily_recon_summary.py` | Reconciler incident summary |
| `2:40 * * *` | `go_live_gate_check.py` | Go-live gate snapshot |
| `23:50 * * *` | `backup_bot.sh` | Backup ledger + queue (7-day retention) |
| `3:00 Sun` | SQLite VACUUM | Reclaim DB space |

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
|   |   |-- analytics_writer.py     # Auto-updates 3 analytics tabs on every trade
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
sudo systemctl enable --now trading_dashboard

# Setup cron
crontab -e  # Add entries from setup_cron.sh

# Verify
curl http://127.0.0.1:5000/health
curl -I http://127.0.0.1:8501
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

1. **Webhook Auth** - Secret validation (strict mode), rejects missing/invalid secrets
2. **Approval Manifest** - Strategy must be in `config/approved_strategies.json` with provenance
3. **Idempotency** - SQLite store prevents duplicate signal_id processing
4. **Signal Dedup** - Same strategy+symbol+side blocked within 120s window
5. **Symbol Cooldown** - 300s minimum between trades on same symbol
6. **Candle Lock** - First signal per hourly candle wins; opposite direction blocked
7. **Auto Exit Detection** - SELL against open LONG auto-detected as exit (and vice versa)
8. **Circuit Breaker** - Daily loss limit, consecutive loss limit, max drawdown
9. **Safety Gate** - Daily PnL limit (-$50), position conflict check
10. **Quantity Cap** - Hard limits per symbol, equity-based sizing optional

---

## Monitoring

**Telegram Alerts:**
- Trade executions (BUY/SELL with price and PnL)
- Safety gate blocks (position conflicts, loss limits)
- Hourly heartbeat (service health, webhook status)

**Google Sheets (6 tabs, auto-updated on every trade):**
- **Trades** - Live trade log with signal_id, strategy, PnL
- **Blocked Trades** - Rejected signals with reason
- **Daily Analytics** - Daily breakdown (trades, wins, losses, PnL, running capital, DD%)
- **Backtest - With Safety** - Actual bot performance with safety gates
- **Backtest - Without Safety** - All signals (shows impact of safety gates)

**Logs:**
```bash
# Webhook server logs
sudo journalctl -u trading_webhook -f

# Orchestrator logs
sudo journalctl -u trading_orchestrator -f

# Dashboard logs
sudo journalctl -u trading_dashboard -f

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
sudo systemctl restart trading_webhook trading_orchestrator trading_dashboard
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

### April 8, 2026 (Current)
- **CRITICAL FIX:** Auto-detect exit trades when SELL opposes open LONG (PnL was stuck at $0)
- **FIX:** Circuit breaker only records win/loss on exit trades (was counting entries as wins)
- **FIX:** Paper report now counts blocked/skipped/failed signals correctly
- **FEAT:** Manifest provenance automation — `/new_strat_mani` requires backtest evidence
- **FEAT:** Auto-generate backtest_hash with strategy+timestamp
- **FEAT:** Go-live gate checker rejects PENDING provenance entries
- **FEAT:** Decision memo template (NO_GO / PAPER_ONLY / READY_FOR_TINY_CAPITAL)
- **FIX:** Tournament dispatch limited to top 3 per symbol (was 326, now 33)
- All 7 manifest strategies have backtest provenance
- Go-live gate: 18/18 PASS
- Tests: 335 passed, 0 failed

### April 7, 2026
- Paper validation window started (Day 1 of 7)
- Converted all Telegram timestamps to IST, crons to 8:00 AM IST
- Paper validation monitoring: daily reports, stop conditions, reconciler summary
- Inventory verifier checks signal queue for live TradingView verification
- CEO audit fixes: reconciler cleanup, operational go-live gates
- Telegram commands for manifest management (/new_strat_mani, /list_manifest, /remove_strat_mani)
- Safety gate tests + automated go-live gate check script
- Trade type labels (Open/Close Long/Short) with SL and TP in alerts

### March 24, 2026
- Added real-time Google Sheets analytics (6 tabs, auto-updated on every trade)
- Fixed TradingView webhook 400 errors and timeouts
- Added `/health` endpoint

### March 23, 2026
- Fixed flip-flop trading with candle lock system
- Added symbol cooldown (300s) and quantity caps
- Cleaned stale ledger entries

### March 21, 2026
- Deployed Alpha Engine with grid-search tournament
- ADX > 20 filter + 2% trailing stop on all strategies

## License

Proprietary and confidential. All rights reserved.
