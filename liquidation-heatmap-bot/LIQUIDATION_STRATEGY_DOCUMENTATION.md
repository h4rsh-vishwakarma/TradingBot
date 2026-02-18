# 🔥 Liquidation Heatmap Trading Strategy - Technical Documentation
**Project:** BTC Liquidation Cluster Trading Bot  
**Created:** February 18, 2026  
**Server:** ubuntu@13.236.143.201  
**Location:** `/home/ubuntu/tradingview-webhook-mvp/trading_bot/`

---

## 📚 Table of Contents
1. [Strategy Overview](#strategy-overview)
2. [How Liquidation Strategy Works](#how-liquidation-strategy-works)
3. [System Architecture](#system-architecture)
4. [Data Flow](#data-flow)
5. [Signal Generation Process](#signal-generation-process)
6. [Trade Execution Logic](#trade-execution-logic)
7. [Configuration & Parameters](#configuration--parameters)
8. [File Structure](#file-structure)
9. [Monitoring & Observability](#monitoring--observability)
10. [Risk Management](#risk-management)
11. [Setup & Deployment](#setup--deployment)

---

## 🎯 Strategy Overview

### What is Liquidation Cluster Trading?

The liquidation heatmap strategy identifies **clusters of liquidation levels** in the Bitcoin futures market and waits for price to approach these zones. When combined with directional confirmation from Open Interest, Funding Rate, and Long/Short Ratio data, the bot executes trades anticipating a price reaction at these liquidation-dense areas.

### Core Concept

Liquidation events create cascading effects:
- **Large liquidation clusters** act as magnets (price tends to move toward them)
- **When price reaches clusters** → Liquidations trigger → Price volatility increases
- **After liquidations execute** → Price often reverses or accelerates

### Trading Logic

```
IF:
  1. Price approaches high-density liquidation cluster (within 2-5%)
  2. Open Interest shows directional bias (longs/shorts building)
  3. Funding rate confirms pressure (longs paying shorts or vice versa)
  4. Long/Short ratio is imbalanced (one side overexposed)
  5. Market regime is trending (not ranging/choppy)

THEN:
  Execute trade in direction toward the cluster
  Set stop-loss beyond cluster
  Target take-profit before major reversal zones
```

---

## 🔥 How Liquidation Strategy Works

### 1. Liquidation Heatmap Data Collection

**Data Source:** Google Sheets (populated by external scrapers)

**Timeframes Analyzed:**
- **12 hours:** Short-term liquidation zones
- **24 hours:** Intraday clusters
- **48 hours:** 2-day liquidation buildup
- **3 days:** Multi-day accumulation
- **1 week:** Weekly liquidation zones

**Data Points Per Cycle:**
- ~334 liquidation price levels across all timeframes
- Each includes: `price`, `liquidation_amount`, `type` (LONG/SHORT), `leverage`, `distance_pct`

### 2. Cluster Detection Algorithm

**Method:** DBSCAN (Density-Based Spatial Clustering)

**Parameters:**
```python
cluster_width_threshold: 0.003  # 0.3% price width
min_cluster_points: 2           # Minimum 2 liquidation levels
cluster_density_threshold: 50000 # $50,000 minimum liquidations
```

**Process:**
1. Merge all liquidation data from 5 timeframes
2. Normalize prices and liquidation values
3. Apply DBSCAN clustering to identify dense zones
4. Filter clusters by minimum density ($50K threshold)
5. Classify clusters as "above price" or "below price"

**Output:**
- ~11 major liquidation clusters detected
- Each cluster has: `center_price`, `density`, `width`, `strength`, `distance_from_current_price`

### 3. Multi-Signal Voting System

The bot uses a **3-method voting system** to generate reliable signals:

**Method 1 (m1): Trend Following**
- Multi-timeframe trend analysis (5m, 15m, 1h, 4h, 1d)
- Uses EMA crossovers and momentum indicators
- Outputs: LONG, SHORT, or NEUTRAL

**Method 2 (m2): Liquidation Cluster Analysis**
- Checks if price is near high-density cluster
- Calculates cluster strength and distance
- Direction: Toward the nearest strong cluster

**Method 3 (m3): Market Sentiment**
- **Open Interest (OI):** Growing OI = Directional conviction
- **Funding Rate (FR):** Positive FR = Longs paying shorts (bearish pressure)
- **Long/Short Ratio (LSR):** High ratio = Too many longs (liquidation cascade risk)

**Voting Logic:**
```python
if m1 == m2 == SHORT:  # Strong agreement
    signal = SHORT
elif m2 == SHORT and m3 == SHORT:  # Cluster + sentiment
    signal = SHORT
elif m1 == m2 == LONG:
    signal = LONG
elif m2 == LONG and m3 == LONG:
    signal = LONG
else:
    signal = REJECTED  # Insufficient confirmation
```

### 4. Signal Validation Layers

**Before executing any trade, signal must pass ALL checks:**

#### Layer 1: Data Freshness ✅
```python
price_age < 120s        # Real-time price (2 min max)
heatmap_age < 900s      # Liquidation data (15 min max)
oi_age < 900s           # Open Interest (15 min max)
funding_age < 900s      # Funding rate (15 min max)
```

#### Layer 2: Cluster Validation ✅
```python
cluster_density > $50,000       # Minimum liquidation size
cluster_distance < 5%           # Not too far from price
cluster_width < 1%              # Tight, focused cluster
min_cluster_points >= 2         # Multiple liquidation levels
```

#### Layer 3: Sentiment Confirmation ✅
```python
# At least ONE must confirm direction:
OI_change > 3%          # Strong directional flow
OR funding_rate > 0.05% # Extreme funding pressure
OR lsr_ratio > 2.0      # Major imbalance
```

#### Layer 4: Market Regime Filter ✅
```python
# Market must be trending (not ranging):
regime in ['TRENDING_UP', 'TRENDING_DOWN', 'HIGH_VOL']
# NOT: 'RANGING', 'LOW_VOL', 'SIDEWAYS'
```

#### Layer 5: Risk Management ✅
```python
daily_risk_used < 2%    # Daily loss cap not hit
positions_open < 3      # Max concurrent positions
kill_switch == False    # Emergency stop not active
```

### 5. Trade Execution

**When ALL validation layers pass:**

```python
# Position Sizing
position_size = balance * 0.015  # 1.5% of balance
position_size_btc = position_size / current_price

# Stop-Loss Calculation
atr = calculate_atr(14_period)
stop_distance = atr * 1.5  # 1.5x ATR

if signal == SHORT:
    entry_price = current_price
    stop_loss = entry_price + stop_distance
    take_profit = entry_price - (stop_distance * 2.5)  # 2.5x reward
    
# Execute on Binance
order = binance.create_market_order(
    symbol='BTCUSDT',
    side='SELL',
    amount=position_size_btc
)

# Set stop-loss and take-profit
binance.set_stop_loss(stop_loss)
binance.set_take_profit(take_profit)

# Log to emitters
log_order(order)
log_decision(signal_details)
```

---

## 🏗️ System Architecture

### Component Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    GOOGLE SHEETS                         │
│  (Liquidation Data - 5 timeframes: 12h,24h,48h,3d,1w)   │
└─────────────────┬───────────────────────────────────────┘
                  │
                  │ Google Sheets API (credentials.json)
                  ↓
┌─────────────────────────────────────────────────────────┐
│         EnhancedGoogleSheetsClient                       │
│  - Rotate credentials (quota management)                 │
│  - Fetch liquidation heatmap                             │
│  - Fetch Open Interest data                              │
│  - Fetch Funding Rate data                               │
└─────────────────┬───────────────────────────────────────┘
                  │
                  ↓
┌─────────────────────────────────────────────────────────┐
│         EnhancedRLSignalGenerator (Core Engine)          │
│                                                           │
│  ┌─────────────────────────────────────────────────┐   │
│  │ 1. Data Loading (async thread)                   │   │
│  │    - Load liquidation heatmap every 60s          │   │
│  │    - Merge 5 timeframes → 334 data points        │   │
│  └─────────────────────────────────────────────────┘   │
│                                                           │
│  ┌─────────────────────────────────────────────────┐   │
│  │ 2. Cluster Detection (DBSCAN)                    │   │
│  │    - Identify ~11 major clusters                 │   │
│  │    - Calculate density, strength, distance       │   │
│  └─────────────────────────────────────────────────┘   │
│                                                           │
│  ┌─────────────────────────────────────────────────┐   │
│  │ 3. Signal Generation (check_for_enhanced_signals)│   │
│  │    - Run every 60 seconds                        │   │
│  │    - Multi-timeframe trend analysis              │   │
│  │    - OI/FR/LSR sentiment analysis                │   │
│  │    - 3-method voting system                      │   │
│  └─────────────────────────────────────────────────┘   │
│                                                           │
│  ┌─────────────────────────────────────────────────┐   │
│  │ 4. Validation & Risk Checks                      │   │
│  │    - Data staleness checks                       │   │
│  │    - Daily risk cap (2% max loss)                │   │
│  │    - Position limits (max 3 concurrent)          │   │
│  │    - Kill switch monitoring                      │   │
│  └─────────────────────────────────────────────────┘   │
│                                                           │
└─────────────────┬───────────────────────────────────────┘
                  │
                  ↓
┌─────────────────────────────────────────────────────────┐
│         BinanceFuturesAdapter                            │
│  - Binance testnet connection                            │
│  - WebSocket price feed (real-time)                      │
│  - REST API for order execution                          │
│  - Position management                                   │
└─────────────────┬───────────────────────────────────────┘
                  │
                  ↓
┌─────────────────────────────────────────────────────────┐
│         BINANCE FUTURES TESTNET                          │
│  - Execute MARKET orders                                 │
│  - Set stop-loss / take-profit                           │
│  - Real-time position tracking                           │
└─────────────────────────────────────────────────────────┘

                  │
                  ↓ Logging
                  
┌─────────────────────────────────────────────────────────┐
│         Observability Emitters                           │
│  - decision.jsonl (signal decisions)                     │
│  - order.jsonl (order executions)                        │
│  - fill.jsonl (trade fills)                              │
│  - health.jsonl (heartbeat every 60s)                    │
│  - error.jsonl (errors and exceptions)                   │
│  - CSV exports (analytics)                               │
└─────────────────────────────────────────────────────────┘
```

### Data Flow Sequence

```
1. [Every 60 seconds] Data Refresh Cycle Starts
   ↓
2. Google Sheets Client fetches liquidation data (5 timeframes)
   ↓
3. Signal Generator receives 334 liquidation levels
   ↓
4. DBSCAN clustering identifies 11 major clusters
   ↓
5. Calculate cluster properties (density, distance, strength)
   ↓
6. Binance WebSocket provides current BTC price
   ↓
7. Check if price is near any high-density cluster
   ↓
8. IF near cluster:
   ├─ Fetch Open Interest data
   ├─ Fetch Funding Rate data
   ├─ Fetch Long/Short Ratio data
   ├─ Run multi-timeframe trend analysis
   └─ Calculate 3-method voting
   ↓
9. IF voting produces signal (LONG/SHORT):
   ├─ Validate data freshness
   ├─ Check market regime (trending?)
   ├─ Verify sentiment confirmation (OI/FR/LSR)
   ├─ Check risk limits (daily cap, positions)
   └─ Calculate position size & stops
   ↓
10. IF all validations pass:
    ├─ Execute MARKET order on Binance
    ├─ Set stop-loss order
    ├─ Set take-profit order
    ├─ Log to decision.jsonl
    ├─ Log to order.jsonl
    └─ Update health.jsonl
    ↓
11. IF validation fails:
    ├─ Log rejection reason
    └─ Wait for next cycle (60s)
    ↓
12. Emit health heartbeat
    ↓
13. Sleep until next cycle
```

---

## 📊 Data Flow

### Input Data Sources

#### 1. Liquidation Heatmap (Google Sheets)

**Spreadsheet Structure:**
```
Sheet: "12h" / "24h" / "48h" / "3d" / "1week"
Columns:
  - price: Liquidation price level
  - liquidation: Total USD value of liquidations
  - type: LONG or SHORT
  - leverage: 5x, 10x, 25x, 50x, 100x
  - distance_pct: Distance from current price (%)
  - timestamp: Data collection time
```

**Example Data:**
```json
{
  "price": 96500.00,
  "liquidation": 477198.36,
  "type": "SHORT",
  "leverage": "25x",
  "distance_pct": 2.01,
  "timestamp": "2026-02-18T06:00:00Z"
}
```

**Update Frequency:** Every 5-15 minutes (external scraper)

#### 2. Open Interest (Google Sheets)

**Purpose:** Measure market participation and directional conviction

**Key Metrics:**
- `oi_value`: Total open interest in USD
- `oi_change_pct`: % change in last hour
- `price_change_pct`: BTC price change in last hour

**Signal Interpretation:**
```
OI ↑ + Price ↑ = BULLISH (longs opening)
OI ↑ + Price ↓ = BEARISH (shorts opening)
OI ↓ + Price ↑ = WEAK (longs closing)
OI ↓ + Price ↓ = WEAK (shorts closing)
```

#### 3. Funding Rate (Google Sheets)

**Purpose:** Measure long/short pressure in perpetual futures

**Key Metrics:**
- `funding_rate`: Current 8-hour funding rate
- `timestamp`: Last funding time

**Signal Interpretation:**
```
Funding > +0.05%  = BEARISH (longs paying shorts, overpriced)
Funding < -0.05%  = BULLISH (shorts paying longs, underpriced)
Funding ≈ 0%      = NEUTRAL (balanced market)
```

#### 4. Long/Short Ratio (Google Sheets)

**Purpose:** Measure trader positioning imbalance

**Key Metrics:**
- `lsr_ratio`: Ratio of long positions to short positions

**Signal Interpretation:**
```
LSR > 2.0  = BEARISH (too many longs, liquidation cascade risk)
LSR < 0.5  = BULLISH (too many shorts, short squeeze risk)
LSR ≈ 1.0  = NEUTRAL (balanced positioning)
```

#### 5. Real-Time Price (Binance WebSocket)

**Purpose:** Sub-second price updates for accurate execution

**Connection:** `wss://fstream.binance.com/ws/btcusdt@aggTrade`

**Data:**
```json
{
  "symbol": "BTCUSDT",
  "price": 67805.90,
  "timestamp": 1708241715772
}
```

---

## 🎯 Signal Generation Process

### Main Function: `check_for_enhanced_signals()`

**Execution Frequency:** Every 60 seconds

### Step-by-Step Process

#### Step 1: Pre-Flight Checks
```python
# Data freshness validation
if price_age > 120s:
    return None  # Price too stale
    
if heatmap_age > 900s:
    return None  # Liquidation data too old
    
# Kill switch check
if kill_switch_active:
    return None  # Emergency stop engaged
    
# Position limit check
if positions_open >= max_concurrent_positions:
    return None  # Too many open trades
```

#### Step 2: Liquidation Cluster Analysis
```python
# Find clusters near current price
clusters = identify_clusters(liquidation_data)
# Returns: 11 clusters with properties

above_clusters = [c for c in clusters if c.price > current_price]
below_clusters = [c for c in clusters if c.price < current_price]

# Find strongest cluster within 5% distance
target_cluster = None
for cluster in above_clusters:
    if cluster.distance_pct < 5.0 and cluster.density > 50000:
        if not target_cluster or cluster.density > target_cluster.density:
            target_cluster = cluster
            signal_direction = 'SHORT'  # Price likely moves toward cluster
```

#### Step 3: Multi-Timeframe Trend Analysis (Method 1)
```python
timeframes = ['5m', '15m', '1h', '4h', '1d']
trends = {}

for tf in timeframes:
    candles = fetch_candles(tf, limit=100)
    
    # Calculate indicators
    ema_fast = EMA(candles, period=8)
    ema_slow = EMA(candles, period=21)
    rsi = RSI(candles, period=14)
    
    # Trend scoring
    if ema_fast > ema_slow and rsi > 50:
        trends[tf] = +1.0  # Bullish
    elif ema_fast < ema_slow and rsi < 50:
        trends[tf] = -1.0  # Bearish
    else:
        trends[tf] = 0.0   # Neutral

# Weighted average (higher timeframes weighted more)
weights = {'5m': 0.1, '15m': 0.2, '1h': 0.3, '4h': 0.25, '1d': 0.15}
overall_trend = sum(trends[tf] * weights[tf] for tf in timeframes)

method_1_signal = 'LONG' if overall_trend > 0.3 else 'SHORT' if overall_trend < -0.3 else 'NEUTRAL'
```

#### Step 4: Market Sentiment Analysis (Method 3)
```python
# Open Interest signal
oi_change_pct = (current_oi - prev_oi) / prev_oi * 100
price_change_pct = (current_price - prev_price) / prev_price * 100

if oi_change_pct > 3 and price_change_pct > 0:
    oi_signal = 'LONG'   # Longs opening
elif oi_change_pct > 3 and price_change_pct < 0:
    oi_signal = 'SHORT'  # Shorts opening
else:
    oi_signal = 'NEUTRAL'

# Funding Rate signal
if funding_rate > 0.05:
    fr_signal = 'SHORT'  # Longs overheated
elif funding_rate < -0.05:
    fr_signal = 'LONG'   # Shorts overheated
else:
    fr_signal = 'NEUTRAL'

# Long/Short Ratio signal
if lsr_ratio > 2.0:
    lsr_signal = 'SHORT'  # Too many longs
elif lsr_ratio < 0.5:
    lsr_signal = 'LONG'   # Too many shorts
else:
    lsr_signal = 'NEUTRAL'

# Aggregate sentiment
sentiment_votes = [oi_signal, fr_signal, lsr_signal]
if sentiment_votes.count('SHORT') >= 2:
    method_3_signal = 'SHORT'
elif sentiment_votes.count('LONG') >= 2:
    method_3_signal = 'LONG'
else:
    method_3_signal = 'NEUTRAL'
```

#### Step 5: 3-Method Voting
```python
# Method 2 is cluster-based signal from Step 2
votes = {
    'm1': method_1_signal,  # Trend following
    'm2': signal_direction,  # Cluster direction (SHORT if above)
    'm3': method_3_signal    # Sentiment
}

# Voting logic
if votes['m1'] == votes['m2'] == 'SHORT':
    final_signal = 'SHORT'
elif votes['m2'] == 'SHORT' and votes['m3'] == 'SHORT':
    final_signal = 'SHORT'
elif votes['m1'] == votes['m2'] == 'LONG':
    final_signal = 'LONG'
elif votes['m2'] == 'LONG' and votes['m3'] == 'LONG':
    final_signal = 'LONG'
else:
    final_signal = 'REJECTED'
    reason = "Only cluster votes with NEUTRAL sentiment (no OI/funding/LSR confirmation)"
```

#### Step 6: Market Regime Check
```python
# Calculate market regime
volatility = calculate_volatility(candles_1h, period=20)
trend_strength = abs(overall_trend)

if trend_strength > 0.5 and volatility > avg_volatility * 1.5:
    regime = 'HIGH_VOL'  # ✅ Can trade
elif trend_strength > 0.4:
    regime = 'TRENDING_UP' if overall_trend > 0 else 'TRENDING_DOWN'  # ✅ Can trade
elif volatility < avg_volatility * 0.5:
    regime = 'LOW_VOL'  # ❌ Cannot trade
else:
    regime = 'RANGING'  # ❌ Cannot trade (choppy)

if regime not in ['TRENDING_UP', 'TRENDING_DOWN', 'HIGH_VOL']:
    final_signal = 'REJECTED'
    reason = f"Market regime {regime} not suitable for trading"
```

#### Step 7: Final Validation & Execution
```python
if final_signal in ['LONG', 'SHORT']:
    # Calculate position size
    risk_per_trade = balance * 0.015  # 1.5%
    atr = calculate_atr(candles_1h, period=14)
    
    if final_signal == 'SHORT':
        entry_price = current_price
        stop_loss = entry_price + (atr * 1.5)
        take_profit = entry_price - (atr * 2.5)
    else:
        entry_price = current_price
        stop_loss = entry_price - (atr * 1.5)
        take_profit = entry_price + (atr * 2.5)
    
    position_size_btc = risk_per_trade / (entry_price - stop_loss)
    
    # Execute trade
    order = execute_trade(
        side=final_signal,
        size=position_size_btc,
        stop_loss=stop_loss,
        take_profit=take_profit
    )
    
    # Log decision
    log_decision({
        'signal': final_signal,
        'cluster': target_cluster,
        'votes': votes,
        'regime': regime,
        'entry': entry_price,
        'stop': stop_loss,
        'tp': take_profit
    })
else:
    log_decision({
        'signal': 'REJECTED',
        'reason': reason,
        'votes': votes
    })
```

---

## 💼 Trade Execution Logic

### Order Types Used

#### 1. Entry Order: MARKET Order
```python
# Execute immediately at best available price
order = binance.create_market_order(
    symbol='BTCUSDT',
    side='BUY' or 'SELL',
    amount=position_size_btc
)
```

**Why MARKET?**
- Guarantees execution
- Minimal slippage in BTC futures (high liquidity)
- Speed critical when price near liquidation cluster

#### 2. Stop-Loss: STOP_MARKET Order
```python
# Triggered when price reaches stop level
stop_order = binance.create_order(
    symbol='BTCUSDT',
    type='STOP_MARKET',
    side='SELL' if position_side == 'LONG' else 'BUY',
    stopPrice=stop_loss_price,
    closePosition=True  # Close entire position
)
```

#### 3. Take-Profit: TAKE_PROFIT_MARKET Order
```python
# Triggered when price reaches target
tp_order = binance.create_order(
    symbol='BTCUSDT',
    type='TAKE_PROFIT_MARKET',
    side='SELL' if position_side == 'LONG' else 'BUY',
    stopPrice=take_profit_price,
    closePosition=True
)
```

### Position Sizing Formula

```python
# Base calculation
balance = 5928.10  # Binance testnet balance
risk_per_trade_pct = 1.5  # 1.5% of balance
risk_usd = balance * (risk_per_trade_pct / 100)  # $88.92

# ATR-based stop distance
atr_14 = calculate_atr(candles, period=14)
stop_distance = atr_14 * 1.5  # 1.5x ATR multiplier

# Position size calculation
# Risk = Position Size × Stop Distance
# Position Size = Risk / Stop Distance
position_size_btc = risk_usd / stop_distance

# Example:
# balance = $5,928.10
# risk = $88.92 (1.5%)
# atr_14 = $500
# stop_distance = $750 (1.5 × ATR)
# position_size = $88.92 / $750 = 0.1185 BTC ≈ $8,000 notional
```

### Stop-Loss & Take-Profit Calculation

```python
# For SHORT position
entry_price = 68000  # Current BTC price
atr = 500            # 14-period ATR
stop_multiplier = 1.5
tp_multiplier = 2.5

stop_loss = entry_price + (atr * stop_multiplier)
# stop_loss = 68000 + (500 × 1.5) = 68750

take_profit = entry_price - (atr * tp_multiplier)
# take_profit = 68000 - (500 × 2.5) = 66750

# Risk:Reward = 750 : 1250 = 1:1.67
```

### Order Execution Flow

```
1. Calculate position size
   ↓
2. Validate position size (min 0.001 BTC, max 10 BTC)
   ↓
3. Execute MARKET entry order
   ↓ [Wait for fill confirmation]
   ↓
4. Retrieve filled entry price
   ↓
5. Calculate actual stop-loss level
   ↓
6. Place STOP_MARKET order
   ↓
7. Calculate actual take-profit level
   ↓
8. Place TAKE_PROFIT_MARKET order
   ↓
9. Log order to order.jsonl
   ↓
10. Update position tracking
    ↓
11. Emit health heartbeat with new position count
```

---

## ⚙️ Configuration & Parameters

### Main Configuration File: `config.py`

#### Trading Parameters
```python
trading_mode: "live"                # Live trading (Binance testnet)
initial_balance: 5928.10            # Account balance
min_trade_amount: 0.002             # Minimum BTC per trade
max_position_size: 0.25             # Max 25% of balance per trade
max_daily_trades: 10                # Max trades per day
max_concurrent_positions: 3         # Max open positions
```

#### Risk Management
```python
max_drawdown: 0.15                  # 15% max drawdown
daily_risk_cap: 0.02                # 2% daily loss limit
stop_loss_multiplier: 1.5           # ATR × 1.5 for stops
take_profit_multiplier: 2.5         # Risk:Reward = 1:1.67
position_size_method: "r_based"     # Risk-based sizing
```

#### Signal Generation
```python
min_confidence_threshold: 0.05      # 5% minimum confidence
signal_cooldown_minutes: 2.0        # 2 min between signals
signal_check_interval_seconds: 60   # Check every 60 seconds
data_refresh_minutes: 1             # Refresh data every 1 min

# Signal source control
enable_cluster_signals: True        # ✅ Liquidation strategy
enable_tradingview_signals: False   # ❌ TradingView disabled
```

#### Data Staleness Thresholds
```python
price_stale_seconds: 120            # 2 min max for price
heatmap_stale_seconds: 900          # 15 min for liquidation data
oi_stale_seconds: 900               # 15 min for Open Interest
funding_stale_seconds: 900          # 15 min for Funding Rate
lsr_stale_seconds: 900              # 15 min for LSR
```

#### Liquidation Cluster Detection
```python
cluster_density_threshold: 50000    # $50K min liquidations
cluster_width_threshold: 0.003      # 0.3% max width
min_cluster_points: 2               # Min 2 liquidation levels
```

### API Configuration

#### Google Sheets Credentials
```json
// credentials.json (Service Account)
{
  "type": "service_account",
  "project_id": "your-project-id",
  "private_key_id": "key-id",
  "private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n",
  "client_email": "service-account@project.iam.gserviceaccount.com",
  "client_id": "123456789",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token"
}
```

**Multiple Credentials for Quota Management:**
- `credentials.json` (primary)
- `credentials1.json` (backup)
- `credentials2.json` (backup)

**Rotation Logic:** When quota exceeded, switch to next credential file

#### Binance API Configuration
```python
# Set via environment variables or .env file
BINANCE_API_KEY=your_testnet_api_key
BINANCE_API_SECRET=your_testnet_secret
BINANCE_TESTNET=True  # Use testnet
```

---

## 📁 File Structure

### Core Files

```
/home/ubuntu/tradingview-webhook-mvp/trading_bot/
│
├── enhanced_trading_bot.py          # Main entry point, bot orchestration
├── config.py                         # Configuration management
├── signal_generator.py               # Core signal generation logic (4,800+ lines)
├── data_sources.py                   # Google Sheets & Binance WebSocket clients
├── binance_futures_adapter.py        # Binance Futures API wrapper
│
├── credentials.json                  # Google API credentials (primary)
├── credentials1.json                 # Backup credentials
├── credentials2.json                 # Backup credentials
│
├── strategy_refinement.py            # Multi-timeframe analysis
├── risk_invariants.py                # Risk management rules
├── edge_calibration.py               # Edge calculation
├── regime_detection.py               # Market regime classifier
├── cluster_metrics.py                # Cluster analysis tools
├── execution_quality.py              # Order execution monitoring
├── veto_analyzer.py                  # Signal veto tracking
├── trade_review.py                   # Trade performance analysis
├── rolling_metrics_monitor.py        # Real-time metrics
├── hybrid_signal_validator.py        # Signal validation (TradingView integration)
│
├── bot.log                           # Main bot logs (16 MB)
├── bot_error.log                     # Error logs
│
├── events/                           # Observability event logs
│   ├── decision.jsonl                # Trading decisions (13 MB, 5,277 decisions)
│   ├── order.jsonl                   # Order executions (2.5 MB, 5,277 orders)
│   ├── fill.jsonl                    # Trade fills (279 KB, 504 fills)
│   ├── health.jsonl                  # Health heartbeats (17 MB, every 60s)
│   ├── error.jsonl                   # Errors (0 KB - empty)
│   ├── guard.jsonl                   # Risk guard triggers
│   ├── veto.jsonl                    # Signal vetoes
│   └── session.jsonl                 # Session tracking (53 KB)
│
├── logs/                             # Additional logs
│   ├── csv/                          # CSV exports for analysis
│   └── llm_summaries/                # LLM-generated trade summaries
│
└── backtester/                       # Backtesting framework
    ├── backtest_artifacts/           # Historical test results
    └── events/                       # Backtest event logs
```

### Key File Descriptions

#### `enhanced_trading_bot.py` (Main Entry Point)
- Initializes all components
- Starts signal generator
- Handles graceful shutdown
- PID file locking (prevents duplicate processes)
- Signal handlers (SIGTERM/SIGINT)

#### `signal_generator.py` (Core Logic - 4,800+ lines)
**Key Functions:**
- `start()`: Start bot main loop
- `stop()`: Stop bot gracefully
- `load_all_data()`: Fetch liquidation/OI/FR data from Google Sheets
- `identify_clusters()`: DBSCAN clustering on liquidation data
- `check_for_enhanced_signals()`: Main signal generation (every 60s)
- `calculate_multi_timeframe_score()`: Trend analysis across 5 timeframes
- `analyze_oi_fr_lsr()`: Sentiment analysis
- `process_tradingview_signals()`: TradingView webhook processing (disabled)

#### `data_sources.py` (Data Fetching)
**Classes:**
- `EnhancedGoogleSheetsClient`: Fetch data from Google Sheets
  - Methods: `get_liquidation_data()`, `get_oi_data()`, `get_funding_data()`
  - Credential rotation for quota management
- `EnhancedBinanceWebSocketClient`: Real-time BTC price via WebSocket
  - Auto-reconnect on disconnect
  - Heartbeat monitoring

#### `binance_futures_adapter.py` (Order Execution)
**Methods:**
- `create_market_order()`: Execute MARKET order
- `create_order()`: Execute STOP/LIMIT orders
- `set_leverage()`: Set position leverage
- `get_balance()`: Fetch account balance
- `get_position()`: Get current position
- `cancel_all_orders()`: Emergency order cancellation

#### `config.py` (Configuration)
**Classes:**
- `TradingConfig`: Trading parameters
- `SMCBoostConfig`: SMC indicator boost (disabled)
- `config_manager`: Global config instance

---

## 📊 Monitoring & Observability

### Event Logging System

#### Decision Events (`events/decision.jsonl`)
**Logged:** Every time a signal is generated or rejected

**Schema:**
```json
{
  "ts": "2026-02-18T06:55:54.682Z",
  "run_id": "cbc354f3-36c4-4ba0-9f91-502289881b2d",
  "session_id": "81f72122-167d-409d-9b9d-14d0fea20132",
  "venue": "binanceusdm",
  "symbol": "BTCUSDT",
  "event": "decision",
  "signal_dir": "SHORT",
  "signal_strength": "WEAK",
  "votes": {
    "m1": "NEUTRAL",
    "m2": "SHORT",
    "m3": "NEUTRAL"
  },
  "cluster": {
    "distance_bps": 201.36,
    "density": 477198.36,
    "strength": 25
  },
  "action": "NO_TRADE",
  "no_trade_reason": "Only cluster votes with NEUTRAL sentiment",
  "price": 67784.90,
  "regime": "ranging"
}
```

#### Health Heartbeats (`events/health.jsonl`)
**Logged:** Every 60 seconds

**Schema:**
```json
{
  "ts": "2026-02-18T06:55:15.772Z",
  "event": "health.heartbeat",
  "venue": "binanceusdm",
  "symbol": "BTCUSDT",
  "mode": "LIVE",
  "price_age_s": 0.028,
  "heatmap_age_s": 44.5,
  "ws_connected": true,
  "positions_open": 0,
  "equity_usd": 5928.1,
  "pnl_realized_usd": 0.0,
  "pnl_unrealized_usd": 0.0,
  "risk_remaining_usd": 118.56,
  "kill_switch_active": false,
  "daily_cap_hit": false
}
```

#### Order Events (`events/order.jsonl`)
**Logged:** When orders are placed

**Schema:**
```json
{
  "ts": "2026-01-19T10:20:55.171Z",
  "event": "order",
  "order_id": "ord_7cfd15ea",
  "decision_id": "c6e2627c-8c3e-4a7b-9164-5401726bf53b",
  "side": "SELL",
  "type": "MARKET",
  "px": 92975.3,
  "qty": 0.005156,
  "status": "FILLED"
}
```

### Monitoring Commands

#### Check Bot Status
```bash
# Process status
ps aux | grep enhanced_trading_bot | grep -v grep

# Uptime
ps -p <PID> -o etime,start

# Resource usage
ps -p <PID> -o %cpu,%mem,rss
```

#### View Live Logs
```bash
# Main bot log
tail -f /home/ubuntu/tradingview-webhook-mvp/trading_bot/bot.log

# Filter for signals
tail -f bot.log | grep -E 'MARKET ANALYSIS|Current Price|Bias:'

# Filter for trades
tail -f bot.log | grep -E 'Execute|PLACE|FILLED'
```

#### Check Recent Activity
```bash
# Recent decisions
tail -20 events/decision.jsonl | python3 -m json.tool

# Latest health status
tail -1 events/health.jsonl | python3 -m json.tool

# Recent orders
tail -10 events/order.jsonl
```

#### Analyze Performance
```bash
# Count trades today
grep "$(date +%Y-%m-%d)" events/order.jsonl | wc -l

# Count decisions
wc -l events/decision.jsonl

# Check cluster detection
grep "Identified.*clusters" bot.log | tail -20
```

### Key Metrics to Monitor

#### System Health
- **WebSocket Connected:** Should always be `true`
- **Price Age:** Should be < 2 seconds
- **Heatmap Age:** Should be < 900 seconds (15 min)
- **Kill Switch:** Should be `false`
- **Daily Cap Hit:** Should be `false`

#### Trading Activity
- **Positions Open:** 0-3 (max_concurrent_positions)
- **Risk Used %:** 0-100% (% of 2% daily cap used)
- **PnL (Realized):** Track daily P&L
- **PnL (Unrealized):** Monitor open positions

#### Signal Quality
- **Decisions per Hour:** ~60 (one per minute)
- **Signals Rejected:** Should see rejections when market is ranging
- **Cluster Detection:** Should see "Identified 11 liquidation clusters" every 60s

---

## 🛡️ Risk Management

### Multi-Layer Risk Controls

#### Layer 1: Position Sizing
```python
# Base risk: 1.5% of balance per trade
risk_per_trade = balance * 0.015  # $88.92 on $5,928 balance

# ATR-based stop distance ensures consistent risk
position_size = risk_per_trade / stop_distance

# Hard limits
min_position_btc = 0.001  # Minimum 0.001 BTC
max_position_btc = balance * 0.25 / current_price  # Max 25% of balance
```

#### Layer 2: Daily Loss Cap
```python
daily_loss_cap = balance * 0.02  # 2% max loss per day = $118.56

# Track daily P&L
daily_pnl = sum(realized_pnl_today)

# Stop trading if cap hit
if abs(daily_pnl) >= daily_loss_cap:
    kill_switch_activate(reason="Daily loss cap hit")
    return None  # No more trades today
```

#### Layer 3: Position Limits
```python
max_concurrent_positions = 3

if positions_open >= max_concurrent_positions:
    log_warning("Max concurrent positions reached")
    return None  # Don't open new trades
```

#### Layer 4: Signal Cooldown
```python
signal_cooldown_seconds = 120  # 2 minutes

time_since_last_signal = now - last_signal_time

if time_since_last_signal < signal_cooldown_seconds:
    log_debug(f"Signal cooldown active ({cooldown_remaining}s remaining)")
    return None  # Prevent rapid-fire trading
```

#### Layer 5: Kill Switch
**Automatic Triggers:**
- Daily loss cap exceeded
- Max drawdown exceeded (15%)
- Consecutive losses > 5 trades
- WebSocket disconnected for > 5 minutes
- Data staleness > 30 minutes

**Manual Activation:**
```python
# Emergency stop via API or file touch
if os.path.exists('/tmp/trading-bot-kill-switch'):
    kill_switch_activate(reason="Manual kill switch")
```

#### Layer 6: Drawdown Protection
```python
max_drawdown = 0.15  # 15%

# Calculate drawdown from peak
peak_balance = max(historical_balances)
current_drawdown = (peak_balance - current_balance) / peak_balance

if current_drawdown >= max_drawdown:
    kill_switch_activate(reason="Max drawdown exceeded")
```

---

## 🚀 Setup & Deployment

### Prerequisites

#### System Requirements
- **OS:** Ubuntu 20.04+ (Linux)
- **Python:** 3.12+
- **RAM:** 4 GB minimum (bot uses ~200 MB)
- **Storage:** 20 GB (for logs and event data)

#### API Accounts Required
1. **Google Cloud Platform:**
   - Enable Google Sheets API
   - Create Service Account
   - Download credentials JSON files
   - Share spreadsheets with service account email

2. **Binance Futures Account:**
   - Create testnet account: https://testnet.binancefuture.com/
   - Generate API key and secret
   - Enable futures trading

### Installation Steps

#### 1. Clone Repository
```bash
cd /home/ubuntu
git clone https://github.com/your-repo/tradingview-webhook-mvp.git
cd tradingview-webhook-mvp/trading_bot
```

#### 2. Install Python Dependencies
```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install packages
pip install -r requirements.txt

# Key packages:
# - google-api-python-client (Google Sheets)
# - ccxt (Binance API)
# - pandas, numpy (data processing)
# - scikit-learn (DBSCAN clustering)
# - websocket-client (price feed)
```

#### 3. Configure Credentials

**Google Sheets:**
```bash
# Place credential files
cp /path/to/credentials.json ./
cp /path/to/credentials1.json ./
cp /path/to/credentials2.json ./

# Set permissions
chmod 600 credentials*.json
```

**Binance API:**
```bash
# Create .env file
cat > .env << EOF
BINANCE_API_KEY=your_testnet_api_key
BINANCE_API_SECRET=your_testnet_secret
BINANCE_TESTNET=True
EOF
```

#### 4. Update Configuration

Edit `config.py`:
```python
# Set your balance
initial_balance: float = 5928.10  # Your testnet balance

# Set spreadsheet IDs
api_config = APIConfig()
api_config.liquidation_spreadsheet_key = "your_spreadsheet_id"
api_config.oi_fr_spreadsheet_key = "your_oi_spreadsheet_id"
```

#### 5. Create Systemd Service

```bash
sudo nano /etc/systemd/system/trading-bot.service
```

```ini
[Unit]
Description=Trading Bot - TradingView Signal Processor
After=network.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/tradingview-webhook-mvp/trading_bot
Environment="PATH=/usr/local/bin:/usr/bin:/bin"
Environment="PYTHONUNBUFFERED=1"
EnvironmentFile=/home/ubuntu/tradingview-webhook-mvp/trading_bot/.env

ExecStart=/usr/bin/python3 -u enhanced_trading_bot.py

Restart=always
RestartSec=10
StartLimitInterval=300
StartLimitBurst=5

StandardOutput=append:/home/ubuntu/tradingview-webhook-mvp/trading_bot/bot.log
StandardError=append:/home/ubuntu/tradingview-webhook-mvp/trading_bot/bot_error.log

[Install]
WantedBy=multi-user.target
```

#### 6. Start the Bot

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable auto-start on boot
sudo systemctl enable trading-bot.service

# Start the bot
sudo systemctl start trading-bot.service

# Check status
sudo systemctl status trading-bot.service

# View logs
tail -f bot.log
```

### Verification

#### Check Bot is Running
```bash
# Process check
ps aux | grep enhanced_trading_bot | grep -v grep

# Should see:
# ubuntu   1234567  5.0  5.2  644148 205796 ?  Ssl  06:07  0:02 /usr/bin/python3 -u enhanced_trading_bot.py
```

#### Verify Data Loading
```bash
# Check logs for cluster detection
tail -100 bot.log | grep "Identified.*clusters"

# Should see:
# 2026-02-18 06:55:54 - Identified 11 liquidation clusters from 334 data points
```

#### Check Health
```bash
# View latest heartbeat
tail -1 events/health.jsonl | python3 -m json.tool

# Verify:
# - ws_connected: true
# - price_age_s < 2
# - heatmap_age_s < 900
# - kill_switch_active: false
```

---

## 🔍 Troubleshooting

### Common Issues

#### Bot Not Starting
```bash
# Check service status
sudo systemctl status trading-bot.service

# View error logs
tail -50 bot_error.log

# Common causes:
# - Missing credentials.json files
# - Invalid API keys
# - Python dependencies not installed
```

#### No Cluster Detection
```bash
# Check if liquidation data is loading
tail -200 bot.log | grep "liquidation"

# Possible causes:
# - Spreadsheet ID incorrect
# - Service account not shared with spreadsheet
# - Google API quota exceeded (check credentials rotation)
```

#### No Trades Executing
```bash
# Check decision log for rejection reasons
tail -10 events/decision.jsonl | python3 -c "import sys,json; [print(json.loads(l)['no_trade_reason']) for l in sys.stdin]"

# Common reasons:
# - "Market regime ranging not suitable" → Wait for trending market
# - "Only cluster votes with NEUTRAL sentiment" → Wait for OI/FR confirmation
# - "Signal cooldown active" → Wait 2 minutes
# - "Daily cap hit" → Next day
```

#### WebSocket Disconnects
```bash
# Check connection status
grep "WebSocket" bot.log | tail -20

# Auto-reconnect logic should handle this
# If persistent disconnects, check network/firewall
```

---

## 📈 Performance Optimization

### Google Sheets API Quota Management

**Quota Limits:**
- 100 requests per 100 seconds per user
- 500 requests per 100 seconds per project

**Optimization Strategies:**
1. **Credential Rotation:** Use 3 service accounts (credentials.json, credentials1.json, credentials2.json)
2. **Caching:** Data refreshes every 60 seconds (not on every signal check)
3. **Batch Requests:** Fetch multiple sheets in single API call

### Memory Management
```python
# Limit historical data
max_candles_per_timeframe = 300  # Keep only last 300 candles

# Clear old data periodically
if len(historical_data) > 10000:
    historical_data = historical_data[-5000:]  # Keep last 5000 records
```

### Logging Optimization
```python
# Rotate logs daily
logging.handlers.RotatingFileHandler(
    'bot.log',
    maxBytes=50*1024*1024,  # 50 MB
    backupCount=5            # Keep 5 backup files
)
```

---

## 📚 Additional Resources

### Trading Concepts
- **Liquidation Cascades:** https://www.investopedia.com/liquidation-cascade
- **Funding Rates:** https://www.binance.com/en/support/faq/funding-rates
- **Open Interest:** https://www.investopedia.com/open-interest

### Technical Documentation
- **Binance Futures API:** https://binance-docs.github.io/apidocs/futures/en/
- **Google Sheets API:** https://developers.google.com/sheets/api
- **DBSCAN Clustering:** https://scikit-learn.org/stable/modules/clustering.html#dbscan

### Code References
- **CCXT Library:** https://github.com/ccxt/ccxt
- **WebSocket Client:** https://websocket-client.readthedocs.io/

---

## 🎓 Strategy Refinements & Future Improvements

### Potential Enhancements

#### 1. Dynamic Position Sizing
```python
# Adjust position size based on signal confidence
if signal_confidence > 0.8:
    position_size *= 1.5  # Increase size for high-confidence signals
elif signal_confidence < 0.3:
    position_size *= 0.5  # Reduce size for low-confidence signals
```

#### 2. Multi-Symbol Support
```python
# Expand beyond BTC to ETH, BNB, etc.
symbols = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT']
for symbol in symbols:
    check_liquidation_clusters(symbol)
```

#### 3. Machine Learning Integration
```python
# Train ML model on historical cluster → price reaction patterns
# Features: cluster density, distance, OI change, funding rate
# Target: Price movement after 1h, 4h, 24h
```

#### 4. Adaptive Parameters
```python
# Adjust cluster thresholds based on market conditions
if volatility > avg_volatility * 2:
    cluster_density_threshold *= 1.5  # Require stronger clusters in high vol
```

---

## 📝 Glossary

- **Liquidation:** Forced closure of leveraged position when margin depleted
- **Liquidation Cluster:** Concentration of liquidation levels at similar price
- **Open Interest (OI):** Total value of outstanding futures contracts
- **Funding Rate:** Periodic payment between longs and shorts in perpetual futures
- **Long/Short Ratio (LSR):** Ratio of long positions to short positions
- **ATR:** Average True Range - volatility indicator
- **DBSCAN:** Density-Based Spatial Clustering of Applications with Noise
- **Kill Switch:** Emergency mechanism to stop all trading
- **Heartbeat:** Periodic health status emission (every 60s)
- **Emitter:** Component that logs events to JSONL files

---

**Last Updated:** February 18, 2026  
**Bot Version:** v2.0 (Liquidation Strategy Only Mode)  
**Status:** Production - Active Trading on Binance Testnet
