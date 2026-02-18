# Liquidation Heatmap Bot

Advanced cryptocurrency liquidation heatmap and liquidity analysis system for Bitcoin futures trading.

## Overview

This bot scrapes and analyzes liquidation data from multiple sources (Binance, Coinglass) to create real-time liquidation heatmaps with multiple timeframe servers. It provides critical liquidity insights for trading decisions.

## Core Components

### Data Scrapers
- **`binance_liquidity_scraper.py`** - Scrapes real-time liquidity data from Binance order book
- **`coinglass_lsr_scraper.py`** - Long/Short ratio scraper from Coinglass
- **`coinglass_visual_scraper.py`** - Visual liquidation heatmap data scraper

### Liquidity Heatmap Servers
- **`full_liquidity_7_1w_server.py`** - 1-week interval heatmap server
- **`full_liquidity_7_24.py`** - 24-hour interval heatmap
- **`full_liquidity_7_3d_server.py`** - 3-day interval heatmap server
- **`full_liquidity_7_48_server.py`** - 48-hour interval heatmap server
- **`full_liquidity_7_12.py`** - 12-hour interval heatmap
- **`full_liquidity_7_12_v2.py`** - Enhanced 12-hour version

### Core Modules

#### `/core`
- **`event_logger.py`** - Event logging and tracking
- **`reconciler.py`** - Data reconciliation between sources
- **`risk_controller.py`** - Risk management and position sizing

#### `/execution`
- **`executor.py`** - Order execution engine
- **`policies.py`** - Execution policies and rules
- **`router.py`** - Order routing logic

#### `/observability`
- **`emitters.py`** - Data emission to monitoring systems
- **`emitters_csv.py`** - CSV data export
- **`postgres_emitter.py`** - PostgreSQL data storage
- **`metrics_emitter.py`** - Metrics collection
- **`alert_rules.py`** - Alert configuration
- **`event_schemas.py`** - Event data structures
- **`stdout_json_logger.py`** - JSON logging
- **`opentelemetry_init.py`** - OpenTelemetry setup

#### `/config_manager`
- **`settings.py`** - Configuration management
- **`__init__.py`** - Module initialization

### Supporting Files
- **`bot_main.py`** - Main bot entry point
- **`config.py`** - Global configuration
- **`data_sources.py`** - Data source integrations
- **`feature_engineering.py`** - Feature extraction and ML preprocessing
- **`signal_generator.py`** - Trading signal generation based on liquidation data

## Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp config.py.example config.py
# Edit config.py with your API keys and settings
```

## Usage

### Start Heatmap Server (24-hour intervals)
```bash
python full_liquidity_7_24.py
```

### Start Data Scrapers
```bash
# Binance liquidity
python binance_liquidity_scraper.py

# Coinglass data
python coinglass_visual_scraper.py
```

### Run Main Bot
```bash
python bot_main.py
```

## Features

- **Real-time liquidation heatmap** across multiple timeframes
- **Multi-source data aggregation** (Binance + Coinglass)
- **Advanced risk management** with position sizing
- **Comprehensive observability** (Prometheus, PostgreSQL, CSV exports)
- **Signal generation** based on liquidation clustering
- **Event-driven architecture** with reconciliation

## Architecture

```
Data Sources (Binance, Coinglass)
    ↓
Scrapers (binance_liquidity_scraper, coinglass_visual_scraper)
    ↓
Feature Engineering (feature_engineering.py)
    ↓
Signal Generator (signal_generator.py)
    ↓
Risk Controller (core/risk_controller.py)
    ↓
Execution Engine (execution/executor.py)
    ↓
Observability (observability/emitters.py)
```

## Configuration

Key configuration options in `config.py`:
- API credentials (Binance, Coinglass)
- Scraping intervals
- Heatmap timeframes
- Risk management parameters
- Database connections
- Alert thresholds

## Monitoring

The system includes comprehensive monitoring:
- OpenTelemetry integration
- Prometheus metrics export
- PostgreSQL event storage
- CSV data exports
- JSON-structured logs
- Alert rules for anomalies

## Requirements

See `requirements.txt` for full dependencies. Key libraries:
- pandas, numpy - Data processing
- requests, aiohttp - HTTP clients
- selenium - Web scraping
- psycopg2 - PostgreSQL
- prometheus_client - Metrics
- opentelemetry - Observability

## Notes

- This system requires live access to Binance Futures and Coinglass
- Multiple heatmap servers can run simultaneously for different timeframes
- Data is reconciled across sources to ensure accuracy
- All execution goes through risk controller validation

## Synced From

Server: `ubuntu@13.236.143.201:/home/ubuntu/tradingview-webhook-mvp/trading_bot`
Date: February 18, 2026
