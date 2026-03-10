# 🚀 Bitcoin Automated Trading Systems

**Advanced Multi-Strategy Cryptocurrency Trading Platform**  
**Server:** ubuntu@13.236.143.201  
**Status:** ✅ Operational (February 18, 2026)

---

## 📋 Overview

This repository contains two sophisticated automated trading systems for Bitcoin futures trading:

1. **Liquidation Heatmap Bot** - Data-driven liquidation cluster analysis and trading
2. **TradingView Webhook Bot** - Multi-strategy signal-based automated execution

Both systems operate on Binance Futures with advanced risk management, real-time monitoring, and comprehensive observability.

---

## 🎯 Trading Systems

###  TradingView Webhook Bot

**Strategy:** Receives and executes signals from TradingView indicators via HTTP webhooks.

**Key Features:**
- ✅ 8+ concurrent strategies running simultaneously
- ✅ Mainnet price authority (real market data)
- ✅ Virtual balance tracking per strategy
- ✅ TradingView alert integration (Pine Script)
- ✅ Stop-loss and take-profit automation
- ✅ Real-time P&L tracking with Google Sheets dashboard

**Active Strategies:**
1. **Institutional Flow Hybrid** - Volume profile + smart money
2. **Squeeze Flow Expansion** - Bollinger squeeze breakout
3. **SMA Crossover 9/21** - Moving average crossover
4. **Supertrend BTC 4H** - ATR-based trend following
5. **OBV WaveTrend Scalper** - Volume oscillator scalping
6. **Madrid Ribbon** - Multi-timeframe EMA ribbon
7. **Institutional Matrix** - Order flow analysis
8. **Lorentzian Classification** - ML-based price prediction

**Performance:**
- Total Strategies: 8 active bots
- Uptime: 99%+ (systemd managed)
- Signal Processing: Real-time webhook reception
- Risk Management: Independent virtual balances per strategy

**Location:** `/home/ubuntu/tradingview-bot/`

📖 **[Read Full Documentation →](docs/TRADINGVIEW_BOT_DOCUMENTATION.md)**  

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     TRADING SYSTEMS OVERVIEW                    │
└─────────────────────────────────────────────────────────────────┘

┌──────────────────────────┐      ┌──────────────────────────────┐
│  LIQUIDATION HEATMAP BOT │      │   TRADINGVIEW WEBHOOK BOT    │
│  ─────────────────────── │      │   ─────────────────────────  │
│                          │      │                              │
│  📊 Data Sources:        │      │  📡 Signal Sources:          │
│  • Coinglass Scraper     │      │  • TradingView Alerts        │
│  • Binance OI/FR         │      │  • Pine Script Indicators    │
│  • LSR Data              │      │  • Webhook HTTP POST         │
│                          │      │                              │
│  🧮 Analysis:            │      │  🤖 Execution:               │
│  • DBSCAN Clustering     │      │  • Multi-Strategy Manager    │
│  • Multi-TF Analysis     │      │  • Virtual Balance Tracking  │
│  • 5-Layer Validation    │      │  • LIMIT Order Execution     │
│                          │      │                              │
│  💹 Execution:           │      │  📈 Strategies:              │
│  • Cluster-Based Entry   │      │  • 8 Independent Bots        │
│  • R-Based Position Size │      │  • Concurrent Processing     │
│  • Dynamic SL/TP         │      │  • Per-Strategy Risk Mgmt    │
│                          │      │                              │
│  🎯 Status: ✅ Active    │      │  🎯 Status: ✅ Active        │
└──────────────────────────┘      └──────────────────────────────┘
           │                                    │
           └──────────────┬─────────────────────┘
                          │
                          ▼
           ┌──────────────────────────────┐
           │    BINANCE FUTURES TESTNET   │
           │    ─────────────────────────│
           │    • Order Execution         │
           │    • Position Management     │
           │    • Mainnet Price Feed      │
           └──────────────────────────────┘
                          │
                          ▼
           ┌──────────────────────────────┐
           │   MONITORING & OBSERVABILITY │
           │   ──────────────────────────│
           │   • Google Sheets Dashboards │
           │   • Real-time P&L Tracking   │
           │   • Signal Logs              │
           │   • Health Heartbeats        │
           └──────────────────────────────┘
```

---

## 📊 Current Status

### System Health (February 18, 2026)

**Liquidation Heatmap Bot:**
- ✅ Scrapers running (coinglass_visual + OI/FR loop)
- ✅ Fresh data: Current BTC $68,080-$68,210
- ✅ 428 liquidation data points loaded
- ✅ 10 clusters identified
- ✅ Signals generating (SHORT bias detected)
- ⚠️ Order execution paused (insufficient margin)

**TradingView Webhook Bot:**
- ✅ 8 strategies active (systemd services)
- ✅ Webhook server operational (port 8004)
- ✅ Real-time signal processing
- ✅ Virtual balance tracking accurate
- ✅ Google Sheets dashboard updating

**Infrastructure:**
- ✅ Xvfb virtual display (Chrome scraping)
- ✅ File descriptor limits: 65,536
- ✅ Watchdog scripts monitoring processes
- ✅ Cron jobs running (every 2 min checks)

---

## 📁 Repository Structure


```
.
└── tradingview_webhook_bot
    ├── README.md
    ├── RUNBOOK.md
    ├── archive
    │   ├── enhanced_trading_bot_remote.py
    │   ├── legacy_backup
    │   │   ├── conftest.py
    │   │   ├── debug_poll.py
    │   │   ├── generate_report.py
    │   │   ├── ingest_trades.py
    │   │   ├── send_fake_signals.py
    │   │   ├── sync_ledger.py
    │   │   ├── telegram_listener_secure.py
    │   │   ├── test_alerts.py
    │   │   └── test_telegram.py
    │   ├── main.py
    │   ├── main_engine.py
    │   └── simulate_signal.py
    ├── auto_scan.log
    ├── aws-configs
    │   ├── harsh-key-ap-south-1.pem
    │   └── harsh-server-ap-south-1
    │       └── HARSH_ACCESS_AP_SOUTH_1.md
    ├── backtesting
    │   ├── A_Leaderboard
    │   │   ├── backtest_imports
    │   │   │   ├── EMA_9_15_Strategy_with_Webhook_BINANCE_BTCUSDH2026_2026-03-05_15m.csv
    │   │   │   ├── LuxAlgo_-_SMC_Strategy_BINANCE_ETHUSDH2026_2026-03-05_15m.csv
    │   │   │   ├── MACD_Strategy_BINANCE_ETHUSDH2026_2026-03-05_4h.csv
    │   │   │   ├── OBV_Div_BINANCE_BTCUSDH2026_2026-03-05_4h.csv
    │   │   │   ├── Reverse_Liquidity_Trap_[PyraTime_Logic]_BINANCE_SOLUSDH2026_2026-03-05_4h.csv
    │   │   │   └── SQZGo-WH_BITSTAMP_BTCUSD_2026-03-05_4h.csv
    │   │   ├── ingest_csv.py
    │   │   └── report.py
    │   ├── __init__.py
    │   ├── core
    │   │   ├── add_last_updated.py
    │   │   ├── init_db.py
    │   │   └── schemas
    │   │       └── event_schema_v1.json
    │   ├── data
    │   ├── db.sqlite3
    │   ├── engine.py
    │   └── pine
    │       ├── 'SMC Strategy [LuxAlgo] + Webhook', 'LuxAlgo - SMC'
    │       ├── ATR Supertrend [QuantAlgo]
    │       ├── EMA 9by15 Strategy
    │       ├── EMA-SMA Crossover
    │       ├── Enhanced ATR Supertrend
    │       ├── Hackathon V3 FIXED - Institutional Matrix
    │       ├── Hybrid SMC [MarkitTick]
    │       ├── Hybrid Smart Money Concepts [MarkitTick]
    │       ├── Institutional Flow Hybrid [SMC + Hull + RSI]
    │       ├── ML Lorentzian Classification
    │       ├── MVO Momentum Variance
    │       ├── Machine Learning Lorentzian Classification
    │       ├── Madrid Ribbon
    │       ├── Mean Reversion Scalper Hybrid
    │       ├── Momentum Variance Oscillator
    │       ├── OBV + WaveTrend Volume Scalper
    │       ├── OBV Divergence Strategy
    │       ├── Oppsite SMA
    │       ├── Reverse Liquidity Trap
    │       ├── Reverse MACD Strategy [ETH 1D]
    │       ├── Reverse Madrid Ribbon Strategy
    │       ├── Reverse SMA 9 Cross
    │       ├── Reverse SMA Cross Backtest - ETH 1H
    │       ├── Reverse SuperTrend - ETH 4h
    │       ├── Reverse SuperTrend ETH 4h
    │       ├── Reverse SuperTrend Strategy
    │       ├── Reversed BarUpDn Strategy
    │       ├── Smart Money Concept - Uncle Sam
    │       ├── Smart Money Concepts Strategy [LuxAlgo] + Webhook', 'LuxAlgo - SMC Strategy'
    │       ├── Smart Money Concepts [LuxAlgo]
    │       ├── Smart Money Concepts [LuxAlgo] - Webhook'SMC-LuxAlgo-WH'
    │       ├── Squeeze Go Momentum Pro
    │       ├── Squeeze Go Pro
    │       ├── Squeeze Momentum
    │       ├── Squeeze Momentum Indicator [LazyBear]
    │       ├── Squeeze Momentum [LazyBear]
    │       ├── Squeeze vX [DGT]
    │       ├── Squeeze-Flow Expansion Hybrid
    │       ├── SuperTrend BTC 4h - Webhook
    │       ├── SuperTrend Fusion — ATP
    │       └── Supertrend
    ├── config
    │   └── settings.json
    ├── deploy
    │   ├── MIGRATION_README.md
    │   ├── README.md
    │   ├── deploy.sh
    │   ├── migrate-server.sh
    │   ├── nginx
    │   │   ├── tradingview_webhook.conf
    │   │   ├── webhook.conf
    │   │   ├── webhook_rate_limit.conf
    │   │   └── webhook_ssl_selfsigned.conf
    │   └── systemd
    │       ├── tv-engine.service
    │       └── tv-webhook.service
    ├── docs
    │   ├── FINAL_STATUS.md
    │   ├── LIQUIDATION_HEATMAP_BOT.md
    │   ├── LIQUIDATION_STRATEGY_DOCUMENTATION.md
    │   ├── PRD_TRADING_SYSTEMS_COMBINED.md
    │   ├── RENAME_COMPLETE.md
    │   ├── REORGANIZATION_PLAN.md
    │   ├── TRADINGVIEW_BOT_DOCUMENTATION.md
    │   └── reports
    │       ├── dlq_analysis_report.txt
    │       ├── requirements.txt
    │       └── safety_gate_report.txt
    ├── logs
    │   ├── orchestrator.log
    │   └── webhook.log
    ├── pytest.ini
    ├── scripts
    │   ├── RUNBOOK.md
    │   ├── analyze_7day.py
    │   ├── asset_scanner.py
    │   ├── backup_bot.sh
    │   ├── clean_dashboard_7tabs.py
    │   ├── clean_dashboard_tab7.py
    │   ├── db_setup.py
    │   ├── dlq_admin.py
    │   ├── dlq_inspector.py
    │   ├── dlq_replay.py
    │   ├── emergency_stop.sh
    │   ├── enable_trading.sh
    │   ├── generate_report.py
    │   ├── ingest_tv_export.py
    │   ├── kill_switch.py
    │   ├── ma_cross_checker.py
    │   ├── smoke_test_signal.py
    │   ├── strategy_health.py
    │   └── system_health_check.py
    ├── strategies
    │   ├── ema_sma_crossover_webhook.pine
    │   ├── enhanced_atr_supertrend_config.json
    │   ├── enhanced_atr_supertrend_webhook.pine
    │   ├── institutional_matrix_webhook.pine
    │   ├── lorentzian_classification_webhook.pine
    │   ├── obv_wavetrend_scalper_webhook.pine
    │   ├── sma_crossover_9_21_webhook.pine
    │   ├── squeeze_flow_expansion_webhook.pine
    │   └── supertrend_btc_4h_webhook.pine
    ├── tests
    │   ├── __init__.py
    │   ├── test_hardened_ledger.py
    │   ├── test_hardened_logic.py
    │   └── test_suite.py
    ├── tradingview_webhook_bot
    │   ├── README.md
    │   ├── RUNBOOK.md
    │   ├── __init__.py
    │   ├── alerts
    │   │   ├── __init__.py
    │   │   ├── email_notifier.py
    │   │   ├── router.py
    │   │   ├── telegram_alerts.py
    │   │   └── test_alerts.py
    │   ├── clean_dashboard_tab7.py
    │   ├── core
    │   │   ├── __init__.py
    │   │   ├── balance_manager.py
    │   │   ├── circuit_breaker.py
    │   │   ├── enhanced_order_manager.py
    │   │   ├── orchestrator.py
    │   │   ├── orchestrator.py.bak
    │   │   ├── order_monitor.py
    │   │   ├── position_manager.py
    │   │   ├── position_size_validator.py
    │   │   ├── reconciler.py
    │   │   ├── risk_manager.py
    │   │   ├── schemas.py
    │   │   ├── signal_processor.py
    │   │   ├── strategy_engine.py
    │   │   └── webhook_server.py
    │   ├── exchange
    │   │   ├── __init__.py
    │   │   ├── binance_client.py
    │   │   ├── enhanced_order_executor.py
    │   │   ├── execution_engine.py
    │   │   └── price_provider.py
    │   ├── ledger
    │   │   ├── __init__.py
    │   │   ├── positions.py
    │   │   └── test_ledger.py
    │   ├── logs
    │   │   ├── bot.log
    │   │   └── enhanced_bot.log
    │   ├── main_enhanced.py
    │   ├── recon
    │   │   ├── __init__.py
    │   │   ├── reconciler.py
    │   │   └── test_recon.py
    │   ├── requirements.txt
    │   ├── schemas.py
    │   ├── storage
    │   │   ├── __init__.py
    │   │   ├── alerts.jsonl
    │   │   ├── alerts.jsonl.1
    │   │   ├── dead_letter.jsonl
    │   │   ├── dead_letter.jsonl.1
    │   │   ├── dlq_archive_20260308_175623.jsonl
    │   │   ├── dlq_archive_20260308_175623.jsonl.1
    │   │   ├── idempotency.db
    │   │   ├── idempotency_store.py
    │   │   ├── jsonl_consumer.py
    │   │   ├── jsonl_queue.py
    │   │   ├── ledger_state.json
    │   │   ├── sheets_logger.py
    │   │   ├── signals.jsonl
    │   │   ├── signals.jsonl.1
    │   │   ├── signals.offset
    │   │   ├── stress_test_queue.py
    │   │   ├── test_storage.py
    │   │   └── trading_system.db
    │   ├── test_orchestrator.py
    │   ├── test_webhook_server.py
    │   ├── tests
    │   │   └── test_core.py
    │   ├── tradingview_webhook_server.py
    │   ├── update_institutional_flow_hybrid_dashboard.py
    │   ├── update_live_dashboard.py
    │   └── utils
    │       ├── __init__.py
    │       ├── client_order_id_generator.py
    │       ├── dashboard_updater.py
    │       ├── event_logger.py
    │       ├── health_checker.py
    │       ├── helpers.py
    │       ├── instance_lock.py
    │       ├── logger.py
    │       ├── position_reconciler.py
    │       ├── signal_archiver.py
    │       └── telegram_alerter.py
    └── wsgi.py

```

---

## 🚀 Quick Start

### Prerequisites

```bash
# System Requirements
- Ubuntu 22.04 LTS
- Python 3.12+
- Chrome/ChromeDriver (for scraping)
- Google Service Account (for Sheets API)
- Binance API keys (Testnet + Mainnet)
```

### Deployment

**1. Clone Repository:**
```bash
cd /home/ubuntu
git clone <repository_url>
cd Btc-Layer-Updated-files-main
```

**2. Install Dependencies:**
```bash
# Liquidation Bot
cd liquidation-heatmap-bot
pip3 install -r requirements.txt

# TradingView Bot
cd ../tradingview-only-bot
pip3 install -r requirements.txt
```

**3. Configure Environment:**
```bash
# Copy example config
cp .env.example .env

# Edit with your API keys
nano .env
```

**4. Start Systems:**
```bash
# Liquidation Bot
cd /home/ubuntu/tradingview-webhook-mvp/trading_bot
python3 -u enhanced_trading_bot.py

# TradingView Bots (systemd)
sudo systemctl start institutional-flow-hybrid.service
sudo systemctl start squeeze-flow-expansion.service
# ... (repeat for all strategies)
```

**5. Start Scrapers:**
```bash
# Visual Heatmap Scraper
cd /home/ubuntu/trading_bot
nohup xvfb-run python3 coinglass_visual_scraper.py > logs/scraper.log 2>&1 &

# OI/Funding Rate Loop
cd /home/ubuntu/tradingview-webhook-mvp/trading_bot
nohup bash run_oi_funding_loop.sh > logs/oi_funding.log 2>&1 &
```

---

## 📖 Documentation

### Core Documentation

📄 **[Product Requirements Document](PRD_TRADING_SYSTEMS_COMBINED.md)**  
Comprehensive PRD covering both trading systems, architecture, and roadmap.


📄 **[TradingView Bot Documentation](docs/TRADINGVIEW_BOT_DOCUMENTATION.md)**  
Full guide for TradingView webhook integration and multi-strategy setup.
### Setup Guides

- [HTTPS Setup Guide](HTTPS_SETUP_GUIDE.md)
- [Indicator Integration Format](INDICATOR_INTEGRATION_FORMAT.md)
- [Top 6 Indicators Setup](TOP_6_INDICATORS_SETUP_GUIDE.md)

### Strategy Guides

- [ATR Supertrend Setup](ATR_SUPERTREND_ALERT_SETUP_GUIDE.md)
- [EMA/SMA Crossover Setup](EMA_SMA_ALERT_SETUP_GUIDE.md)
- [Madrid Ribbon Setup](MADRID_RIBBON_ALERT_SETUP_GUIDE.md)
- [SMC LuxAlgo Setup](SMC_LUXALGO_SETUP_GUIDE.md)

---

## 🛠️ Key Technologies

**Programming:**
- Python 3.12 (asyncio, multiprocessing)
- Pine Script (TradingView indicators)

**Data Processing:**
- Pandas, NumPy (data analysis)
- Scikit-learn (DBSCAN clustering)
- gspread (Google Sheets API)

**Web Scraping:**
- Selenium + Chrome
- Xvfb (virtual display)
- undetected-chromedriver

**Trading:**
- Binance Futures API
- ccxt (exchange abstraction)

**Monitoring:**
- Google Sheets (real-time dashboards)
- systemd (process management)
- Custom event logging

**Infrastructure:**
- Ubuntu 22.04 LTS
- Nginx (webhook proxy)
- Cron (scheduled tasks)

---

## 📊 Performance Metrics

### Liquidation Heatmap Bot

### TradingView Webhook Bot

| Metric | Value |
|--------|-------|
| Active Strategies | 8 concurrent bots |
| Signal Latency | <500ms (webhook reception) |
| Order Execution | LIMIT orders (maker fees) |
| Balance Tracking | Virtual per-strategy |
| Uptime | 99%+ (systemd managed) |

---

## 🔐 Security

**API Keys:**
- ✅ Environment variables (.env)
- ✅ Testnet keys (no real funds)
- ✅ Mainnet read-only (price data)

**Webhook Security:**
- ✅ Secret token validation
- ✅ HTTPS (optional)
- ✅ IP restrictions (recommended)

**Risk Management:**
- ✅ Position size limits
- ✅ Maximum exposure controls
- ✅ Kill switch functionality
- ✅ Virtual balance safeguards

---

## 🤝 Support & Contact

**Server Access:**
```bash
ssh ubuntu@13.236.143.201
```

**Key Directories:**
- Liquidation Bot: `/home/ubuntu/tradingview-webhook-mvp/trading_bot/`
- TradingView Bot: `/home/ubuntu/tradingview-bot/`
- Logs: `/home/ubuntu/trading_bot/logs/`

**Monitoring:**
- Liquidation Bot Logs: `tail -f /home/ubuntu/tradingview-webhook-mvp/trading_bot/bot.log`
- Scraper Logs: `tail -f /home/ubuntu/trading_bot/logs/coinglass_scraper.log`
- OI/FR Logs: `tail -f /home/ubuntu/tradingview-webhook-mvp/trading_bot/logs/oi_funding_loop.log`

---

## 📝 Recent Updates

### February 18, 2026
- ✅ Fixed Chrome scraper infrastructure (Xvfb + file descriptors)
- ✅ Restored liquidation data pipeline (now analyzing current price $66K-$68K)
- ✅ Started OI/Funding Rate scraper loop (fresh data every 5 minutes)
- ✅ Resolved signal rejection issue (no longer "no OI/funding/LSR confirmation")
- ✅ Created comprehensive documentation (3 files, 100+ pages)
- ✅ Organized docs folder structure

---

## 📄 License

This project is proprietary and confidential. All rights reserved.

---

## 🎯 Roadmap

See [PRD_TRADING_SYSTEMS_COMBINED.md](PRD_TRADING_SYSTEMS_COMBINED.md) for detailed roadmap and feature planning.

**Upcoming Features:**
- [ ] Advanced ML-based signal filtering
- [ ] Multi-exchange support (OKX, Bybit)
- [ ] Automated backtesting framework
- [ ] Real-time Telegram notifications
- [ ] Web-based monitoring dashboard

---

**Built with ❤️ for algorithmic crypto trading**
