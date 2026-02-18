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

### 1. Liquidation Heatmap Bot

**Strategy:** Identifies and trades liquidation clusters using multi-source data aggregation.

**Key Features:**
- ✅ Real-time liquidation heatmap scraping (Coinglass)
- ✅ Multi-timeframe cluster detection (12h, 24h, 48h, 3d, 1week)
- ✅ DBSCAN clustering algorithm for density analysis
- ✅ Open Interest + Funding Rate + LSR confirmation
- ✅ 5-layer signal validation system
- ✅ Advanced R-based position sizing

**Performance:**
- Current BTC Price Analysis: $66,423 - $68,210 ✅
- Data Points: 428 liquidation levels across 5 timeframes
- Clusters Detected: 10 major liquidation zones
- Signal Generation: Active with fresh OI/FR/LSR data

**Location:** `/home/ubuntu/tradingview-webhook-mvp/trading_bot/`

📖 **[Read Full Documentation →](docs/LIQUIDATION_STRATEGY_DOCUMENTATION.md)**

---

### 2. TradingView Webhook Bot

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
📖 **[Liquidation Heatmap Bot Details →](docs/LIQUIDATION_HEATMAP_BOT.md)**

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
Btc-Layer-Updated-files-main/
│
├── 📄 README.md                          # This file
├── 📄 PRD_TRADING_SYSTEMS_COMBINED.md   # Product Requirements Document
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
│   └── core/
│
├── 📁 tradingview-only-bot/              # TradingView webhook system
│   ├── main_enhanced.py
│   ├── signal_processor.py
│   ├── execution_engine.py
│   ├── risk_controller.py
│   └── config/
│
├── 📁 config/                            # Strategy configurations
│   ├── config_institutional_flow_hybrid.json
│   ├── config_squeeze_flow_expansion.json
│   ├── config_supertrend_btc_4h.json
│   └── ...
│
├── 📁 scripts/                           # Utility scripts
├── 📁 strategies/                        # Pine Script indicators
└── 📁 deploy/                            # Deployment automation
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

📄 **[Liquidation Strategy Documentation](docs/LIQUIDATION_STRATEGY_DOCUMENTATION.md)**  
Complete technical documentation for liquidation heatmap trading bot.

📄 **[TradingView Bot Documentation](docs/TRADINGVIEW_BOT_DOCUMENTATION.md)**  
Full guide for TradingView webhook integration and multi-strategy setup.

📄 **[Liquidation Heatmap Bot Details](docs/LIQUIDATION_HEATMAP_BOT.md)**  
Component breakdown and architecture of liquidation bot system.

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

| Metric | Value |
|--------|-------|
| Data Sources | 3 (Coinglass, Binance OI, Binance FR) |
| Liquidation Points | 428 across 5 timeframes |
| Clusters Detected | 10 major zones |
| Signal Validation Layers | 5 (cluster + OI + FR + LSR + multi-TF) |
| Current Status | ✅ Signals generating |

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
