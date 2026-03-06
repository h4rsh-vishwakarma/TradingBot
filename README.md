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
trading-view-indicators/
│
├── 📄 README.md                          # This file
├── 📄 PRD_TRADING_SYSTEMS_COMBINED.md   # Product Requirements Document
├── 📄 REORGANIZATION_PLAN.md             # Reorganization documentation
│
├── 📁 docs/                              # Documentation
│   ├── LIQUIDATION_STRATEGY_DOCUMENTATION.md
│   ├── TRADINGVIEW_BOT_DOCUMENTATION.md
│   └── LIQUIDATION_HEATMAP_BOT.md
│
├── 📁 liquidation-heatmap-bot/           # Liquidation trading system
│   ├── bot_main.py
│   ├── signal_generator.py
│   ├── data_sources.py
│   ├── coinglass_visual_scraper.py
│   ├── config.py
│   ├── core/                             # Core modules
│   ├── observability/                    # Event logging & metrics
│   └── execution/                        # Trade execution
│
├── 📁 tradingview-webhook-bot/           # TradingView webhook system
│   ├── main_enhanced.py                  # Main entry point
│   ├── core/                             # Trading logic
│   │   ├── balance_manager.py            # Virtual balance tracking
│   │   ├── enhanced_order_manager.py     # Order execution
│   │   ├── order_monitor.py              # Order fill monitoring
│   │   ├── position_manager.py           # Position state
│   │   ├── position_size_validator.py    # Position size security
│   │   ├── risk_manager.py               # Risk calculations
│   │   ├── signal_processor.py           # Signal validation
│   │   ├── strategy_engine.py            # Strategy validation
│   │   ├── webhook_server.py             # Flask webhook receiver
│   │   └── circuit_breaker.py            # Circuit breaker logic
│   ├── exchange/                         # Exchange integration
│   │   ├── binance_client.py             # Binance API wrapper
│   │   ├── price_provider.py             # Mainnet price fetcher
│   │   ├── enhanced_order_executor.py    # Order execution
│   │   └── execution_engine.py           # Testnet execution
│   ├── utils/                            # Utility modules
│   │   ├── logger.py                     # Logging setup
│   │   ├── event_logger.py               # Event logging
│   │   ├── health_checker.py             # Health monitoring
│   │   ├── signal_archiver.py            # Signal queue cleanup
│   │   ├── dashboard_updater.py          # Metrics dashboard
│   │   ├── instance_lock.py              # Prevent duplicates
│   │   ├── client_order_id_generator.py  # Order ID generation
│   │   ├── position_reconciler.py        # Position reconciliation
│   │   ├── telegram_alerter.py           # Telegram notifications
│   │   └── helpers.py                    # Helper functions
│   ├── storage/                          # Persistent data
│   │   ├── idempotency_store.py          # Idempotency tracking
│   │   ├── jsonl_queue.py                # Signal queue
│   │   └── jsonl_consumer.py             # Queue consumer
│   └── alerts/                           # Alert system
│       └── telegram_alerts.py            # Telegram integration
│
├── 📁 strategies/                        # Pine Script indicators
│   ├── ema_sma_crossover_webhook.pine
│   ├── enhanced_atr_supertrend_webhook.pine
│   ├── institutional_matrix_webhook.pine
│   ├── lorentzian_classification_webhook.pine
│   ├── obv_wavetrend_scalper_webhook.pine
│   ├── sma_crossover_9_21_webhook.pine
│   ├── squeeze_flow_expansion_webhook.pine
│   └── supertrend_btc_4h_webhook.pine
│
├── 📁 scripts/                           # Utility scripts
│   ├── analyze_7day.py                   # 7-day analysis
│   ├── clean_dashboard_7tabs.py          # Dashboard cleanup
│   ├── clean_dashboard_tab7.py           # Dashboard cleanup
│   └── kill_switch.py                    # Emergency stop
│
├── 📁 config/                            # Strategy configurations
│   ├── config_institutional_flow_hybrid.json
│   ├── config_squeeze_flow_expansion.json
│   ├── config_supertrend_btc_4h.json
│   └── ...
│
├── 📁 deploy/                            # Deployment automation
│   ├── deploy.sh                         # Manual deployment script
│   └── nginx/                            # Nginx configurations
│
└── 📁 .github/
    └── workflows/
        └── deploy.yml                    # CI/CD deployment
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
