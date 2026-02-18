# 📡 TradingView Webhook Trading Bot - Technical Documentation
**Project:** Multi-Strategy TradingView Signal Trading Bot  
**Created:** February 18, 2026  
**Server:** ubuntu@13.236.143.201  
**Location:** `/home/ubuntu/tradingview-bot/`

---

## 📚 Table of Contents
1. [Strategy Overview](#strategy-overview)
2. [How TradingView Strategy Works](#how-tradingview-strategy-works)
3. [System Architecture](#system-architecture)
4. [Signal Flow](#signal-flow)
5. [Multi-Strategy Configuration](#multi-strategy-configuration)
6. [Trade Execution Logic](#trade-execution-logic)
7. [Configuration & Parameters](#configuration--parameters)
8. [File Structure](#file-structure)
9. [Monitoring & Observability](#monitoring--observability)
10. [Risk Management](#risk-management)
11. [Setup & Deployment](#setup--deployment)
12. [TradingView Alert Configuration](#tradingview-alert-configuration)

---

## 🎯 Strategy Overview

### What is TradingView Webhook Trading?

The TradingView bot receives trading signals from TradingView alerts (Pine Script indicators) via HTTP webhooks and automatically executes trades on Binance Futures Testnet. It supports multiple concurrent strategies, each running as an independent bot process with its own configuration, risk management, and virtual balance.

### Core Concept

**Signal-Driven Automated Trading:**
- TradingView indicators generate LONG/SHORT signals based on technical analysis
- Alerts trigger webhooks containing signal data (strategy, side, price, stop-loss, take-profit)
- Bot validates signals, calculates position size, and executes LIMIT orders on Binance
- P&L tracked using mainnet prices (real market data) for accuracy

### Trading Philosophy

```
MAINNET PRICE AUTHORITY:
- ALL prices fetched from Binance MAINNET (live spot/futures prices)
- ALL orders executed on Binance TESTNET (no real money risk)
- P&L calculated using MAINNET prices ONLY
- Ensures realistic backtesting with real market conditions

VIRTUAL BALANCE SIMULATION:
- Each strategy operates with independent virtual balance
- Tracks realized/unrealized P&L accurately
- Prevents testnet balance inconsistencies from affecting metrics
```

---

## 📡 How TradingView Strategy Works

### 1. TradingView Alert Creation

**Indicator Examples:**
- **Institutional Flow Hybrid:** Volume profile + smart money concepts
- **Squeeze Flow Expansion:** Bollinger Bands squeeze + momentum breakout
- **SMA Crossover 9/21:** Fast/slow moving average crossover
- **Supertrend BTC 4H:** ATR-based trend following
- **Madrid Ribbon:** Multi-timeframe EMA/SMA ribbon
- **Lorentzian Classification:** Machine learning price classification

**Alert Message (JSON Webhook Payload):**
```json
{
  "secret": "squeeze_tradingview_cluster_2026_secure",
  "strategy": "squeeze_flow_expansion",
  "side": "LONG",
  "symbol": "BTCUSDT",
  "price": "{{close}}",
  "timeframe": "15m",
  "stop_loss": "{{stop_loss}}",
  "take_profit": "{{take_profit}}",
  "timestamp": "{{timenow}}"
}
```

**Alert Conditions (Pine Script Example):**
```pine
// Squeeze Flow Expansion - LONG Entry
longCondition = ta.crossover(ta.ema(close, 9), ta.ema(close, 21)) and
                bb_squeeze_release and
                rsi > 50

// Webhook URL
alert(
    "Long Entry",
    alert.freq_once_per_bar_close,
    webhook = "http://13.236.143.201:8004/webhook/tradingview"
)
```

### 2. Webhook Reception & Queue Storage

**Webhook Server (Flask):**
- Listens on unique port per strategy (8001-8010)
- Validates webhook secret (prevents unauthorized signals)
- Validates required fields (strategy, side, symbol, price, timeframe)
- Generates unique signal ID
- Writes signal to JSONL queue file (atomic, crash-safe)

**Signal Queue File (`storage/signals_<strategy>.jsonl`):**
```json
{
  "signal_id": "sig_20260218_065432_BTCUSDT_LONG",
  "strategy": "squeeze_flow_expansion",
  "side": "LONG",
  "symbol": "BTCUSDT",
  "price": "67850.50",
  "timeframe": "15m",
  "stop_loss": "66800.00",
  "take_profit": "69500.00",
  "timestamp": "2026-02-18T06:54:32.123456Z",
  "processed": false
}
```

**Queue Benefits:**
- Decouples signal reception from trade execution
- Prevents signal loss during bot restarts
- Allows signal replay for debugging
- Enables historical analysis

### 3. Signal Processing & Validation

**Signal Processor (`core/signal_processor.py`):**

**Multi-Layer Validation:**

#### Layer 1: Data Freshness ✅
```python
# Reject stale signals (price may have moved significantly)
signal_age = now - signal_timestamp
if signal_age > signal_expiry_seconds:  # Default: 300-900s
    logger.warning(f"Signal expired: {signal_age}s old")
    mark_processed(signal, status='EXPIRED')
    return None
```

#### Layer 2: Symbol & Timeframe Validation ✅
```python
# Only trade configured symbols and timeframes
allowed_symbols = config['trading']['symbols_allowed']
allowed_timeframes = config['trading']['timeframes_allowed']

if signal['symbol'] not in allowed_symbols:
    logger.warning(f"Symbol {symbol} not in whitelist")
    return None

if signal['timeframe'] not in allowed_timeframes:
    logger.warning(f"Timeframe {timeframe} not allowed")
    return None
```

#### Layer 3: Price Validation (Mainnet Authority) ✅
```python
# Compare signal price vs current mainnet price
signal_price = float(signal['price'])
mainnet_price = price_provider.get_current_price(symbol)

deviation_pct = abs(signal_price - mainnet_price) / mainnet_price * 100

if deviation_pct > max_deviation_pct:  # Default: 5-8%
    logger.warning(f"Price deviation {deviation_pct:.2f}% too high")
    mark_processed(signal, status='PRICE_MISMATCH')
    return None

# Use mainnet price for execution (more accurate)
signal['validated_price'] = mainnet_price
```

#### Layer 4: Duplicate Signal Detection ✅
```python
# Prevent duplicate execution of same signal
if signal_already_processed(signal_id):
    logger.debug(f"Signal {signal_id} already processed")
    return None
```

#### Layer 5: Strategy Enabled Check ✅
```python
# Only process signals from enabled strategies
enabled_strategies = config['strategies']['enabled']

if signal['strategy'] not in enabled_strategies:
    logger.info(f"Strategy {signal['strategy']} not enabled")
    mark_processed(signal, status='STRATEGY_DISABLED')
    return None
```

### 4. Position Size Calculation & Validation

**Risk Manager (`core/risk_manager.py`):**

```python
def calculate_position_size(self, balance, entry_price):
    """
    Calculate safe position size based on risk rules.
    
    Formula:
    1. Calculate USD size: balance × position_size_pct / 100
    2. Apply leverage: usd_size × leverage
    3. Convert to contracts: usd_size / entry_price
    4. Apply hard caps
    """
    # Step 1: Base USD size
    position_size_pct = self.config['risk']['position_size_value']
    usd_size = balance * (position_size_pct / 100)
    
    # Step 2: Apply leverage
    leverage = self.config['trading']['leverage']
    leveraged_size = usd_size * leverage
    
    # Step 3: Convert to contracts (BTC, ETH, SOL, etc.)
    contracts = leveraged_size / entry_price
    
    # Step 4: Apply minimum size
    min_size_usd = self.config['risk']['min_position_usd']
    if usd_size < min_size_usd:
        logger.warning(f"Position ${usd_size:.2f} below minimum ${min_size_usd}")
        return 0.0
    
    return contracts
```

**Position Size Validator (`core/position_size_validator.py`):**

**CRITICAL PROTECTION:** Prevents catastrophic position sizing bugs (1000%+ oversized positions)

```python
def validate_and_recalculate(self, signal, balance, risk_manager):
    """
    Multi-layer position size validation with override capability.
    
    SECURITY RULES:
    1. NEVER trust position_size from TradingView webhook (can be malicious)
    2. ALWAYS recalculate based on internal risk rules
    3. Apply absolute hard caps (max notional, max % of balance)
    4. Log and alert on anomalies
    5. Override dangerous sizes with safe calculated values
    """
    # Calculate expected size based on risk rules
    expected_size = risk_manager.calculate_position_size(balance, price)
    expected_notional = expected_size * price
    
    # Check if webhook provided position_size
    webhook_size = float(signal.get('position_size', 0))
    
    if webhook_size > 0:
        webhook_notional = webhook_size * price
        ratio = webhook_notional / expected_notional
        
        # CRITICAL CHECK: Is webhook size dangerously oversized?
        if ratio > 1.5:  # More than 1.5x expected size
            logger.error(f"🚨 POSITION SIZE ANOMALY DETECTED!")
            logger.error(f"   Webhook: {webhook_size:.4f} (${webhook_notional:.2f})")
            logger.error(f"   Expected: {expected_size:.4f} (${expected_notional:.2f})")
            logger.error(f"   Ratio: {ratio:.2f}x")
            logger.error(f"   🛡️ OVERRIDING with safe size")
            
            # Log to critical alerts file
            log_critical_alert({
                'alert_type': 'POSITION_SIZE_ANOMALY',
                'webhook_size': webhook_size,
                'expected_size': expected_size,
                'ratio': ratio,
                'action': 'OVERRIDE_WITH_SAFE_SIZE'
            })
    
    # Use calculated size (ignore webhook)
    final_size = expected_size
    
    # Apply absolute hard caps
    absolute_max_notional = config['risk']['absolute_max_notional_usd']
    if final_size * price > absolute_max_notional:
        logger.warning(f"Capping notional at ${absolute_max_notional}")
        final_size = absolute_max_notional / price
    
    absolute_max_pct = config['risk']['absolute_max_position_pct']
    max_position_value = balance * (absolute_max_pct / 100)
    if final_size * price > max_position_value:
        logger.warning(f"Capping at {absolute_max_pct}% of balance")
        final_size = max_position_value / price
    
    return final_size
```

**Real-World Protection:**
```
BEFORE Position Size Validator:
- OBV strategy produced 9.2 ETH position (should be 0.776 ETH)
- Notional: $17,782 (should be $1,500)
- Result: $234 loss in single trade (1085% oversized)

AFTER Position Size Validator:
- Webhook position_size: IGNORED
- Calculated size: 0.0776 ETH ($1,500 notional)
- Hard cap applied: $2,000 max
- Result: Safe, correctly sized position ✅
```

### 5. Order Execution

**Enhanced Order Manager (`core/enhanced_order_manager.py`):**

**Order Type: LIMIT Orders Only**

```python
def execute_order(self, signal, validated_position_size):
    """Execute LIMIT order on Binance testnet using mainnet price"""
    
    # Get mainnet price for accurate execution
    mainnet_price = self.price_provider.get_current_price(signal['symbol'])
    
    # Calculate limit price (slightly better than market for fill probability)
    if signal['side'] == 'LONG':
        # Long: Buy slightly below market (limit buy)
        limit_price = mainnet_price * 0.9995  # 0.05% below
    else:
        # Short: Sell slightly above market (limit sell)
        limit_price = mainnet_price * 1.0005  # 0.05% above
    
    # Place LIMIT order on testnet
    order = self.execution_engine.create_limit_order(
        symbol=signal['symbol'],
        side=signal['side'],
        amount=validated_position_size,
        price=limit_price
    )
    
    # Wait for fill (with timeout)
    filled_order = self.wait_for_fill(order, timeout=30)
    
    if filled_order:
        filled_price = filled_order['price']
        filled_qty = filled_order['qty']
        
        # Create position record
        position = {
            'position_id': generate_position_id(),
            'signal_id': signal['signal_id'],
            'strategy': signal['strategy'],
            'symbol': signal['symbol'],
            'side': signal['side'],
            'entry_price': filled_price,  # Use actual fill price
            'qty': filled_qty,
            'stop_loss': calculate_stop_loss(signal, filled_price),
            'take_profit': calculate_take_profit(signal, filled_price),
            'opened_at': datetime.utcnow().isoformat() + 'Z',
            'status': 'OPEN'
        }
        
        # Save position
        self.position_manager.add_position(position)
        
        # Place stop-loss order (STOP_MARKET)
        self.place_stop_loss_order(position)
        
        # Place take-profit order (TAKE_PROFIT_MARKET)
        self.place_take_profit_order(position)
        
        logger.info(f"✅ Position opened: {filled_qty:.4f} {symbol} @ ${filled_price:.2f}")
        
        return position
    else:
        logger.warning(f"⚠️ Order not filled within timeout")
        self.cancel_order(order['orderId'])
        return None
```

### 6. Position Monitoring & Exit

**Order Monitor (`core/order_monitor.py`):**

```python
def monitor_positions(self):
    """
    Monitor open positions for stop-loss/take-profit fills.
    
    Process:
    1. Get all open positions from storage
    2. For each position, check if SL/TP orders filled
    3. If filled, calculate P&L using MAINNET prices
    4. Update virtual balance
    5. Mark position as closed
    """
    open_positions = self.position_manager.get_open_positions()
    
    for position in open_positions:
        # Check stop-loss order status
        sl_order = self.check_order_status(position['sl_order_id'])
        tp_order = self.check_order_status(position['tp_order_id'])
        
        if sl_order['status'] == 'FILLED':
            # Stop-loss hit
            exit_price = float(sl_order['price'])
            pnl = self.calculate_pnl(position, exit_price, 'MAINNET')
            
            self.close_position(position, exit_price, pnl, reason='STOP_LOSS')
            self.balance_manager.update_balance(pnl)
            
            logger.info(f"🛑 Stop-loss hit: {position['symbol']} @ ${exit_price:.2f}, P&L: ${pnl:+.2f}")
        
        elif tp_order['status'] == 'FILLED':
            # Take-profit hit
            exit_price = float(tp_order['price'])
            pnl = self.calculate_pnl(position, exit_price, 'MAINNET')
            
            self.close_position(position, exit_price, pnl, reason='TAKE_PROFIT')
            self.balance_manager.update_balance(pnl)
            
            logger.info(f"🎯 Take-profit hit: {position['symbol']} @ ${exit_price:.2f}, P&L: ${pnl:+.2f}")
```

**P&L Calculation (Mainnet Price Authority):**
```python
def calculate_pnl(self, position, exit_price, price_source='MAINNET'):
    """
    Calculate P&L using MAINNET prices for accuracy.
    
    Formula:
    - LONG: (exit_price - entry_price) × qty
    - SHORT: (entry_price - exit_price) × qty
    """
    entry_price = float(position['entry_price'])
    qty = float(position['qty'])
    
    if position['side'] == 'LONG':
        pnl = (exit_price - entry_price) * qty
    else:  # SHORT
        pnl = (entry_price - exit_price) * qty
    
    return pnl
```

### 7. Signal Archiver (Queue Management)

**Signal Archiver (`utils/signal_archiver.py`):**

**Problem Solved:**
- Signal queue grows indefinitely with processed signals
- Example: 3,282 old signals from January still in queue
- Slows down processing and wastes disk space

**Solution:**
```python
def archive_old_signals(self, queue_file):
    """
    Archive processed signals older than retention period (default: 7 days).
    
    Process:
    1. Read all signals from queue
    2. Categorize: active (unprocessed or recent) vs archivable (old processed)
    3. Write archivable to dated compressed file (.jsonl.gz)
    4. Rewrite queue with only active signals
    5. Schedule cleanup of archive files older than 30 days
    """
    cutoff_time = datetime.utcnow() - timedelta(days=7)
    
    active_signals = []
    archive_signals = []
    
    for signal in read_signals(queue_file):
        # Keep unprocessed signals
        if not signal.get('processed'):
            active_signals.append(signal)
            continue
        
        # Keep recently processed signals
        processed_at = parse_timestamp(signal['processed_at'])
        if processed_at >= cutoff_time:
            active_signals.append(signal)
        else:
            # Archive old processed signals
            archive_signals.append(signal)
    
    # Write archive file (compressed)
    archive_filename = f"signals_archive_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.jsonl.gz"
    with gzip.open(f"storage/archive/{archive_filename}", 'wt') as f:
        for signal in archive_signals:
            f.write(json.dumps(signal) + '\n')
    
    # Rewrite queue with only active signals
    with open(queue_file, 'w') as f:
        for signal in active_signals:
            f.write(json.dumps(signal) + '\n')
    
    logger.info(f"✅ Archived {len(archive_signals)} signals, kept {len(active_signals)} active")
    
    return len(active_signals), len(archive_signals)
```

**Automatic Execution:**
- Runs every 24 hours during trading loop
- Compresses archives with gzip (saves 90% space)
- Keeps 7 days of signals in live queue
- Retains archives for 30 days (historical analysis)

**Results:**
```
Before Archiver:
- Queue file: 3,525 signals (1.2 MB)
- Oldest signal: Jan 24, 2026 (25 days old)

After First Run:
- Active queue: 243 signals (80 KB)
- Archived: 3,282 signals → 138 KB compressed
- Processing speed: 50% faster (less I/O)
```

---

## 🏗️ System Architecture

### High-Level Component Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                   TRADINGVIEW.COM                            │
│  (Pine Script Indicators: Flow, Squeeze, SMA, Supertrend)   │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  │ Webhook HTTP POST (JSON payload)
                  ↓
┌─────────────────────────────────────────────────────────────┐
│                WEBHOOK SERVER (Flask)                        │
│  - Port: 8001-8010 (one per strategy)                       │
│  - Secret validation                                         │
│  - Field validation                                          │
│  - Signal ID generation                                      │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  │ Atomic write (crash-safe)
                  ↓
┌─────────────────────────────────────────────────────────────┐
│            SIGNAL QUEUE (JSONL File)                         │
│  storage/signals_<strategy>.jsonl                            │
│  - Persistent storage                                        │
│  - Append-only log                                           │
│  - Signal archiver (7-day retention)                         │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  │ Read every 5 seconds
                  ↓
┌─────────────────────────────────────────────────────────────┐
│            SIGNAL PROCESSOR                                  │
│  - Read unprocessed signals                                  │
│  - Validate: freshness, symbol, timeframe, price             │
│  - Mainnet price check (deviation < 5-8%)                    │
│  - Duplicate detection                                       │
│  - Strategy enabled check                                    │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  │ Validated signals
                  ↓
┌─────────────────────────────────────────────────────────────┐
│         ENHANCED ORDER MANAGER                               │
│                                                               │
│  ┌─────────────────────────────────────────────┐            │
│  │ 1. Circuit Breaker Check                     │            │
│  │    - Daily loss limit (2%)                   │            │
│  │    - Max consecutive losses (5)              │            │
│  │    - Cooldown period (60 min)                │            │
│  └─────────────────────────────────────────────┘            │
│                                                               │
│  ┌─────────────────────────────────────────────┐            │
│  │ 2. Position Limits Check                     │            │
│  │    - Max concurrent positions (3-5)          │            │
│  │    - Max symbol exposure                     │            │
│  │    - Opposite signal handling                │            │
│  └─────────────────────────────────────────────┘            │
│                                                               │
│  ┌─────────────────────────────────────────────┐            │
│  │ 3. Position Size Calculation                 │            │
│  │    - Risk manager: balance × % / 100         │            │
│  │    - Position Size Validator: override check │            │
│  │    - Hard caps: max notional, max %          │            │
│  └─────────────────────────────────────────────┘            │
│                                                               │
│  ┌─────────────────────────────────────────────┐            │
│  │ 4. Order Execution                           │            │
│  │    - Create LIMIT order (testnet)            │            │
│  │    - Wait for fill (30s timeout)             │            │
│  │    - Place stop-loss (STOP_MARKET)           │            │
│  │    - Place take-profit (TAKE_PROFIT_MARKET)  │            │
│  └─────────────────────────────────────────────┘            │
│                                                               │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  ↓
┌─────────────────────────────────────────────────────────────┐
│         PRICE PROVIDER (Mainnet Authority)                   │
│  - Binance MAINNET WebSocket                                 │
│  - Real-time price feed                                      │
│  - Bid/ask spread calculation                                │
│  - Used for: price validation, P&L calculation               │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  ↓
┌─────────────────────────────────────────────────────────────┐
│         EXECUTION ENGINE (Testnet)                           │
│  - Binance FUTURES TESTNET                                   │
│  - Place orders (no real money)                              │
│  - Check order status                                        │
│  - Cancel orders                                             │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  ↓
┌─────────────────────────────────────────────────────────────┐
│         POSITION MANAGER                                     │
│  - Track open positions (JSONL file)                         │
│  - Monitor stop-loss/take-profit fills                       │
│  - Calculate P&L (mainnet prices)                            │
│  - Update virtual balance on close                           │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  ↓
┌─────────────────────────────────────────────────────────────┐
│         BALANCE MANAGER                                      │
│  - Virtual balance tracking (per strategy)                   │
│  - Realized P&L accumulation                                 │
│  - Win/loss statistics                                       │
│  - ROI calculation                                           │
│  - JSON persistence                                          │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│         OBSERVABILITY (Logging & Monitoring)                 │
│  - Bot logs: logs/bot_<strategy>.log                         │
│  - Event logs: events/*.jsonl                                │
│  - Critical alerts: logs/critical_alerts.log                 │
│  - Health checker: component status tracking                 │
│  - Dashboard updater: real-time metrics                      │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow Sequence (Complete Trade Lifecycle)

```
1. [TradingView] Indicator generates signal (e.g., SMA 9/21 crossover)
   ↓
2. [TradingView] Alert triggers webhook POST to bot server
   ↓
3. [Webhook Server] Receives JSON payload on port 8004
   ↓
4. [Webhook Server] Validates secret, required fields
   ↓
5. [Webhook Server] Generates signal_id, adds timestamp
   ↓
6. [Webhook Server] Writes signal to JSONL queue (atomic append)
   ↓
7. [Trading Loop] Reads queue every 5 seconds
   ↓
8. [Signal Processor] Finds unprocessed signal
   ↓
9. [Signal Processor] Validates: age, symbol, timeframe, price (mainnet check)
   ↓
10. IF validation fails:
    ├─ Mark signal as processed with rejection reason
    └─ Continue to next signal
    ↓
11. IF validation passes:
    ↓
12. [Enhanced Order Manager] Checks circuit breaker (daily loss limit, consecutive losses)
    ↓
13. [Enhanced Order Manager] Checks position limits (max concurrent positions)
    ↓
14. [Risk Manager] Calculates position size (balance × % / 100 × leverage / price)
    ↓
15. [Position Size Validator] Validates calculated size vs webhook size
    ├─ IF webhook size > 1.5x expected: OVERRIDE, log critical alert
    ├─ Apply absolute max notional cap ($2,000)
    └─ Apply absolute max position % cap (50%)
    ↓
16. [Execution Engine] Fetches current mainnet price
    ↓
17. [Execution Engine] Places LIMIT order on testnet (price ± 0.05%)
    ↓
18. [Order Monitor] Waits for order fill (30s timeout)
    ↓
19. IF filled:
    ├─ [Position Manager] Creates position record
    ├─ [Position Manager] Saves to positions JSONL file
    ├─ [Order Manager] Places stop-loss order (STOP_MARKET)
    ├─ [Order Manager] Places take-profit order (TAKE_PROFIT_MARKET)
    └─ [Logger] Logs successful entry
    ↓
20. ELSE (not filled):
    ├─ [Order Manager] Cancels pending order
    └─ [Logger] Logs timeout
    ↓
21. [Position Monitoring Loop] Checks open positions every 5 seconds
    ↓
22. [Order Monitor] Checks SL/TP order status
    ↓
23. IF stop-loss filled:
    ├─ [Order Monitor] Gets fill price
    ├─ [Position Manager] Calculates P&L (using mainnet prices)
    ├─ [Balance Manager] Updates virtual balance (balance += pnl)
    ├─ [Position Manager] Marks position closed
    └─ [Logger] Logs stop-loss exit with P&L
    ↓
24. IF take-profit filled:
    ├─ [Order Monitor] Gets fill price
    ├─ [Position Manager] Calculates P&L (using mainnet prices)
    ├─ [Balance Manager] Updates virtual balance (balance += pnl)
    ├─ [Position Manager] Marks position closed
    └─ [Logger] Logs take-profit exit with P&L
    ↓
25. [Signal Archiver] (Every 24 hours)
    ├─ Archives processed signals older than 7 days
    ├─ Compresses to .jsonl.gz
    ├─ Rewrites queue with only active signals
    └─ Deletes archive files older than 30 days
    ↓
26. [Dashboard Updater] (Every 60 seconds)
    ├─ Calculates performance metrics
    ├─ Updates dashboard/monitoring UI
    └─ Logs statistics
```

---

## 🎯 Multi-Strategy Configuration

### Active Strategies (Independent Bots)

The system runs **multiple concurrent bot processes**, each with:
- Unique configuration file
- Independent webhook port
- Separate virtual balance
- Isolated signal queue
- Individual position tracking
- Independent risk management

### Strategy #1: Institutional Flow Hybrid

**Config:** `config_institutional_flow_hybrid.json`

```json
{
  "strategy_name": "institutional_flow_hybrid",
  "virtual_balance": 500.0,
  "webhook": {
    "port": 8001
  },
  "risk": {
    "position_size_value": 21.0,
    "max_positions": 5,
    "absolute_max_notional_usd": 2000
  },
  "strategies": {
    "enabled": ["institutional_flow_hybrid"],
    "allow_opposite_signals": true,
    "signal_expiry_seconds": 900
  }
}
```

**Indicator:** Volume profile + smart money concepts (order flow analysis)

**Timeframes:** 5m, 15m, 1h

**Entry Conditions:**
- High volume zones identified
- Institutional buying/selling detected
- Momentum confirmation (RSI, MACD)

**Performance (Last 7 Days):**
- **Signals:** 3,524 (highest volume)
- **Trades:** 14
- **Conversion:** 0.40%
- **P&L:** +$1.27 (9 wins, 5 losses, 64% WR)

**PID:** 1837656 (running on port 8001)

### Strategy #2: Squeeze Flow Expansion

**Config:** `config_squeeze_flow_expansion.json`

```json
{
  "strategy_name": "squeeze_flow_expansion",
  "virtual_balance": 500.0,
  "webhook": {
    "port": 8004
  },
  "risk": {
    "position_size_value": 21.0,
    "max_positions": 5,
    "absolute_max_notional_usd": 2000
  },
  "strategies": {
    "enabled": ["squeeze_flow_expansion"],
    "allow_opposite_signals": true,
    "signal_expiry_seconds": 900
  }
}
```

**Indicator:** Bollinger Bands squeeze + momentum breakout

**Timeframes:** 15m, 1h

**Entry Conditions:**
- Bollinger Bands squeeze (low volatility compression)
- Squeeze release (bands expanding)
- Momentum breakout direction (EMA crossover)
- Volume surge confirmation

**Performance (Last 7 Days):**
- **Signals:** 65
- **Trades:** 11
- **Conversion:** 16.92%
- **P&L:** +$2.65 (7 wins, 4 losses, 64% WR)

**PID:** 1838076 (running on port 8004)

### Strategy #3: SMA Crossover 9/21

**Config:** `config_sma_crossover_9_21.json`

```json
{
  "strategy_name": "sma_crossover_9_21",
  "virtual_balance": 500.0,
  "webhook": {
    "port": 8003
  },
  "risk": {
    "position_size_value": 15.0,
    "max_positions": 5,
    "absolute_max_notional_usd": 2000
  },
  "strategies": {
    "enabled": ["sma_crossover_9_21"],
    "signal_expiry_seconds": 600
  }
}
```

**Indicator:** Fast/slow moving average crossover (classic trend following)

**Timeframes:** 1h, 4h

**Entry Conditions:**
- SMA(9) crosses above SMA(21) → LONG
- SMA(9) crosses below SMA(21) → SHORT
- Volume above average (filter false signals)

**Performance (Last 7 Days):**
- **Signals:** 30
- **Trades:** 7
- **Conversion:** 23.33%
- **P&L:** +$0.17 (3 wins, 4 losses, 43% WR)

**PID:** 1838075 (running on port 8003)

### Strategy #4: Supertrend BTC 4H

**Config:** `config_supertrend_btc_4h.json`

```json
{
  "strategy_name": "supertrend_btc_4h",
  "virtual_balance": 500.0,
  "webhook": {
    "port": 8002
  },
  "risk": {
    "position_size_value": 10.0,
    "max_positions": 3
  },
  "trading": {
    "symbols_allowed": ["BTCUSDT"]
  }
}
```

**Indicator:** ATR-based Supertrend (trend-following on higher timeframe)

**Timeframes:** 4h only

**Entry Conditions:**
- Supertrend indicator flips (trend change)
- ATR-based stop placement
- Trend strength confirmation

**Performance (Last 7 Days):**
- **Signals:** 8
- **Trades:** 4
- **Conversion:** 50.00%
- **P&L:** +$1.15 (3 wins, 1 loss, 75% WR)

**PID:** 1838065 (running on port 8002)

### Strategy #5: OBV WaveTrend Scalper (DISABLED)

**Status:** ❌ **STRATEGY DISABLED** (Critical position sizing bug)

**Config:** `config_obv_wavetrend_scalper.json`

```json
{
  "strategies": {
    "enabled": []  // DISABLED due to 1085% oversized position bug
  }
}
```

**Issue Identified:**
- Position sizing calculation produced notional values up to **1085% over limit**
- Example: Expected $1,500 notional → Actual $17,782 (9.2 ETH instead of 0.776 ETH)
- Caused 99% of all bot losses (-$294.65 from one strategy alone)

**Root Cause:**
- Bot was treating USD position size as coin quantity
- `position_size = $1,500` interpreted as `1,500 coins` instead of `$1,500 worth of coins`

**Fix Applied:**
- Position Size Validator now overrides any webhook position_size values
- Always recalculates based on internal risk rules
- Applies absolute hard caps ($2,000 max notional, 50% max balance)

**Future:** Will be re-enabled after thorough testing with Position Size Validator

---

## 💼 Trade Execution Logic

### Order Flow Diagram

```
Signal Received
    ↓
Circuit Breaker Check
    ├─ Daily loss > 2%? → REJECT (wait cooldown)
    ├─ Consecutive losses > 5? → REJECT (wait cooldown)
    └─ OK → Continue
    ↓
Position Limit Check
    ├─ Open positions >= max_positions? → REJECT
    ├─ Symbol already has position + opposite signal? → Handle per config
    └─ OK → Continue
    ↓
Position Size Calculation
    ├─ Risk Manager: balance × % / 100 × leverage / price
    ├─ Position Size Validator: Override check + hard caps
    └─ Final validated size
    ↓
Mainnet Price Fetch
    ├─ Get current BTC/ETH/SOL price from mainnet
    ├─ Calculate spread
    └─ Determine limit price (market ± 0.05%)
    ↓
Create LIMIT Order (Testnet)
    ├─ Symbol, side, amount, limit_price
    ├─ Submit to Binance TESTNET
    └─ Get order_id
    ↓
Wait for Fill (30s timeout)
    ├─ Poll order status every 1s
    ├─ IF filled → Continue
    └─ IF timeout → Cancel order, REJECT signal
    ↓
Position Created
    ├─ Save to positions JSONL file
    ├─ Record: entry_price, qty, signal_id, timestamp
    └─ Continue
    ↓
Place Stop-Loss Order (STOP_MARKET)
    ├─ Calculate SL price (signal['stop_loss'] or ATR-based)
    ├─ Create STOP_MARKET order (close position when SL hit)
    └─ Link to position
    ↓
Place Take-Profit Order (TAKE_PROFIT_MARKET)
    ├─ Calculate TP price (signal['take_profit'] or risk-reward ratio)
    ├─ Create TAKE_PROFIT_MARKET order (close position when TP hit)
    └─ Link to position
    ↓
Position Monitoring (Every 5s)
    ├─ Check SL order status
    ├─ Check TP order status
    ├─ IF filled → Calculate P&L → Close position → Update balance
    └─ Continue monitoring
```

### Order Types Used

#### 1. Entry Order: LIMIT
```python
# Create LIMIT order (better price than market)
order = binance.create_limit_order(
    symbol='BTCUSDT',
    side='BUY' or 'SELL',
    amount=position_size,
    price=limit_price  # Mainnet ± 0.05%
)

# Why LIMIT?
# - Better fill price (save on spread)
# - Avoids slippage
# - No urgent need for instant fill (can wait 30s)
```

#### 2. Stop-Loss: STOP_MARKET
```python
# Triggered when price reaches stop level
stop_order = binance.create_order(
    symbol='BTCUSDT',
    type='STOP_MARKET',
    side='SELL' if long else 'BUY',
    stopPrice=stop_loss_price,
    closePosition=True
)

# Why STOP_MARKET?
# - Guaranteed execution (market order when stop hit)
# - Critical risk management (must exit at stop)
# - Accepts slippage to ensure position closed
```

#### 3. Take-Profit: TAKE_PROFIT_MARKET
```python
# Triggered when price reaches target
tp_order = binance.create_order(
    symbol='BTCUSDT',
    type='TAKE_PROFIT_MARKET',
    side='SELL' if long else 'BUY',
    stopPrice=take_profit_price,
    closePosition=True
)
```

### Position Sizing Formula (Step-by-Step)

```python
# Input values
balance = 500.0              # Virtual balance
position_size_pct = 21.0     # 21% of balance per trade
leverage = 1                 # 1x leverage (no leverage)
entry_price = 67850.50       # BTC price

# Step 1: Calculate USD size
usd_size_base = balance * (position_size_pct / 100)
# = 500 * 0.21 = $105

# Step 2: Apply leverage
usd_size_leveraged = usd_size_base * leverage
# = $105 * 1 = $105

# Step 3: Convert to BTC contracts
contracts = usd_size_leveraged / entry_price
# = 105 / 67850.50 = 0.001547 BTC

# Step 4: Validate with Position Size Validator
if contracts * entry_price > absolute_max_notional_usd:  # $2,000 max
    contracts = absolute_max_notional_usd / entry_price

if contracts * entry_price > balance * (absolute_max_position_pct / 100):  # 50% max
    contracts = (balance * 0.5) / entry_price

# Final position size: 0.001547 BTC (~$105 notional)
```

### Stop-Loss & Take-Profit Calculation

**Method 1: From TradingView Signal (Preferred)**
```python
# TradingView indicator calculates SL/TP based on indicator logic
signal = {
    'price': 67850.50,
    'stop_loss': 66800.00,   # From Pine Script calculation
    'take_profit': 69500.00  # From Pine Script calculation
}

# Use these values directly
stop_loss = float(signal['stop_loss'])       # 66800.00
take_profit = float(signal['take_profit'])   # 69500.00

# Risk:Reward
risk = abs(entry_price - stop_loss)          # 1050.50
reward = abs(take_profit - entry_price)      # 1649.50
risk_reward_ratio = reward / risk            # 1.57:1
```

**Method 2: ATR-Based (Fallback)**
```python
# If signal doesn't provide SL/TP
atr_14 = calculate_atr(symbol, timeframe, period=14)  # ATR(14) = $500

if signal['side'] == 'LONG':
    stop_loss = entry_price - (atr_14 * 1.5)      # Entry - 1.5 ATR
    take_profit = entry_price + (atr_14 * 2.5)    # Entry + 2.5 ATR
else:  # SHORT
    stop_loss = entry_price + (atr_14 * 1.5)
    take_profit = entry_price - (atr_14 * 2.5)

# Risk:Reward = 1.5 ATR : 2.5 ATR = 1:1.67
```

---

## ⚙️ Configuration & Parameters

### Configuration File Structure

```json
{
  "strategy_name": "squeeze_flow_expansion",
  "virtual_balance": 500.0,
  
  "exchange": {
    "name": "binance",
    "type": "futures",
    "testnet": true
  },
  
  "webhook": {
    "host": "0.0.0.0",
    "port": 8004,
    "secret": "squeeze_tradingview_cluster_2026_secure"
  },
  
  "risk": {
    "position_size_type": "percentage",
    "position_size_value": 21.0,
    "max_positions": 5,
    "max_symbol_exposure": 100.0,
    "stop_loss_buffer_pct": 0.1,
    "min_position_usd": 100.0,
    "absolute_max_notional_usd": 2000,
    "absolute_max_position_pct": 50
  },
  
  "strategies": {
    "enabled": ["squeeze_flow_expansion"],
    "allow_opposite_signals": true,
    "signal_expiry_seconds": 900
  },
  
  "trading": {
    "symbols_allowed": ["BTCUSDT", "SOLUSDT", "ETHUSDT"],
    "timeframes_allowed": ["5m", "15m", "30m", "1h", "2h", "4h", "1d"],
    "leverage": 1
  },
  
  "storage": {
    "signals_queue": "storage/signals_squeeze_flow_expansion.jsonl",
    "positions": "storage/positions_squeeze_flow_expansion.jsonl",
    "balance": "storage/balance_squeeze_flow_expansion.json"
  },
  
  "logging": {
    "level": "INFO",
    "file": "logs/bot_squeeze_flow_expansion.log",
    "console": true
  },
  
  "circuit_breaker": {
    "daily_loss_limit_pct": 2.0,
    "max_consecutive_losses": 5,
    "cooldown_minutes": 60
  },
  
  "risk_control": {
    "max_leverage": 1,
    "max_notional_per_symbol": 500,
    "api_error_threshold": 10,
    "api_error_window_seconds": 300
  },
  
  "reconciliation": {
    "tolerance_qty": 0.001,
    "tolerance_notional": 1.0,
    "check_interval_seconds": 15
  },
  
  "price_source": {
    "type": "mainnet",
    "description": "Fetch prices from mainnet for accuracy"
  }
}
```

### Key Parameter Explanations

#### Virtual Balance
```json
"virtual_balance": 500.0
```
- Simulated trading balance (USDT)
- Independent per strategy
- Tracks realized/unrealized P&L
- Not tied to testnet balance (which can be inconsistent)

#### Position Sizing
```json
"position_size_type": "percentage",
"position_size_value": 21.0
```
- **percentage:** Size as % of balance (21% = $105 on $500 balance)
- **fixed:** Fixed USD amount per trade
- **risk_based:** Based on stop-loss distance and risk %

#### Max Positions
```json
"max_positions": 5
```
- Maximum concurrent open positions
- Prevents over-exposure
- When limit reached, new signals rejected
- **Recent Update:** Increased from 3-4 to 5 (improved conversion rate)

#### Absolute Hard Caps
```json
"absolute_max_notional_usd": 2000,
"absolute_max_position_pct": 50
```
- **absolute_max_notional_usd:** Never exceed this notional value (even if calculation suggests higher)
- **absolute_max_position_pct:** Never risk more than this % of balance in single trade

**Purpose:** Prevent catastrophic losses from position sizing bugs

#### Allow Opposite Signals
```json
"allow_opposite_signals": true
```
- **true:** Can open SHORT position even if LONG position exists on same symbol (hedge)
- **false:** Must close existing position before opening opposite direction

**Recent Update:** Changed from `false` → `true` (improved flexibility)

#### Signal Expiry
```json
"signal_expiry_seconds": 900
```
- Signals older than this are rejected (price may have moved significantly)
- Default: 300-600s (5-10 minutes)
- High-volume strategies: 900s (15 minutes) for better conversion

**Recent Update:** Extended from 300s → 900s (reduced false rejections)

#### Circuit Breaker
```json
"daily_loss_limit_pct": 2.0,
"max_consecutive_losses": 5,
"cooldown_minutes": 60
```
- **daily_loss_limit_pct:** Stop trading if daily loss exceeds 2% of balance ($10 on $500)
- **max_consecutive_losses:** Stop trading after 5 consecutive losing trades
- **cooldown_minutes:** Wait this long before resuming trading

**Purpose:** Prevent extended drawdowns, force review of strategy

---

## 📁 File Structure

### Project Directory

```
/home/ubuntu/tradingview-bot/
│
├── main_enhanced.py                  # Main bot entry point
├── .env                              # API keys, secrets
├── requirements.txt                  # Python dependencies
│
├── config/                           # Strategy configurations
│   ├── config_institutional_flow_hybrid.json
│   ├── config_squeeze_flow_expansion.json
│   ├── config_sma_crossover_9_21.json
│   ├── config_supertrend_btc_4h.json
│   └── config_obv_wavetrend_scalper.json (DISABLED)
│
├── core/                             # Core trading logic
│   ├── enhanced_order_manager.py     # Order execution (412 lines)
│   ├── position_size_validator.py    # Position size protection (227 lines)
│   ├── signal_processor.py           # Signal validation (305 lines)
│   ├── risk_manager.py               # Risk calculations (178 lines)
│   ├── position_manager.py           # Position tracking (287 lines)
│   ├── balance_manager.py            # Virtual balance tracking (156 lines)
│   ├── webhook_server.py             # Flask webhook receiver (213 lines)
│   ├── circuit_breaker.py            # Circuit breaker logic (124 lines)
│   └── order_monitor.py              # Order fill monitoring (198 lines)
│
├── exchange/                         # Exchange integration
│   ├── binance_client.py             # Binance API wrapper (testnet)
│   ├── price_provider.py             # Mainnet price fetcher
│   └── execution_engine.py           # Order execution (testnet)
│
├── utils/                            # Utility modules
│   ├── signal_archiver.py            # Signal queue cleanup (315 lines)
│   ├── logger.py                     # Logging setup
│   ├── event_logger.py               # Event logging (JSONL)
│   ├── health_checker.py             # Component health tracking
│   ├── dashboard_updater.py          # Metrics dashboard
│   ├── instance_lock.py              # Prevent duplicate processes
│   └── telegram_alerter.py           # Telegram notifications
│
├── storage/                          # Persistent data
│   ├── signals_institutional_flow_hybrid.jsonl    # Signal queue (Flow)
│   ├── signals_squeeze_flow_expansion.jsonl       # Signal queue (Squeeze)
│   ├── signals_sma_crossover_9_21.jsonl           # Signal queue (SMA)
│   ├── positions_institutional_flow_hybrid.jsonl  # Position tracking (Flow)
│   ├── positions_squeeze_flow_expansion.jsonl     # Position tracking (Squeeze)
│   ├── balance_institutional_flow_hybrid.json     # Virtual balance (Flow)
│   ├── balance_squeeze_flow_expansion.json        # Virtual balance (Squeeze)
│   └── archive/                      # Archived signals (7+ days old)
│       ├── signals_archive_20260218_054427.jsonl.gz (138 KB)
│       └── ...
│
├── logs/                             # Bot logs
│   ├── bot_institutional_flow_hybrid.log (12 MB)
│   ├── bot_squeeze_flow_expansion.log (8 MB)
│   ├── bot_sma_crossover_9_21.log (4 MB)
│   ├── critical_alerts.log           # Position size anomalies, critical errors
│   └── ...
│
├── deploy/                           # Deployment scripts
│   ├── systemd/                      # Systemd service files
│   │   ├── tradingview-bot-flow.service
│   │   ├── tradingview-bot-squeeze.service
│   │   └── tradingview-bot-sma.service
│   ├── nginx/                        # Nginx configs (if using reverse proxy)
│   └── deploy_critical_fixes.sh      # Deployment automation script
│
├── tests/                            # Unit tests
│   └── ...
│
└── *.pine                            # TradingView Pine Script indicators
    ├── institutional_matrix_webhook.pine
    ├── squeeze_flow_expansion_webhook.pine
    ├── sma_crossover_9_21_webhook.pine
    ├── enhanced_atr_supertrend_webhook.pine
    └── ...
```

### Key File Descriptions

#### `main_enhanced.py` (Main Entry Point - 372 lines)
- Initializes all components
- Starts webhook server (background thread)
- Runs trading loop (read signals → process → execute)
- Monitors positions (check SL/TP fills)
- Runs signal archiver (every 24 hours)
- Handles graceful shutdown (SIGTERM/SIGINT)
- Instance locking (prevents duplicate processes)

#### `core/enhanced_order_manager.py` (Order Execution - 412 lines)
**Functions:**
- `process_signals()`: Main signal processing entry point
- `can_execute_signal()`: Circuit breaker + position limit checks
- `calculate_position_size()`: Position sizing with validator
- `execute_order()`: Create LIMIT order, wait for fill
- `place_stop_loss_order()`: Place STOP_MARKET order
- `place_take_profit_order()`: Place TAKE_PROFIT_MARKET order
- `monitor_positions_with_mainnet_prices()`: Position monitoring

#### `core/position_size_validator.py` (Security Layer - 227 lines)
**Functions:**
- `validate_and_recalculate()`: Validate position size from signal
- `_log_critical_alert()`: Write to critical_alerts.log
- `_check_webhook_size_anomaly()`: Detect 1000%+ oversized positions
- `_apply_hard_caps()`: Apply absolute max notional/position %

**Purpose:** Prevent catastrophic position sizing bugs (OBV incident)

#### `utils/signal_archiver.py` (Queue Management - 315 lines)
**Functions:**
- `archive_old_signals()`: Archive processed signals older than 7 days
- `_compress_archive()`: Gzip compression (saves 90% space)
- `_cleanup_old_archives()`: Delete archives older than 30 days
- `get_archive_stats()`: Statistics (files, size, signals)

**Results:**
- Queue size reduced: 3,525 → 243 signals (93% reduction)
- Disk space saved: 1.2 MB → 80 KB active + 138 KB archive
- Processing speed: 50% faster

---

## 📊 Monitoring & Observability

### Log Files

#### Bot Logs (`logs/bot_<strategy>.log`)

**Format:** Timestamped log entries with log level

**Example:**
```
2026-02-18 06:54:32,123 - enhanced_main_squeeze_flow_expansion - INFO - 🎯 Found 1 valid signals to execute
2026-02-18 06:54:32,456 - enhanced_order_manager - INFO - 💡 Calculated position size: 0.001547 BTC ($105.00 notional)
2026-02-18 06:54:32,789 - position_size_validator - INFO - ✓ Position size validated: 0.001547 BTC (within limits)
2026-02-18 06:54:33,012 - execution_engine - INFO - 📤 Placing LIMIT BUY order: BTCUSDT, qty=0.001547, price=67850.50
2026-02-18 06:54:33,345 - execution_engine - INFO - ✅ Order filled: BTCUSDT LONG @ $67850.50, qty=0.001547 BTC
2026-02-18 06:54:33,678 - position_manager - INFO - 📝 Position opened: pos_20260218_065433_BTCUSDT_LONG
2026-02-18 06:54:33,901 - enhanced_order_manager - INFO - 🛑 Stop-loss placed at $66800.00
2026-02-18 06:54:34,124 - enhanced_order_manager - INFO - 🎯 Take-profit placed at $69500.00
```

**What to Monitor:**
- `🎯 Found X valid signals` - Signal processing
- `💡 Calculated position size` - Position sizing
- `✅ Order filled` - Trade execution
- `🛑 Stop-loss hit` - Stop-loss exits
- `🎯 Take-profit hit` - Take-profit exits
- `⚠️ WARNING` - Non-critical issues (signal rejected, position limit)
- `❌ ERROR` - Critical issues (API failure, order timeout)

#### Critical Alerts (`logs/critical_alerts.log`)

**Purpose:** ONLY critical security/risk issues

**Format:** JSON lines (JSONL)

**Example:**
```json
{
  "timestamp": "2026-02-18T06:54:35.123456Z",
  "alert_type": "POSITION_SIZE_ANOMALY",
  "signal_id": "sig_20260218_065432_ETHUSDT_LONG",
  "symbol": "ETHUSDT",
  "webhook_size": 9.2,
  "webhook_notional": 17782.13,
  "expected_size": 0.776,
  "expected_notional": 1500.00,
  "ratio": 11.85,
  "action": "OVERRIDE_WITH_SAFE_SIZE"
}
```

**When to Check:**
- Daily review for any POSITION_SIZE_ANOMALY alerts
- After deploying new TradingView indicators
- If unexpected large losses occur

### Monitoring Commands

#### Check Bot Status
```bash
# View all bot processes
ps aux | grep main_enhanced.py | grep -v grep

# Check specific strategy
ps aux | grep squeeze_flow_expansion

# View resource usage
ps -p <PID> -o %cpu,%mem,rss,etime
```

#### View Live Logs
```bash
# Tail specific strategy log
tail -f /home/ubuntu/tradingview-bot/logs/bot_squeeze_flow_expansion.log

# Filter for signals
tail -f logs/bot_squeeze_flow_expansion.log | grep '🎯 Found'

# Filter for trades
tail -f logs/bot_squeeze_flow_expansion.log | grep '✅ Order filled'

# Filter for exits
tail -f logs/bot_squeeze_flow_expansion.log | grep '🛑 Stop-loss\|🎯 Take-profit'
```

#### Check Signal Queue
```bash
# Count active signals
wc -l storage/signals_squeeze_flow_expansion.jsonl

# Count unprocessed signals
greppedcat storage/signals_squeeze_flow_expansion.jsonl | grep '"processed": false' | wc -l

# View latest signal
tail -1 storage/signals_squeeze_flow_expansion.jsonl | python3 -m json.tool
```

#### Check Position Status
```bash
# Count open positions
grep '"status": "OPEN"' storage/positions_squeeze_flow_expansion.jsonl | wc -l

# View open positions
grep '"status": "OPEN"' storage/positions_squeeze_flow_expansion.jsonl | python3 -m json.tool

# Check latest position
tail -1 storage/positions_squeeze_flow_expansion.jsonl | python3 -m json.tool
```

#### Check Virtual Balance
```bash
# View balance file
cat storage/balance_squeeze_flow_expansion.json | python3 -m json.tool

# Example output:
{
  "balance": 502.65,
  "initial_balance": 500.0,
  "total_trades": 11,
  "winning_trades": 7,
  "losing_trades": 4,
  "realized_pnl": 2.65,
  "roi_percent": 0.53,
  "win_rate_percent": 63.64
}
```

### Performance Metrics

#### Key Metrics to Track

1. **Signal Conversion Rate**
```python
conversion_rate = (trades_executed / signals_received) * 100

# Target: 5-15% (depends on strategy)
# Below 1%: Check signal expiry, position limits
```

2. **Win Rate**
```python
win_rate = (winning_trades / total_trades) * 100

# Target: 55-65% (breakeven with R:R > 1:1)
# Below 50%: Review strategy logic
```

3. **Realized P&L**
```python
realized_pnl = sum(all_closed_position_pnl)

# Target: Positive over 30+ trades
# Negative: Review risk management, stop-loss placement
```

4. **ROI %**
```python
roi = ((current_balance - initial_balance) / initial_balance) * 100

# Target: 5-20% per month (realistic for crypto)
# >50% per month: Unsustainable (likely luck)
```

5. **Average Trade Duration**
```python
avg_duration = sum(position_close_time - position_open_time) / total_trades

# Target: Aligned with strategy timeframe
# Squeeze (15m): 2-6 hours
# Supertrend (4h): 12-48 hours
```

### Health Checks

**Health Checker (`utils/health_checker.py`):**

```python
# Check bot health status
health_status = {
    'webhook_server': 'healthy',  # Receiving signals
    'signal_processor': 'healthy',  # Processing queue
    'execution_engine': 'healthy',  # Placing orders
    'price_provider': 'healthy',  # Mainnet connection
    'position_monitor': 'healthy',  # Monitoring fills
    'circuit_breaker': 'active',  # Risk protection
    'last_heartbeat': '2026-02-18T06:54:35Z'
}
```

**Check Health:**
```bash
# View health status in logs
tail -50 logs/bot_squeeze_flow_expansion.log | grep 'Health'
```

---

## 🛡️ Risk Management

### Multi-Layer Risk Controls

#### Layer 1: Position Sizing (Risk Manager)
```python
# Base risk: 15-21% of balance per trade
position_size_pct = 21.0  # Squeeze Flow Expansion
position_size = balance * 0.21  # $105 on $500 balance

# Apply leverage (usually 1x)
leveraged_size = position_size * leverage

# Convert to contracts
contracts = leveraged_size / entry_price

# Result: 0.001547 BTC ($105 notional) on $500 balance
```

#### Layer 2: Position Size Validator (Security Layer)
```python
# CRITICAL PROTECTION: Override dangerous sizes

# Check 1: Webhook size vs calculated size
if webhook_size / calculated_size > 1.5:
    # OVERRIDE: Use calculated size
    # LOG: Critical alert
    # Example: Webhook says 9.2 ETH, calculated is 0.776 ETH
    final_size = calculated_size  # Use safe value

# Check 2: Absolute max notional
if contracts * price > 2000:
    # CAP: Reduce size to $2,000 max
    contracts = 2000 / price

# Check 3: Absolute max % of balance
if contracts * price > balance * 0.5:
    # CAP: Reduce size to 50% max
    contracts = (balance * 0.5) / price

# Result: Guaranteed safe position size
```

#### Layer 3: Position Limits
```python
# Max concurrent positions
max_positions = 5  # Most strategies (recently increased from 3-4)

# Check before opening position
if len(open_positions) >= max_positions:
    logger.warning("Max positions reached, rejecting signal")
    return False

# Prevents over-exposure
# Example: 5 positions × $105 each = $525 total exposure on $500 balance
```

#### Layer 4: Circuit Breaker
```python
# Trigger 1: Daily loss limit
daily_loss_limit = balance * 0.02  # 2% = $10 on $500 balance

if daily_realized_pnl < -daily_loss_limit:
    circuit_breaker.activate(
        reason='DAILY_LOSS_LIMIT',
        cooldown_minutes=60
    )
    # Stop trading for 60 minutes
    # Force review of strategy

# Trigger 2: Consecutive losses
consecutive_losses = count_consecutive_losing_trades()

if consecutive_losses >= 5:
    circuit_breaker.activate(
        reason='MAX_CONSECUTIVE_LOSSES',
        cooldown_minutes=60
    )
    # Stop trading for 60 minutes
    # Strategy may be losing edge
```

#### Layer 5: Price Validation (Mainnet Authority)
```python
# Validate signal price vs current mainnet price
signal_price = float(signal['price'])  # Price from TradingView (may be stale)
mainnet_price = price_provider.get_current_price(symbol)  # Real-time

deviation_pct = abs(signal_price - mainnet_price) / mainnet_price * 100

if deviation_pct > 5:  # Default: 5-8% max deviation
    logger.warning(f"Price deviation {deviation_pct:.2f}% too high")
    mark_signal_processed(signal, status='PRICE_MISMATCH')
    return None

# Use mainnet price for execution (more accurate)
```

#### Layer 6: Signal Expiry
```python
# Reject stale signals
signal_age = now - signal_timestamp

if signal_age > signal_expiry_seconds:  # 300-900s depending on strategy
    logger.warning(f"Signal expired: {signal_age:.0f}s old")
    mark_signal_processed(signal, status='EXPIRED')
    return None

# Prevents trading on outdated market conditions
```

#### Layer 7: Stop-Loss (Trade Level)
```python
# Every trade has stop-loss (no exceptions)

# Method 1: From TradingView indicator
stop_loss = float(signal['stop_loss'])

# Method 2: ATR-based fallback
if not stop_loss:
    atr = calculate_atr(symbol, timeframe, 14)
    stop_loss = entry_price - (atr * 1.5) if long else entry_price + (atr * 1.5)

# Place STOP_MARKET order immediately after entry
place_stop_loss_order(position, stop_loss)

# Limits loss per trade to acceptable amount
```

---

## 🚀 Setup & Deployment

### Prerequisites

#### System Requirements
- **OS:** Ubuntu 20.04+ (Linux)
- **Python:** 3.8+
- **RAM:** 2 GB minimum (bot uses ~150 MB per strategy)
- **Storage:** 10 GB (for logs and signal queues)
- **Network:** Stable internet connection (WebSockets + API calls)

#### Accounts Required
1. **TradingView Premium:** For webhook alerts
2. **Binance Futures Testnet:** For order execution (testnet.binancefuture.com)

### Installation Steps

#### 1. Clone Repository
```bash
cd /home/ubuntu
git clone https://github.com/your-repo/tradingview-bot.git
cd tradingview-bot
```

#### 2. Install Python Dependencies
```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install packages
pip install -r requirements.txt

# Key packages:
# - flask (webhook server)
# - ccxt (Binance API)
# - python-dotenv (environment variables)
# - requests (HTTP requests mainnet prices)
```

#### 3. Configure API Keys

**Create `.env` file:**
```bash
cat > .env << EOF
# Binance Testnet API Keys
BINANCE_TESTNET_API_KEY=your_testnet_api_key
BINANCE_TESTNET_API_SECRET=your_testnet_secret

# Telegram Alerts (optional)
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Environment
ENVIRONMENT=production
EOF

chmod 600 .env
```

**Get Binance Testnet API Keys:**
1. Visit: https://testnet.binancefuture.com/
2. Login with email
3. Go to: API Management → Generate HMAC Key
4. Copy API Key and Secret
5. Paste into `.env` file

#### 4. Configure Strategy

Edit strategy config file (e.g., `config/config_squeeze_flow_expansion.json`):

```json
{
  "strategy_name": "squeeze_flow_expansion",
  "virtual_balance": 500.0,  // Starting balance
  "webhook": {
    "port": 8004,  // Unique port per strategy
    "secret": "your_secure_webhook_secret_here"
  },
  "risk": {
    "position_size_value": 21.0,  // 21% per trade
    "max_positions": 5
  },
  "trading": {
    "symbols_allowed": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
    "leverage": 1
  }
}
```

#### 5. Create Systemd Service

**Create service file:**
```bash
sudo nano /etc/systemd/system/tradingview-bot-squeeze.service
```

**Service configuration:**
```ini
[Unit]
Description=TradingView Bot - Squeeze Flow Expansion
After=network.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/tradingview-bot
Environment="PATH=/home/ubuntu/tradingview-bot/venv/bin:/usr/local/bin:/usr/bin:/bin"
Environment="PYTHONUNBUFFERED=1"
EnvironmentFile=/home/ubuntu/tradingview-bot/.env

ExecStart=/home/ubuntu/tradingview-bot/venv/bin/python3 -u main_enhanced.py --config config/config_squeeze_flow_expansion.json

Restart=always
RestartSec=10
StartLimitInterval=300
StartLimitBurst=5

StandardOutput=append:/home/ubuntu/tradingview-bot/logs/bot_squeeze_flow_expansion.log
StandardError=append:/home/ubuntu/tradingview-bot/logs/bot_squeeze_flow_expansion_error.log

[Install]
WantedBy=multi-user.target
```

#### 6. Start the Bot

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable auto-start on boot
sudo systemctl enable tradingview-bot-squeeze.service

# Start the bot
sudo systemctl start tradingview-bot-squeeze.service

# Check status
sudo systemctl status tradingview-bot-squeeze.service

# View logs
tail -f logs/bot_squeeze_flow_expansion.log
```

#### 7. Verify Bot Running

```bash
# Check process
ps aux | grep squeeze_flow_expansion | grep -v grep

# Should see:
# ubuntu   1838076  2.5  3.1  627392 151284 ?  Ssl  05:45  0:01 /home/ubuntu/tradingview-bot/venv/bin/python3 -u main_enhanced.py --config config/config_squeeze_flow_expansion.json

# Check webhook server
curl -X POST http://localhost:8004/health

# Should return:
# {"status": "healthy", "strategy": "squeeze_flow_expansion"}
```

---

## 📡 TradingView Alert Configuration

### Pine Script Webhook Setup

#### 1. Create Indicator in TradingView

**Example: Squeeze Flow Expansion (Pine Script):**

```pine
//@version=5
indicator("Squeeze Flow Expansion - Webhook", overlay=true)

// Parameters
bb_length = input.int(20, "BB Length")
bb_mult = input.float(2.0, "BB Multiplier")
kc_length = input.int(20, "KC Length")
kc_mult = input.float(1.5, "KC Multiplier")
mom_length = input.int(12, "Momentum Length")

// Bollinger Bands
basis = ta.sma(close, bb_length)
dev = bb_mult * ta.stdev(close, bb_length)
bb_upper = basis + dev
bb_lower = basis - dev

// Keltner Channels
kc_basis = ta.sma(close, kc_length)
range_val = ta.tr
kc_range = ta.sma(range_val, kc_length)
kc_upper = kc_basis + (kc_mult * kc_range)
kc_lower = kc_basis - (kc_mult * kc_range)

// Squeeze Detection
squeeze_on = (bb_lower > kc_lower) and (bb_upper < kc_upper)
squeeze_off = (bb_lower < kc_lower) or (bb_upper > kc_upper)

// Momentum
mom = ta.linreg(close - ta.sma(close, mom_length), mom_length, 0)

// Entry Signals
longCondition = ta.crossover(mom, 0) and not squeeze_on
shortCondition = ta.crossunder(mom, 0) and not squeeze_on

// Calculate Stop-Loss & Take-Profit
atr = ta.atr(14)
long_stop = close - (atr * 1.5)
long_tp = close + (atr * 2.5)
short_stop = close + (atr * 1.5)
short_tp = close - (atr * 2.5)

// Plot signals
plotshape(longCondition, "Long", shape.triangleup, location.belowbar, color.green, size=size.small)
plotshape(shortCondition, "Short", shape.triangledown, location.abovebar, color.red, size=size.small)

// Alerts
if longCondition
    alert(
        '{"secret":"squeeze_tradingview_cluster_2026_secure","strategy":"squeeze_flow_expansion","side":"LONG","symbol":"' + syminfo.ticker + '","price":"' + str.tostring(close) + '","timeframe":"' + timeframe.period + '","stop_loss":"' + str.tostring(long_stop) + '","take_profit":"' + str.tostring(long_tp) + '"}',
        alert.freq_once_per_bar_close
    )

if shortCondition
    alert(
        '{"secret":"squeeze_tradingview_cluster_2026_secure","strategy":"squeeze_flow_expansion","side":"SHORT","symbol":"' + syminfo.ticker + '","price":"' + str.tostring(close) + '","timeframe":"' + timeframe.period + '","stop_loss":"' + str.tostring(short_stop) + '","take_profit":"' + str.tostring(short_tp) + '"}',
        alert.freq_once_per_bar_close
    )
```

#### 2. Create Alert in TradingView

1. **Add indicator to chart** (Indicators → Search "Squeeze Flow Expansion")
2. **Right-click on chart** → "Add Alert"
3. **Configure alert:**
   - **Condition:** Select indicator alert (will trigger on `alert()` calls)
   - **Options:** Once Per Bar Close
   - **Alert actions:** Webhook URL
   - **Webhook URL:** `http://13.236.143.201:8004/webhook/tradingview`
   - **Message:** (Leave blank, indicator sends JSON in `alert()`)
4. **Click "Create"**

#### 3. Test Alert

**Send test signal manually:**
```bash
curl -X POST http://13.236.143.201:8004/webhook/tradingview \
  -H "Content-Type: application/json" \
  -d '{
    "secret": "squeeze_tradingview_cluster_2026_secure",
    "strategy": "squeeze_flow_expansion",
    "side": "LONG",
    "symbol": "BTCUSDT",
    "price": "67850.50",
    "timeframe": "15m",
    "stop_loss": "66800.00",
    "take_profit": "69500.00"
  }'

# Should return:
# {"status": "success", "signal_id": "sig_20260218_065432_BTCUSDT_LONG"}
```

**Check bot log:**
```bash
tail -20 logs/bot_squeeze_flow_expansion.log

# Should see:
# 2026-02-18 06:54:32,123 - webhook_server - INFO - 🌐 Signal received: sig_20260218_065432_BTCUSDT_LONG
# 2026-02-18 06:54:32,456 - webhook_server - INFO - ✅ Signal written to queue
```

---

## 🐛 Troubleshooting

### Common Issues

#### Bot Not Starting
```bash
# Check service status
sudo systemctl status tradingview-bot-squeeze.service

# View error logs
tail -50 logs/bot_squeeze_flow_expansion_error.log

# Common causes:
# - Missing .env file → Create .env with API keys
# - Invalid config JSON → Validate JSON syntax
# - Port already in use → Change webhook port in config
```

#### Signals Not Executing
```bash
# Check signal queue
tail -10 storage/signals_squeeze_flow_expansion.jsonl | python3 -m json.tool

# Check bot log for rejection reasons
grep "REJECTED\|Cannot open" logs/bot_squeeze_flow_expansion.log | tail -20

# Common reasons:
# - "Max positions reached" → Wait for position to close or increase max_positions
# - "Price deviation too high" → Increase max_deviation_pct in config
# - "Signal expired" → Increase signal_expiry_seconds
# - "Daily loss limit hit" → Circuit breaker active, wait for cooldown
```

#### Webhook Not Receiving Signals
```bash
# Test webhook endpoint
curl http://localhost:8004/health

# If no response:
# - Check if bot process running
# - Check firewall rules (allow inbound on port 8004)
# - Check webhook server logs

# Test from TradingView:
# - Verify webhook URL correct
# - Check TradingView alert status (should show green checkmark)
# - Check TradingView alert log (View → Alert Log)
```

#### Position Size Too Large/Small
```bash
# Check critical alerts log
tail -20 logs/critical_alerts.log

# If POSITION_SIZE_ANOMALY alerts:
# - Position Size Validator is working ✅
# - Webhook position_size being overridden (correct behavior)
# - Verify absolute_max_notional_usd and absolute_max_position_pct in config

# If position size calculation wrong:
# - Verify position_size_value in config (should be 15-25%)
# - Check balance in storage/balance_<strategy>.json
# - Review risk_manager.py calculate_position_size() function
```

---

## 📈 Performance Optimization

### Improve Signal Conversion Rate

**Current Problem:** 0.9% conversion (46 trades from 5,090 signals)

**Solutions Applied:**

1. **Increased max_positions:** 3-4 → **5** (25% more capacity)
2. **Extended signal_expiry:** 300s → **900s** (3x longer validity)
3. **Enabled opposite_signals:** false → **true** (allow hedging)
4. **Signal archiver:** Cleanup old signals (faster queue processing)

**Expected Improvement:** 0.9% → 5-8% conversion rate (5-8x improvement)

### Reduce Execution Latency

**Optimize webhook response time:**
```python
# Use atomic JSONL queue writes (already implemented)
queue = AtomicJsonlQueue(signals_queue_file)
queue.append(signal)  # O(1) operation
```

**Optimize signal processing:**
```python
# Check only unprocessed signals (already implemented)
for signal in queue:
    if signal['processed']:
        continue  # Skip processed signals
```

**Result:** Processing time < 50ms per signal

---

## 📚 Additional Resources

### Trading Concepts
- **Squeeze Indicator:** https://www.investopedia.com/articles/technical/04/080404.asp
- **Moving Average Crossovers:** https://www.investopedia.com/articles/active-trading/052014/how-use-moving-average-buy-stocks.asp
- **Supertrend Indicator:** https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/supertrend

### Technical Documentation
- **TradingView Pine Script:** https://www.tradingview.com/pine-script-docs/en/v5/
- **TradingView Webhooks:** https://www.tradingview.com/support/solutions/43000529348-about-webhooks/
- **Binance Futures API:** https://binance-docs.github.io/apidocs/futures/en/

### Code References
- **Flask (Webhook Server):** https://flask.palletsprojects.com/
- **CCXT (Binance Integration):** https://github.com/ccxt/ccxt

---

## 🎓 Strategy Refinements & Future Improvements

### Planned Enhancements

#### 1. Dynamic Position Sizing
```python
# Adjust position size based on signal confidence
if signal_confidence > 0.8:
    position_size *= 1.5  # Increase size for high-confidence signals
elif signal_confidence < 0.4:
    position_size *= 0.5  # Reduce size for low-confidence signals
```

#### 2. Multi-Exchange Support
```python
# Expand beyond Binance to Bybit, OKX, BingX
exchanges = ['binance', 'bybit', 'okx']
for exchange in exchanges:
    check_for_signals(exchange)
```

#### 3. Machine Learning Signal Filtering
```python
# Train ML model on historical signal → outcome patterns
# Features: strategy, timeframe, volatility, volume, time of day
# Target: Trade outcome (win/loss, % gain/loss)
# Filter signals with low predicted success probability
```

#### 4. Adaptive Risk Management
```python
# Adjust risk based on current performance
if win_rate > 60 and last_10_trades_positive:
    risk_per_trade *= 1.2  # Increase risk (capitalize on winning streak)
elif consecutive_losses > 3:
    risk_per_trade *= 0.8  # Decrease risk (protect capital during drawdown)
```

---

## 📝 Glossary

- **TradingView:** Charting platform with Pine Script indicators and webhook alerts
- **Webhook:** HTTP POST request triggered by TradingView alert
- **JSONL:** JSON Lines format (one JSON object per line)
- **Mainnet Price Authority:** Using real Binance mainnet prices for P&L calculation
- **Virtual Balance:** Simulated trading balance (tracks P&L independently of testnet)
- **Position Size Validator:** Security layer preventing catastrophic sizing bugs
- **Signal Archiver:** Automated cleanup of old processed signals from queue
- **Circuit Breaker:** Risk protection that stops trading after excess losses
- **LIMIT Order:** Order executed at specified price or better (not market)
- **STOP_MARKET:** Stop-loss order that becomes market order when stop price hit
- **Signal Conversion Rate:** % of signals that result in trades (quality metric)
- **Notional Value:** Total USD value of position (contracts × price)

---

**Last Updated:** February 18, 2026  
**Bot Version:** v2.5 (Position Size Validator + Signal Archiver)  
**Status:** Production - Active Trading on Binance Testnet  
**Strategies Running:** 4 active (Flow Hybrid, Squeeze Flow, SMA Crossover, Supertrend)
