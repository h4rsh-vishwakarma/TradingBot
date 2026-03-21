# Backtesting & Strategy Tournament Engine

**Automated Strategy Validation, Optimization, and Ranking System**
**Version:** 2.0.0 | **Status:** Active | **Last Updated:** March 21, 2026

---

## Overview

The backtesting system validates trading strategies against 3 years of historical data, optimizes parameters via grid search, and ranks strategies by performance. Results feed directly into the live trading bot's decision engine -- only strategies that pass backtested validation (54%+ confidence) are allowed to execute trades.

**Key Capabilities:**
- 3-year high-resolution backtesting (15-minute candles)
- Grid-search parameter optimization (7 combinations per strategy)
- Hybrid scoring: 60% backtest + 40% live performance
- Automated daily tournament with Telegram reporting
- 100+ backtest CSVs across 38+ strategies and 3 symbols
- Direct integration with live Orchestrator for signal gating

---

## Pipeline Architecture

```
1. TOURNAMENT (strategy_tournament.py)
   Input: 38+ Pine strategies x 3 symbols x 3Y data
   Grid-Search: 7 parameter combos per strategy-symbol
   Output: tournament_winners.csv (114 entries ranked by ROI)
              |
              v
2. CSV GENERATION (generate_backtest_csvs.py)
   Input: tournament_winners.csv + 3Y data + optimal params
   Process: Apply strategies, calc trades, clip to -2%/+6%
   Output: 100+ CSVs in backtest_imports/ (per-trade PnL)
              |
              v
3. ENGINE VALIDATION (engine.py)
   Input: strategy_id + symbol + live ledger
   Process: Find matching CSV, calc WR & PF, hybrid score
   Output: (bool, confidence_score) for signal validation
              |
              v
4. LIVE TRADING (via orchestrator.py)
   Input: Webhook signal + validated confidence
   Action: Execute trade if confidence >= 54%
   Tracking: Log PnL to ledger for next cycle
```

---

## Core Components

### Backtesting Engine (`engine.py`)

The validation engine that scores strategy confidence before allowing live trades.

**Class: `BacktestEngine`**

**`get_strategy_confidence(strategy_id, symbol)`**
- Finds matching CSV via fuzzy filename matching
- Calculates **Win Rate** = winning trades / total trades
- Calculates **Profit Factor** = total_gains / |total_losses|
- Normalizes PF to 0-1 scale: `PF_score = 0.5 + (PF - 1.0) * 0.2` (capped at 0.95)
- Final score = `max(win_rate, pf_score)` -- allows trend strategies with <50% WR but high PF to pass

**`get_live_confidence(ledger)`**
- Scores based on recent 5-trade live performance
- Returns live win rate (0.0-1.0), default 0.6 if no data

**`validate_signal(strategy_id, symbol, ledger)`**
- Hybrid validation: `hybrid_score = (bt_confidence * 0.6) + (live_confidence * 0.4)`
- Returns `(True, score)` if `hybrid_score >= 0.54`, else `(False, score)`

**File Matching Logic:**
- Strategy name: Fuzzy match (removes spaces, underscores, dashes)
- Symbol: Match 3-letter base (BTC from BTCUSDT, ETH from ETHUSDT)
- Picks most recently modified matching file

---

### Strategy Tournament (`scripts/strategy_tournament.py`)

Runs backtests across all strategies and symbols, finds optimal parameters, ranks by ROI.

**Tournament Parameters:**

| Parameter | Value |
|-----------|-------|
| Lookback | 1095 days (3 years) |
| Resolution | 15-minute candles |
| Bars/Year | 35,040 |
| Leverage | 2.5x |
| Stop Loss | 2% (hard floor) |
| Take Profit | 6% (hard ceiling) |
| ADX Threshold | 25 (trend strength filter) |

**Grid Search (7 combinations):**

| Multiplier | 1.5 | 1.8 | 2.0 | 2.5 | 3.0 | 3.5 | 4.0 |
|------------|-----|-----|-----|-----|-----|-----|-----|
| Length | 7 | 9 | 11 | 14 | 18 | 21 | 26 |

**Metrics Calculated:**
- **Daily ROI %:** `(total_return_sum / 1095 days) * 100`
- **Gross DD %:** Peak-to-trough drawdown on equity curve (compounding)
- **Net DD %:** Non-compounding drawdown (cumulative sum)
- **Win Rate %:** Winning trades / total trades
- **Sharpe Ratio:** `(mean_ret / std_ret) * sqrt(35,040)` (annualized)
- **Total Trades:** Count of non-zero signals

**Performance Tiers:**

| Tier | Criteria | Action |
|------|----------|--------|
| ALPHA++ | Daily ROI >= 1.5% | Auto-execute in live trading |
| ALPHA | Daily ROI >= 0.5% | Auto-execute in live trading |
| AVERAGE | Daily ROI > 0.1% | Requires manual Telegram approval |
| REJECT | Daily ROI <= 0.1% | Blocked from live trading |

**Output:** `storage/reports/tournament_winners.csv` with 114 entries:
```
Symbol, Strategy, Daily_ROI_%, Gross_DD_%, Net_DD_%, Tier, Win_Rate_%, Sharpe_Ratio, Total_Trades, Optimal_Mult, Optimal_Len
```

---

### CSV Generation (`scripts/generate_backtest_csvs.py`)

Generates per-trade CSV files from tournament results for the validation engine.

**Workflow:**
1. Reads `tournament_winners.csv` (114 strategy-symbol combos)
2. For each entry:
   - Loads 3Y 15m data from `storage/backtest_data/{Symbol}_3y_15m.csv`
   - Applies strategy via `my_strategies.apply_strategy()`
   - Calculates ADX for signal filtering (>25 threshold)
   - Computes: `trade_ret = signal * pct_change * 2.5x leverage`
   - Clips to [-2%, +6%] bounds
3. Outputs CSV with columns: `Date, Price, Side, Profit`
4. Saves to `backtesting/A_Leaderboard/backtest_imports/`

**CSV Format:**
```csv
Date,Price,Side,Profit
2023-03-23 14:45:00,28043.6,Long,2.62
2023-03-23 15:00:00,28337.5,Long,1.2139
2023-03-24 11:45:00,27558.4,Short,-2.0
```

**Naming Convention:** `{CleanStrategyName}_{Symbol}USD_backtest.csv`

---

### Daily Alpha Check (`scripts/daily_alpha_check.py`)

Automated daily reporting of top-performing strategies.

**Workflow:**
1. Runs `strategy_tournament()` to regenerate tournament results
2. Reads top 5 strategies from tournament_winners.csv
3. Formats report with all metrics (ROI%, DD%, Win Rate%, Sharpe)
4. Sends to Telegram via `TelegramAlert` with HTML formatting

**Output Example:**
```
DAILY ALPHA REPORT
#1 ALPHA++ | SOLUSDT
   OPTIMIZED_SOLUSDT.txt
   ROI: 2.588%/day
   Gross DD: -65.22% | Net DD: -96.76%
   Win: 49.4% | Sharpe: 5.71
```

---

### Strategy Implementations (`scripts/my_strategies.py`)

Dynamically applies trading logic based on strategy name patterns.

| Category | Keywords | Logic |
|----------|----------|-------|
| **Trend Following** | SUPERTREND, ATR, SMA, EMA, RIBBON, CROSS | ATR-based breakout with EMA200 filter |
| **Mean Reversion/ML** | SQUEEZE, REVERSION, LORENTZIAN, ML, MATRIX | Bollinger-band style (mean +/- mult*std) |
| **Volume & Momentum** | OBV, WAVETREND, MACD, MOMENTUM, FLOW | OBV with trend filter, ADX > 18 |
| **SMC & Liquidity** | SMC, LIQUIDITY, INSTITUTIONAL | Price breakout over lookback period |

Common filters: 14-period ADX calculation, optimization entropy for unique trades.

---

### Leaderboard Ingestion (`A_Leaderboard/`)

**`ingest_csv.py`** -- Parses TradingView backtest CSVs and stores metrics in SQLite:
- Calculates: net profit, profit factor, win rate, max drawdown, sharpe ratio
- Handles multiple encodings (UTF-8, UTF-16, CP1252)
- Upserts to `metrics` table with ON CONFLICT handling

**`report.py`** -- Generates formatted leaderboard:
- Star rating system (1-3 stars based on Sharpe & Profit Factor)
- Key insights: Highest Sharpe, Win Rate, Lowest DD
- Formatted console output

---

## Strategies Library

38+ Pine Script strategies in `pine/` directory:

| Category | Strategies |
|----------|-----------|
| **Supertrend** | ATR Supertrend [QuantAlgo], Enhanced ATR Supertrend, SuperTrend BTC 4h, SuperTrend Fusion ATP, Reverse SuperTrend |
| **Moving Average** | EMA-SMA Crossover, EMA 9by15, Madrid Ribbon, Reverse Madrid Ribbon, Oppsite SMA, SMA 9 Cross |
| **Squeeze/Momentum** | Squeeze Go Pro, Squeeze Go Momentum Pro, Squeeze Flow Expansion, Squeeze Momentum [LazyBear], Squeeze vX [DGT], MVO Momentum Variance |
| **Smart Money** | SMC Strategy [LuxAlgo], Smart Money Concepts, Smart Money Concept Uncle Sam, Hybrid SMC [MarkitTick] |
| **ML/Advanced** | ML Lorentzian Classification, Machine Learning Lorentzian, Institutional Flow Hybrid, Hackathon V3 Institutional Matrix |
| **Volume** | OBV + WaveTrend Volume Scalper, Mean Reversion Scalper Hybrid |
| **Reversal** | Reverse Liquidity Trap, Reversed BarUpDn |

---

## Data

### Historical Data (`storage/backtest_data/`)

| File | Size | Description |
|------|------|-------------|
| `BTCUSDT_3y_15m.csv` | ~6.2M | 3 years of 15m OHLCV |
| `ETHUSDT_3y_15m.csv` | ~6.1M | 3 years of 15m OHLCV |
| `SOLUSDT_3y_15m.csv` | ~5.7M | 3 years of 15m OHLCV |
| `BTCUSDT_1y_15m.csv` | ~2.2M | 1 year of 15m OHLCV |
| `ETHUSDT_1y_15m.csv` | ~2.1M | 1 year of 15m OHLCV |
| `SOLUSDT_1y_15m.csv` | ~2.2M | 1 year of 15m OHLCV |

### Backtest Imports (`A_Leaderboard/backtest_imports/`)

100+ CSV files containing per-trade P&L data for each strategy-symbol combination.

### Reports (`storage/reports/`)

| File | Description |
|------|-------------|
| `tournament_winners.csv` | 114 ranked strategies with all metrics |
| `alpha_leaderboard.csv` | Alternative leaderboard format |
| `push_log.txt` | Deployment logs |

---

## Database

**Location:** `backtesting/db.sqlite3`

```sql
CREATE TABLE metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_name TEXT UNIQUE,
    net_profit REAL,
    profit_factor REAL,
    win_rate REAL,
    max_dd REAL,
    sharpe REAL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_updated TIMESTAMP
);
```

---

## Configuration & Parameters

### Engine Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| Min Win Rate | 54% | Validation threshold |
| BT Weight | 60% | Hybrid scoring weight for backtest |
| Live Weight | 40% | Hybrid scoring weight for live trades |
| PF Normalization | `0.5 + (PF-1.0)*0.2` | Profit factor to 0-1 scale, max 0.95 |
| Default Live Conf | 0.6 | When no live data available |
| Default BT Conf | 0.51 | When no CSV match found |

### Tournament Grid

| Parameter | Range |
|-----------|-------|
| Multiplier | 1.5, 1.8, 2.0, 2.5, 3.0, 3.5, 4.0 |
| Length | 7, 9, 11, 14, 18, 21, 26 |

---

## Automation

### Cron Schedule (24h Cycle)

1. **Data Fetch** -- Download 3Y OHLCV for BTCUSDT, ETHUSDT, SOLUSDT
2. **Tournament** -- Grid-search optimization across all strategies
3. **CSV Generation** -- Per-trade validation data from optimal parameters
4. **Alpha Report** -- Daily Telegram notification with top performers

Configuration: `setup_cron.sh`, logs in `cron_logs.log`

---

## Integration with Live Trading

The backtesting system integrates with the live Orchestrator through:

1. **Tournament Winners CSV** -- Orchestrator reads tier information (ALPHA/AVERAGE/REJECT) from `tournament_winners.csv` to gate incoming signals
2. **Engine Validation** -- Orchestrator calls `BacktestEngine.validate_signal()` for confidence scoring before executing any trade
3. **Script Vault** -- Uses tournament rankings to auto-generate and deploy Pine Scripts for top strategies
4. **Daily Alpha Command** -- Telegram `/alpha` command triggers tournament re-run and deploys winners

---

## Usage

### Run Tournament
```bash
cd /home/ubuntu/tradingview_webhook_bot
python3 scripts/strategy_tournament.py
```

### Generate Backtest CSVs
```bash
python3 scripts/generate_backtest_csvs.py
```

### Run Daily Alpha Check
```bash
python3 scripts/daily_alpha_check.py
```

### Ingest TradingView CSV Export
```bash
python3 backtesting/A_Leaderboard/ingest_csv.py path/to/export.csv
```

### View Leaderboard Report
```bash
python3 backtesting/A_Leaderboard/report.py
```

### Validate a Strategy Manually
```python
from backtesting.engine import BacktestEngine

engine = BacktestEngine()
confidence = engine.get_strategy_confidence("squeeze_flow_expansion", "BTCUSDT")
print(f"Confidence: {confidence:.2%}")
```

---

## Error Handling

| Scenario | Fallback |
|----------|----------|
| Missing CSV | Returns confidence = 0.51 (just above threshold) |
| No PnL column found | Returns 0.5 |
| Live ledger missing | Uses default confidence 0.6 |
| Strategy match failure | Logs warning, returns None |
| Tournament error | Returns (-1, -1, -1, 0.0, 0.0, 0, "REJECT") |
| Memory pressure | Garbage collection after each strategy run |

---

## File Structure

```
backtesting/
|-- engine.py                      # Core validation engine
|-- db.sqlite3                     # Metrics SQLite database
|-- __init__.py                    # Package init
|-- A_Leaderboard/
|   |-- ingest_csv.py              # CSV ingestion to SQLite
|   |-- report.py                  # Leaderboard report generator
|   `-- backtest_imports/          # 100+ per-trade CSV files
|       |-- ATR_Supertrend_QuantAlgo_BTCUSD_backtest.csv
|       |-- Squeeze_Flow_Expansion_BTCUSD_backtest.csv
|       `-- ...
|-- core/
|   |-- init_db.py                 # Database initialization
|   |-- add_last_updated.py        # Schema migration
|   `-- schemas/
|       `-- event_schema_v1.json   # Event schema definition
|-- pine/                          # 38+ Pine Script strategy files
|   |-- ATR Supertrend [QuantAlgo]
|   |-- Squeeze Go Pro
|   |-- Smart Money Concepts [LuxAlgo]
|   `-- ...
`-- data/                          # Additional data storage

Related scripts (in scripts/):
|-- strategy_tournament.py         # Tournament runner
|-- generate_backtest_csvs.py      # CSV generator
|-- daily_alpha_check.py           # Daily reporting
|-- my_strategies.py               # Strategy implementations
`-- auto_injector.py               # Auto Pine Script generation
```

---

**Developed by:** Harsh
**License:** Proprietary and confidential. All rights reserved.
