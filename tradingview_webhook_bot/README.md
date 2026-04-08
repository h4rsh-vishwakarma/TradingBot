# TradingView Webhook Bot

**Production-Grade Multi-Strategy Cryptocurrency Trading System**
**Version:** 4.0.0 | **Status:** Pre-production hardened / Paper validation active | **Last Updated:** April 8, 2026

---

## Overview

Automated cryptocurrency trading system that receives trading signals from TradingView Pine Script indicators via HTTP webhooks and executes trades on Binance Futures. Designed for production reliability with multi-strategy concurrent support, 4-layer risk management, and real-time monitoring.

**Key Characteristics:**
- **Signal-Driven:** Receives alerts from TradingView Pine Script indicators
- **Multi-Strategy:** 7 approved strategies running independently
- **Mainnet Price Authority:** All prices fetched from Binance mainnet (live spot/futures data)
- **Testnet Execution:** Orders on Binance Futures Testnet (paper validation active)
- **Approval Manifest:** Only strategies with backtest provenance can execute
- **Auto Exit Detection:** SELL against open LONG auto-detected as exit
- **Deterministic Ledger:** Accurate P&L tracking using Weighted Average Entry Price (WAEP)
- **Crash-Safe:** Atomic JSONL queue storage with offset management
- **Production Hardened:** Pydantic v2 schemas, CI/CD automation, reconciliation logic

---

## System Architecture

```
TradingView Indicator (Pine Script)
        |
        v
Webhook Server (Flask) -- Port 5000
  |-- Secret Validation
  |-- Data Validation (Pydantic v2)
  |-- Generates Signal ID
        |
        v
JSONL Queue (signals.jsonl) -- Atomic, Crash-Safe
  |-- Offset File (signals.offset)
  |-- Dead Letter Queue (dead_letter.jsonl)
        |
        v
Orchestrator (Core Engine)
  |-- Tournament Alpha Check (Leaderboard Validation)
  |-- Safety Gate (Risk Management)
  |-- ROI Guard (Negative History Block)
  |-- Tier-Based Interactive Gate
        |
        v
Exchange Layer (Binance)
  |-- Mainnet Price Substitution
  |-- Testnet Order Execution
  |-- Position Tracking
        |
        v
Storage & Monitoring
  |-- Ledger State (ledger_state.json)
  |-- Google Sheets Logging
  |-- Telegram Alerts
  |-- Reconciliation Audit
```

---

## Core Modules

### Webhook Server (`core/webhook_server.py`)

Receives and validates trading signals from TradingView.

- **Endpoint:** `POST /webhook/tradingview`
- **Secret Validation:** Verifies webhook secret matches `WEBHOOK_SECRET` env var
- **Smart Mapping:** Extracts strategy, symbol, action, price from flexible payload structures
- **Backtest Ingestion:** Secondary `/backtest-report` endpoint for strategy statistics
- **Non-blocking:** Spawns background thread, returns HTTP 200 immediately

**Payload Example:**
```json
{
  "signal_id": "sig_20260221_123456_BTCUSDT_LONG",
  "secret": "your_webhook_secret",
  "payload": {
    "strategy": "squeeze_flow_expansion",
    "symbol": "BTCUSDT",
    "action": "BUY",
    "price": 67850.50,
    "quantity": 0.003,
    "exchange": "binance",
    "indicator": "SMC_LuxAlgo"
  }
}
```

---

### Orchestrator (`core/orchestrator.py`) -- The Decision Engine

Core trading logic that consumes signals and executes trades with multi-layer validation.

**10-Layer Safety Pipeline:**

| Layer | Gate | Action |
|-------|------|--------|
| 1 | **Webhook Auth** | Secret validation (strict mode) |
| 2 | **Approval Manifest** | Strategy must be in approved_strategies.json with provenance |
| 3 | **Idempotency** | SQLite dedup by signal_id |
| 4 | **Signal Dedup** | Same strategy+symbol+side blocked within 120s |
| 5 | **Symbol Cooldown** | 300s between trades per symbol |
| 6 | **Candle Lock** | First signal wins per candle period |
| 7 | **Auto Exit Detection** | SELL against LONG auto-detected as exit |
| 8 | **Circuit Breaker** | Daily loss limit, consecutive losses, max drawdown |
| 9 | **Safety Gate** | Position conflict, kill switch check |
| 10 | **Qty Cap** | Per-symbol limits, equity-based sizing |

**Execution Flow:**
1. Parse signal (extract symbol, strategy, quantity, price, action)
2. Apply symbol cleaning (BTCUSDT normalization)
3. Check tournament tier -- block if not ALPHA/AVERAGE
4. Check ROI history -- block if negative
5. Check safety gates -- block if risky
6. Execute order (Binance Testnet via BinanceClient)
7. Apply fill to ledger (WAEP calculation)
8. Log to Google Sheets
9. Send Telegram alerts

---

### Position Ledger (`ledger/positions.py`)

Deterministic position accounting using Weighted Average Entry Price (WAEP).

**WAEP Formula:**
```
new_WAEP = (old_qty * old_price + new_qty * new_price) / total_qty
```

**Position Snapshot Structure:**
```json
{
  "symbol": "binance:BTCUSDT",
  "quantity": 0.003,
  "avg_price": 67500.00,
  "realized_pnl": 150.00,
  "daily_realized_pnl": 45.00,
  "last_update_date": "2026-03-21"
}
```

- Survives crashes via JSON persistence (`storage/ledger_state.json`)
- Tracks `trade_history` for Hybrid Scoring (last 50 trades)
- Daily PnL resets at UTC midnight

---

### Telegram Listener (`core/telegram_listener.py`)

Interactive command-based control and monitoring via Telegram bot.

| Command | Purpose |
|---------|---------|
| `/help` | Display full command reference |
| `/status` | Live system health (net profit, trade count, strategy) |
| `/alpha` | Deploy top Alpha strategies (auto-runs daily 9 AM UTC) |
| `/audit` | Tournament Leaderboard -- Top 10 strategies |
| `/buy SYMBOL` | Manual BUY signal (e.g., `/buy SOLUSDT`) |
| `/sell SYMBOL` | Manual SELL signal |
| `/override SYMBOL` | Force BUY (bypasses tier check) |
| `/new_strat_mani` | Add strategy to approval manifest (requires notes) |
| `/list_manifest` | Show all approved strategies |
| `/remove_strat_mani` | Remove strategy from manifest |
| `/stop` | Emergency stop — halt all dispatches |

---

### Script Vault (`core/script_vault.py`)

Dynamically generates and deploys Pine Script indicators to Telegram.

- **GOD MODE Template:** Zero-margin Pine Script with error bypass logic
- **Logic Injection:** Automatically inserts strategy-specific logic based on type:
  - SMC/Liquidity/Flow/BarUpDn: Lookback-based logic
  - Supertrend: ATR-based trend following
  - Default: Bollinger Bands logic
- **DD Reduction:** ADX > 25 filter + 4% trailing stop
- **Rate Limiting:** 3-4 second delays to avoid Telegram HTTP 429 errors

---

### Google Sheets Logger (`storage/sheets_logger.py`)

Real-time P&L and trade logging to Google Sheets for dashboards.

- **OAuth 2.0 Auth:** Uses service account credentials (`service_account.json`)
- **Dual Tabs:** "Trades" (executed trades) + "Blocked Trades" (rejected signals)
- **Row Structure:** Signal ID | Timestamp | Symbol | Action | Qty | Price | PnL | Indicator | Strategy

---

### Telegram Alerts (`alerts/telegram_alerts.py`)

Real-time notifications for critical trading events.

**Alert Severity Levels:**

| Level | Icon | Usage |
|-------|------|-------|
| DEBUG | (magnifier) | Detailed diagnostics |
| INFO | (info) | General information |
| WARNING | (warning) | Caution needed |
| HIGH | (orange) | Important alerts |
| CRITICAL | (siren) | System failures |

**Built-in Alerts:** `circuit_breaker_tripped`, `position_stuck`, `no_signals_received`, `api_error_spike`, `position_opened`, `position_closed`, `daily_summary`, `bot_started`, `bot_stopped`

Rate limited: 60-second minimum between identical alerts (configurable).

---

### JSONL Queue & Offset Consumer (`storage/jsonl_consumer.py`)

Crash-safe, offset-based signal queuing.

- Signals written to `signals.jsonl` as newline-delimited JSON
- Offset tracked in `signals.offset` file (O(1) seek on restart)
- Only advances offset after successful processing
- Corrupt lines moved to `dead_letter.jsonl` with error reason
- File truncation detection: resets offset to 0 if file shrinks

---

### Idempotency Store (`storage/idempotency_store.py`)

Prevents duplicate order execution (exactly-once semantics).

- SQLite-based (`idempotency.db`)
- Handles TradingView re-fires, network retries
- Survives system restarts

---

### Binance Client (`exchange/binance_client.py`)

Hardened Binance Futures API wrapper.

- **Mainnet Price Substitution:** Fetches real prices from `fapi.binance.com`
- **Testnet Execution:** Orders placed on testnet
- **Retry Logic:** Exponential backoff (up to 3 attempts)
- **Account Health:** Available balance, margin ratio monitoring
- **Audit Data:** Returns open positions for reconciliation

---

### Reconciliation Engine (`recon/reconciler.py`)

Audits ledger against actual Binance positions.

- Compares local ledger vs Binance balances
- Detects and logs drift
- Auto-fixes by syncing ledger to Binance reality

---

## Approved Strategies (Manifest)

| Strategy | Exchange | Symbols | Timeframe | Provenance |
|----------|----------|---------|-----------|------------|
| CCI Trend | Binance | ETHUSDT | 4h | Realistic backtest (ROI=5.91%, Sharpe=0.69) |
| Donchian Trend | Binance | ETHUSDT | 4h | Realistic backtest (ROI=3.26%, Sharpe=0.41) |
| 44_PSAR_Volume_Surge | Binance | BTCUSDT | 4h | Tournament (ROI=1.19%, Sharpe=5.53) |
| 56_PSAR_Volume_Tight | Binance | ETHUSDT, BTCUSDT | 4h | Tournament (ROI=1.148%, Sharpe=5.35) |
| 57_PSAR_Volume_Ultra | Binance | ETHUSDT | 4h | Tournament (ROI=1.19%, Sharpe=5.53) |
| L_X | Binance | ETHUSDT, BTCUSDT | 4h | Pine-only (paper validation) |
| Long | Binance | ETHUSDT, BTCUSDT | 4h | Pine-only (paper validation) |

Manifest: `config/approved_strategies.json`. Managed via Telegram `/new_strat_mani` (requires backtest evidence).

---

## Storage Structure

```
storage/
|-- signals.jsonl              # Primary signal queue
|-- signals.offset             # Consumer offset tracking
|-- dead_letter.jsonl          # Corrupt/failed signals
|-- ledger_state.json          # Position ledger & trade history
|-- idempotency.db             # SQLite DB for duplicate detection
|-- alerts.jsonl               # Alert history (rotated)
|-- sheets_logger.py           # Google Sheets integration
|-- jsonl_consumer.py          # Offset-based queue consumer
|-- idempotency_store.py       # Duplicate prevention
`-- trading_system.db          # Legacy database
```

---

## Configuration

### Environment Variables

```bash
# Binance API
BINANCE_API_KEY=your_api_key
BINANCE_API_SECRET=your_api_secret
BINANCE_TESTNET=true

# Trading
ALLOW_REAL_TRADES=false
RUN_MODE=production
WEBHOOK_SECRET=your_secret
MAX_NOTIONAL_PER_TRADE=500.0
DAILY_LOSS_LIMIT=-50.0

# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Google Sheets
GOOGLE_SERVICE_ACCOUNT_FILE=/etc/tradingbot/service_account.json
GOOGLE_SHEET_NAME=Trading_Bot_Ledger
```

### Settings File (`config/settings.json`)

```json
{
  "strategy_name": "multi_strategy",
  "virtual_balance": 1000.0,
  "trading": {
    "symbols_allowed": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
    "timeframes_allowed": ["1", "5", "15", "60", "240", "D"],
    "leverage": 1,
    "order_type": "LIMIT"
  },
  "risk": {
    "max_positions": 5,
    "position_size_type": "PERCENT_OF_BALANCE",
    "position_size_value": 10.0,
    "stop_loss_pct": 2.0,
    "take_profit_pct": 4.0,
    "max_drawdown_limit": 10.0
  },
  "webhook": {
    "host": "0.0.0.0",
    "port": 5000,
    "secret": "your_secret"
  }
}
```

---

## Deployment

### Systemd Services

```bash
# Webhook Server
sudo systemctl start tv-webhook
sudo systemctl status tv-webhook
journalctl -u tv-webhook -f

# Trading Engine
sudo systemctl start tv-engine
sudo systemctl status tv-engine
journalctl -u tv-engine -f
```

Service files: `deploy/systemd/tv-webhook.service`, `deploy/systemd/tv-engine.service`

Nginx configs: `deploy/nginx/`

### Pre-Flight Checklist

- ALLOW_REAL_TRADES set correctly in env_vars
- Backtest CSVs exist in `backtesting/A_Leaderboard/backtest_imports/`
- Telegram bot token and chat ID configured
- Google Sheets service account authenticated
- Binance API keys (Testnet) working
- Webhook secret matches TradingView alerts
- Nginx reverse proxy running (if HTTPS required)

---

## Monitoring

```bash
# Watch orchestrator logs
sudo journalctl -u tv-engine -f -n 50

# Check processed signals count
sqlite3 storage/idempotency.db \
  "SELECT COUNT(*) FROM processed_signals;"

# View recent trades
sqlite3 storage/idempotency.db \
  "SELECT signal_id, processed_at FROM processed_signals ORDER BY processed_at DESC LIMIT 10;"

# Check ledger state
cat storage/ledger_state.json | python3 -m json.tool

# Check signal queue offset
cat storage/signals.offset
```

---

## Runbook

### Service Down
1. SSH into the server
2. Restart: `sudo systemctl restart tv-engine` / `sudo systemctl restart tv-webhook`
3. Check logs: `sudo journalctl -u tv-engine -f -n 50`

### DLQ (Dead Letter Queue) Alert
1. Inspect: `python3 scripts/dlq_inspector.py`
2. Network error: Fix connectivity, run `python3 scripts/dlq_replay.py`
3. Validation error: Update signal mapping in orchestrator, then replay

### Reconciliation Drift
1. Auto-fixes on restart via `sync_ledger.py`
2. Manual fix: `python3 scripts/sync_ledger.py`

### Emergency Stop
- Telegram: Send `/stop`
- CLI: `python3 scripts/kill_switch.py`
- Systemd: `sudo systemctl stop tv-engine`

### Rotating Secrets
1. Update `.env` with new keys
2. Restart both services
3. Verify: `journalctl -u tv-engine -f | grep "Connected to Binance"`

---

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/daily_alpha_check.py` | Daily automated leaderboard update & strategy validation |
| `scripts/strategy_tournament.py` | Run multi-timeframe backtests, generate leaderboard CSV |
| `scripts/dlq_inspector.py` | Inspect Dead Letter Queue for failure reasons |
| `scripts/dlq_replay.py` | Replay failed signals after fixing issues |
| `scripts/kill_switch.py` | Emergency stop: close all positions & pause trading |
| `scripts/generate_backtest_csvs.py` | Auto-generate backtest CSVs from historical data |
| `scripts/auto_injector.py` | Auto-generate Pine Scripts from leaderboard |
| `scripts/smoke_test_signal.py` | Send test signal to webhook |
| `scripts/system_health_check.py` | System health diagnostics |

---

## CI/CD

GitHub Actions (`.github/workflows/ci.yml`):
- **Triggers:** Push/PR to `main`
- **Steps:** Python 3.10, install requirements, run 335 tests (integration, orchestrator, strategy, lighter, exit, alpha, backtest realism, inventory, reconciler)

---

## Testing

```bash
# Run full test suite (335 tests)
source venv/bin/activate
python -m pytest -v tests/ tradingview_webhook_bot/recon/test_recon.py

# Ledger math audit
python3 ledger/test_ledger.py

# Reconciliation tests
python3 recon/test_recon.py

# Storage tests
python3 storage/test_storage.py
```

---

## File Structure

```
tradingview_webhook_bot/
|-- core/
|   |-- orchestrator.py            # Core decision engine
|   |-- telegram_listener.py       # Telegram bot commands
|   |-- script_vault.py            # Pine Script generation
|   |-- webhook_server.py          # Signal reception
|   |-- signal_processor.py        # Signal parsing
|   |-- risk_manager.py            # Risk controls
|   |-- strategy_engine.py         # Strategy logic
|   |-- balance_manager.py         # Virtual balance tracking
|   |-- circuit_breaker.py         # Circuit breaker pattern
|   |-- reconciler.py              # Position reconciliation
|   `-- schemas.py                 # Pydantic v2 models
|-- exchange/
|   |-- binance_client.py          # Binance API wrapper
|   |-- execution_engine.py        # Testnet order execution
|   `-- price_provider.py          # Mainnet price feeds
|-- ledger/
|   |-- positions.py               # WAEP position ledger
|   `-- test_ledger.py             # Ledger math tests
|-- storage/
|   |-- sheets_logger.py           # Google Sheets logging
|   |-- jsonl_consumer.py          # Queue consumer
|   |-- idempotency_store.py       # Duplicate detection
|   |-- signals.jsonl              # Signal queue
|   |-- ledger_state.json          # Position state
|   `-- idempotency.db             # Processed signals DB
|-- alerts/
|   |-- telegram_alerts.py         # Alert system
|   |-- email_notifier.py          # Email alerts
|   `-- router.py                  # Alert routing
|-- recon/
|   |-- reconciler.py              # Position reconciliation
|   `-- test_recon.py              # Recon tests
|-- utils/
|   |-- logger.py                  # Logging setup
|   |-- dashboard_updater.py       # Dashboard updates
|   |-- health_checker.py          # Health monitoring
|   `-- signal_archiver.py         # Signal archival
|-- main_enhanced.py               # Enhanced bot entry point
`-- tradingview_webhook_server.py  # Server entry point
```

---

## Security

- API keys stored as environment variables (never in code)
- Testnet keys for execution (no real funds at risk)
- Mainnet read-only access (price data only)
- Webhook secret token validation on every request
- HTTPS via Nginx reverse proxy (optional)
- Position size limits and daily loss controls
- Kill switch for emergency shutdown

---

**Developed by:** Harsh
**Environment:** Binance Futures Testnet (Mainnet Price Authority)
**License:** Proprietary and confidential. All rights reserved.
