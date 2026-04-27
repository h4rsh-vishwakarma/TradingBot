# Trading Bot System Runbook

**Version:** 4.0 | **Updated:** April 8, 2026 | **Server:** `ubuntu@15.207.152.119`

---

## 1. System Architecture

### Signal Flow

```
TradingView (7 Approved Strategies on ETHUSDT/BTCUSDT)
      |
      v  HTTPS POST (JSON + Plain Text alerts)
+-----+------+
|    Nginx   |  Port 443, SSL, rate limiting
+-----+------+
      |
      v  proxy_pass :5000
+-----+------+
|  Gunicorn  |  2 workers, 2 threads, gthread | trading_webhook.service
| webhook_   |  Parses JSON & plain text formats
| server.py  |  Validates secret, generates signal_id
+-----+------+
      |
      v  Append to signals.jsonl (crash-safe queue)
+-----+------+
| Orchestrator|  trading_orchestrator.service
| orchestrator|
|    .py      |  7 Safety Gates:
|             |   1. Idempotency (SQLite)
|             |   2. Leaderboard Tier (ALPHA only)
|             |   3. Signal Dedup (120s window)
|             |   4. Symbol Cooldown (300s)
|             |   5. Candle Lock (first wins per hour)
|             |   6. Safety Gate (daily loss, position conflict)
|             |   7. Qty Cap (SOL:1, ETH:0.05, BTC:0.003)
+-----+------+
      |
      v  MARKET order
+-----+------+
|   Binance  |  Testnet execution, Mainnet price authority
|   Futures  |  Min notional $21, qty precision rules
+-----+------+
      |
      v  After each trade
+-----+------+-----+-------+
|Telegram |Sheets |Ledger |Analytics|
| alert   |Trades | state |3 tabs   |
+---------+-------+-------+---------+
```

### Data Flow

```
Historical Data          Tournament              Live Trading
(3Y 15m candles)    (strategy_tournament.py)   (orchestrator.py)
     |                      |                        |
     v                      v                        v
 BTCUSDT_3y_15m.csv   tournament_winners.csv    signals.jsonl
 ETHUSDT_3y_15m.csv        |                    ledger_state.json
 SOLUSDT_3y_15m.csv        v                    idempotency.db
                    Pine Script generation           |
                    (script_vault.py)                v
                           |                  Google Sheets:
                           v                   - Trades
                    Telegram dispatch          - Blocked Trades
                    (11 scripts daily)         - Daily Analytics
                                               - Backtest With Safety
                                               - Backtest Without Safety
```

---

## 2. Services

| Service | Type | Port | Description |
|---------|------|------|-------------|
| `trading_webhook` | Gunicorn | 5000 | HTTP webhook receiver |
| `trading_orchestrator` | Python daemon | - | Signal consumer + executor |
| `trading_dashboard` | Streamlit | 8501 | Health dashboard UI |
| `hl_mirror` | Python daemon | - | Hyperliquid mirror (optional) |
| `telegram_bot` | Python daemon | - | Telegram backtest bot |
| `nginx` | Reverse proxy | 443 | SSL termination + rate limit |

### Service Commands

```bash
# Status
sudo systemctl status trading_webhook trading_orchestrator trading_dashboard

# Restart
sudo systemctl restart trading_webhook trading_orchestrator trading_dashboard

# Logs (live tail)
journalctl -u trading_orchestrator -f
journalctl -u trading_webhook -f
journalctl -u trading_dashboard -f

# Health check
curl http://127.0.0.1:5000/health
curl -I http://127.0.0.1:8501
```

---

## 3. Cron Jobs

| Schedule (UTC) | Script | Purpose |
|:-:|--------|---------|
| 00:00 | `fetch_historical_data.py` | Download 3-year OHLCV for BTC/ETH/SOL |
| 00:15 | `strategy_tournament.py` | Grid-search optimization, output winners CSV |
| 09:00 | `script_vault.py` | Deploy top 11 Pine Scripts to Telegram |
| Every hour | `auto_injector.py` | Heartbeat scan (webhook, orchestrator, processes) |
| 23:55 | `analytics_writer.py` | End-of-day analytics snapshot to Google Sheets |
| 00:00 | `tradingbot_sync.sh` | Git sync backup |

### Edit Cron

```bash
crontab -e
```

---

## 4. Google Sheets (Auto-Updated)

**Sheet Name:** `Trading_Bot_Ledger`

All tabs below auto-update on every trade execution:

| Tab | Content | Update Trigger |
|-----|---------|----------------|
| **Trades** | Every executed trade (signal_id, time, symbol, side, qty, price, PnL, strategy) | Every trade |
| **Blocked Trades** | Every rejected signal (time, symbol, side, strategy, rejection reason) | Every blocked signal |
| **Daily Analytics** | Daily breakdown (trades, wins, losses, win rate, gross profit/loss, net PnL, running capital, Net DD%, Worst DD%) | Every trade |
| **Backtest - With Safety** | Same as Daily Analytics but only executed trades | Every trade |
| **Backtest - Without Safety** | All signals including blocked ones (shows what happens without safety gates) | Every trade |

### Analytics Columns

| Column | Description |
|--------|-------------|
| Date | Trading day |
| Total Signals | Signals received |
| Executed | Trades that passed all 7 safety gates |
| Blocked | Signals rejected by safety gates |
| Wins / Losses | Trades with positive/negative PnL |
| Win Rate % | Wins / Executed * 100 |
| Gross Profit | Sum of all positive PnL |
| Gross Loss | Sum of all negative PnL |
| Net PnL | Gross Profit + Gross Loss |
| Running Capital | Starting $10K + cumulative Net PnL |
| Net DD % | `(10000 - Running Capital) / 10000 * 100` (only when below $10K) |
| Worst DD % | Peak-to-trough maximum drawdown from any capital high point |

### Manual Analytics Refresh

```bash
cd /home/ubuntu/tradingview_webhook_bot
venv/bin/python3 -c 'from tradingview_webhook_bot.storage.analytics_writer import AnalyticsWriter; AnalyticsWriter().update_today()'
```

---

## 5. Backtesting Engine

### Tournament Pipeline

Runs daily at 00:15 UTC:

```
Step 1: fetch_historical_data.py
  - Downloads 3-year 15m candles from Binance
  - Symbols: BTCUSDT, ETHUSDT, SOLUSDT
  - Output: storage/backtest_data/*_3y_15m.csv

Step 2: strategy_tournament.py
  - 38+ strategies x 3 symbols x 7 parameter combos
  - Grid-search: SMA period (8-28), Bollinger mult (1.5-4.2), lookback (14-26)
  - Ranking: Daily ROI, Sharpe ratio, win rate, max drawdown
  - Output: storage/reports/tournament_winners.csv

Step 3: script_vault.py (09:00 UTC)
  - Takes top 11 winners from tournament
  - Generates Pine Script v5 with webhook alerts
  - Adds ADX > 25 filter + 4% trailing stop
  - Dispatches to Telegram for deployment to TradingView
```

### Strategy Types

| Category | Strategies | Logic |
|----------|-----------|-------|
| Mean Reversion | OPTIMIZED, MVO Momentum, ML Lorentzian, Mean Reversion Scalper, OBV WaveTrend | `close < SMA - mult * StdDev` (buy), `close > SMA + mult * StdDev` (sell) |
| Momentum | Reversed BarUpDn, SMC LuxAlgo, Reverse Liquidity Trap, Institutional Flow Hybrid | `close > close[lookback]` (buy), `close < close[lookback]` (sell) |

### Tournament Winners CSV

Located at `storage/reports/tournament_winners.csv`:

```
Strategy, Symbol, Daily_ROI, Optimal_Len, Optimal_Mult, Win_Rate, Sharpe, Total_Trades, Gross_DD, Net_DD
```

The orchestrator reads this file to validate incoming signals (Tier Check gate).

### Manual Tournament Rerun

```bash
cd /home/ubuntu/tradingview_webhook_bot
venv/bin/python3 scripts/strategy_tournament.py
```

---

## 6. Drawdown Calculations

### Net DD (Drawdown from Starting Capital)

```
Net DD % = (Starting Capital - Lowest Capital) / Starting Capital * 100
```

- Starting Capital = $10,000
- Only counts when capital drops BELOW $10,000
- Tracked per-day in Daily Analytics sheet

### Worst DD (Peak-to-Trough)

```
Worst DD % = (Peak Capital - Current Capital) / Peak Capital * 100
```

- Measures maximum drop from ANY high point (not just starting capital)
- Cumulative across all trading days

### Gross DD vs Net DD

| Metric | Includes Fees? | Use Case |
|--------|:---:|-----------|
| Gross DD | No | Raw strategy performance |
| Net DD | Yes (0.1% per side) | Actual account impact |

---

## 7. Safety Pipeline Details

### Gate 1: Idempotency

- SQLite database at `storage/idempotency.db`
- Each `signal_id` (e.g., `TV-1774335610`) stored after processing
- Prevents duplicate execution if TradingView sends same alert twice

### Gate 2: Leaderboard Tier

- Reads `storage/reports/tournament_winners.csv`
- Strategy+Symbol must exist in top rankings
- Rejects strategies not in the leaderboard

### Gate 3: Signal Dedup (120s)

- Same `strategy + symbol + side` combination blocked within 120 seconds
- Prevents JSON and plain-text duplicate alerts from same TradingView alert

### Gate 4: Symbol Cooldown (300s)

- After executing a trade on any symbol, 300s cooldown on that symbol
- Prevents rapid-fire from multiple strategies on same symbol

### Gate 5: Candle Lock (3600s)

- First signal that executes on a symbol locks direction for 1 hour
- Example: If BUY SOLUSDT executes, all SELL SOLUSDT blocked until next hour
- Prevents flip-flop trading where strategies disagree on direction

### Gate 6: Safety Gate

- Daily PnL loss limit (configurable, default -$50)
- No opening position if already in same-direction position
- All trades blocked when daily loss limit hit

### Gate 7: Quantity Cap

- Hard limits per symbol regardless of signal:
  - SOLUSDT: max 1.0
  - ETHUSDT: max 0.05
  - BTCUSDT: max 0.003
- Min notional: $21 (Binance Futures minimum $20 + buffer)

---

## 8. Webhook Format

### JSON Format (from Pine Script `alert()`)

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

### Plain Text Format (TradingView default)

```
Machine Learning Lorentzian Classification | SOLUSDT - Webhook (squeeze_tradingview_cluster_2026_secure): order buy @ 10 filled on SOLUSDT_PREMIUM. New strategy position is 10
```

Both formats are supported. The webhook server auto-detects and parses either.

**Symbol cleaning:** `SOLUSDT_PREMIUM` -> `SOLUSDT`, `BTCUSD_PERP` -> `BTCUSDT`

---

## 9. Troubleshooting

### Common Issues

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| TradingView 400 Bad Request | Unknown alert format or price=0 | Check `journalctl -u trading_webhook -f`; unknown formats return 200 (ignored) |
| TradingView Timeout | Webhook processing too slow | Price=0 signals queue instantly; orchestrator fetches price async |
| "Notional must be >= 20" | Qty too small for Binance minimum | Min notional auto-adjusted to $21; check `binance_client.py fix_quantity()` |
| Flip-flop trades | Multiple strategies contradicting | Candle lock + cooldown prevents this; check `orchestrator.py` |
| "Already in BUY position" | Duplicate position attempt | Safety Gate working correctly; this is expected behavior |
| Heartbeat alert fires | Webhook /health not responding | Check `sudo systemctl status trading_webhook`; verify `/health` route exists |
| Strategy tier blocked | Strategy not in tournament winners | Rerun `strategy_tournament.py` or check CSV matches strategy name |
| Google Sheets quota error | Too many API calls | Analytics is rate-limited; end-of-day cron as backup |

### Debug Commands

```bash
# Check what trades happened today
journalctl -u trading_orchestrator --since today | grep "Trade Success\|Order Success"

# Check what got blocked today
journalctl -u trading_orchestrator --since today | grep "Cooldown\|Candle Lock\|Safety Gate\|Tier Block"

# Check webhook delivery
sudo tail -100 /var/log/nginx/access.log | grep "webhook"

# Check current positions
cat tradingview_webhook_bot/storage/ledger_state.json | python3 -m json.tool

# Check last 10 trades
python3 -c "
import json
with open('tradingview_webhook_bot/storage/ledger_state.json') as f:
    data = json.load(f)
for t in data.get('trade_history', [])[-10:]:
    print(f\"{t['timestamp'][:19]}  {t['symbol']:12s}  {t['side']:4s}  PnL: \${t['pnl']:>8.2f}\")
"
```

---

## 10. Emergency Procedures

### Stop All Trading

```bash
sudo systemctl stop trading_orchestrator
# or
python3 scripts/kill_switch.py  # closes all positions + stops
```

### Reset Ledger

```bash
# Backup first
cp tradingview_webhook_bot/storage/ledger_state.json ledger_backup_$(date +%F).json
# Clear
echo '{"open_positions": {}, "trade_history": [], "daily_pnl": 0}' > tradingview_webhook_bot/storage/ledger_state.json
sudo systemctl restart trading_orchestrator
```

### Reconcile Positions

```bash
python3 -m tradingview_webhook_bot.recon.reconciler
```

### R-04 Quarantined Positions (Documented Exception)

The gate check reports 6 positions quarantined under R-04. These are positions that
were opened by signals outside the ETHUSDT decision lane (pre-G-01 governance
enforcement, before 2026-04-18) and are now inert — they generate no new orders and
carry no active capital. They appear in the reconciler snapshot but do not affect
live P&L or the SIDE_MISMATCH drift check.

**H-4 Idempotency Audit (2026-04-27):** 0 duplicate signal_ids found in the
idempotency DB for the Apr 25–27 window during the duplicate orchestrator incident.
The idempotency DB absorbed all signals cleanly — no double-executions occurred.

Resolution: these positions will be closed at next paper-window reset. Until then,
they are documented here as a known, inert exception.

### Clear Signal Queue

```bash
# Dangerous: only if queue is corrupted
echo "" > tradingview_webhook_bot/storage/signals.jsonl
echo "0" > tradingview_webhook_bot/storage/signals.offset
sudo systemctl restart trading_orchestrator
```

---

## 11. Deployment

### First-Time Setup

```bash
# 1. Clone repo
cd /home/ubuntu
git clone <repo_url> tradingview_webhook_bot
cd tradingview_webhook_bot

# 2. Virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r tradingview_webhook_bot/requirements.txt

# 3. Environment config
sudo mkdir -p /etc/tradingbot
sudo cp .env.example /etc/tradingbot/env_vars
sudo nano /etc/tradingbot/env_vars  # Fill API keys

# 4. Google Sheets service account
sudo cp service_account.json /etc/tradingbot/service_account.json

# 5. Deploy services
sudo cp deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now trading_webhook trading_orchestrator

# 6. Setup cron
crontab -e  # Add cron entries from Section 3

# 7. Verify
curl http://127.0.0.1:5000/health
journalctl -u trading_orchestrator -f
```

### Update Deployment

```bash
cd /home/ubuntu/tradingview_webhook_bot
git pull origin main
sudo systemctl restart trading_webhook trading_orchestrator
```

---

## 12. Pre-Flight Checklist

Before going live, verify:

- [ ] `/etc/tradingbot/env_vars` has all API keys filled
- [ ] `ALLOW_REAL_TRADES=true` in env_vars
- [ ] `BINANCE_TESTNET=true` (or false for real money)
- [ ] Telegram bot token valid and sending heartbeats
- [ ] Google Sheets service account has editor access to sheet
- [ ] Tournament winners CSV exists and has recent date
- [ ] TradingView alerts configured with correct webhook URL and secret
- [ ] Nginx SSL certificate valid (`sudo certbot certificates`)
- [ ] All 11 Pine Scripts loaded on TradingView charts
- [ ] `/health` endpoint returns 200

---

## 13. File Locations

| File | Purpose |
|------|---------|
| `/etc/tradingbot/env_vars` | All environment variables (API keys, secrets) |
| `/etc/tradingbot/service_account.json` | Google Sheets service account key |
| `storage/signals.jsonl` | Signal queue (append-only) |
| `storage/signals.offset` | Queue consumer position |
| `storage/idempotency.db` | Processed signal ID store |
| `storage/ledger_state.json` | Current positions + trade history + daily PnL |
| `storage/reports/tournament_winners.csv` | Daily tournament rankings |
| `storage/backtest_data/*.csv` | 3-year historical candle data |
| `/var/log/nginx/access.log` | Nginx request logs |
| `auto_scan.log` | Hourly heartbeat scan logs |
| `cron_logs.log` | Cron job output logs |
