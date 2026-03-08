# Project Reorganization Plan

**Date:** 2026-02-19
**Status:** ✅ COMPLETED

## Executive Summary

The project structure has been successfully reorganized and unified. All issues have been resolved.

## Completed Actions

1. ✅ Restored 20 missing Python files from git history
2. ✅ Reorganized repository to use `tradingview-webhook-bot/` subdirectory
3. ✅ Moved Pine scripts to `strategies/` directory
4. ✅ Moved utility scripts to `scripts/` directory
5. ✅ Unified repo and server structures
6. ✅ Updated deployment scripts
7. ✅ Migrated production server to new structure
8. ✅ All 7 TradingView bot strategies operational

## Current Structure Issues (RESOLVED)

## Current Structure Issues

### Import Dependencies Found

From `main_enhanced.py`, the following imports are referenced but **files don't exist**:

| Import Statement | Expected File | Status |
|-----------------|---------------|--------|
| `from exchange.binance_client import BinanceClient` | `exchange/binance_client.py` | ❌ Missing |
| `from exchange.price_provider import get_price_provider` | `exchange/price_provider.py` | ❌ Missing |
| `from core.strategy_engine import StrategyEngine` | `core/strategy_engine.py` | ❌ Missing |
| `from core.position_manager import PositionManager` | `core/position_manager.py` | ❌ Missing |
| `from core.risk_manager import RiskManager` | `core/risk_manager.py` | ❌ Missing |
| `from core.balance_manager import BalanceManager` | `core/balance_manager.py` | ❌ Missing |
| `from exchange.enhanced_order_executor import EnhancedOrderExecutor` | `exchange/enhanced_order_executor.py` | ❌ Missing |
| `from utils.signal_archiver import SignalArchiver` | `utils/signal_archiver.py` | ❌ Missing |
| `from utils.helpers import ...` | `utils/helpers.py` | ❌ Missing |

### Existing Files That Are Imported

| Import Statement | File Location | Status |
|-----------------|---------------|--------|
| `from exchange.execution_engine import get_execution_engine` | `exchange/execution_engine.py` | ✅ Exists |
| `from core.enhanced_order_manager import EnhancedOrderManager` | `core/enhanced_order_manager.py` | ✅ Exists |
| `from core.webhook_server import WebhookServer` | `core/webhook_server.py` | ✅ Exists |
| `from core.signal_processor import SignalProcessor` | `core/signal_processor.py` | ✅ Exists |
| `from core.order_monitor import get_order_monitor` | `core/order_monitor.py` | ✅ Exists |
| `from utils.logger import setup_logger` | `utils/logger.py` | ✅ Exists |
| `from utils.instance_lock import InstanceLock` | `utils/instance_lock.py` | ✅ Exists |
| `from utils.health_checker import get_health_checker` | `utils/health_checker.py` | ✅ Exists |
| `from utils.dashboard_updater import trigger_dashboard_update` | `utils/dashboard_updater.py` | ✅ Exists |
| `from storage.idempotency_store import IdempotencyStore` | `storage/idempotency_store.py` | ✅ Exists |
| `from storage.jsonl_consumer import JsonlOffsetConsumer` | `storage/jsonl_consumer.py` | ✅ Exists |

## Proposed Directory Structure

```
trading-view-indicators/
├── tradingview-webhook-bot/          # NEW - TradingView webhook system
│   ├── main_enhanced.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── circuit_breaker.py
│   │   ├── enhanced_order_manager.py
│   │   ├── order_monitor.py
│   │   ├── signal_processor.py
│   │   └── webhook_server.py
│   ├── exchange/
│   │   ├── __init__.py
│   │   └── execution_engine.py
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── client_order_id_generator.py
│   │   ├── dashboard_updater.py
│   │   ├── event_logger.py
│   │   ├── health_checker.py
│   │   ├── instance_lock.py
│   │   ├── logger.py
│   │   ├── position_reconciler.py
│   │   └── telegram_alerter.py
│   └── storage/
│       ├── __init__.py
│       ├── idempotency_store.py
│       ├── jsonl_consumer.py
│       └── jsonl_queue.py
│
├── liquidation-heatmap-bot/          # UNCHANGED - Already properly structured
│   ├── bot_main.py
│   ├── signal_generator.py
│   ├── config.py
│   ├── core/
│   ├── observability/
│   └── execution/
│
├── strategies/                       # NEW - Pine Script indicators
│   ├── ema_sma_crossover_webhook.pine
│   ├── enhanced_atr_supertrend_config.json
│   ├── enhanced_atr_supertrend_webhook.pine
│   ├── institutional_matrix_webhook.pine
│   ├── lorentzian_classification_webhook.pine
│   ├── obv_wavetrend_scalper_webhook.pine
│   ├── sma_crossover_9_21_webhook.pine
│   ├── squeeze_flow_expansion_webhook.pine
│   └── supertrend_btc_4h_webhook.pine
│
├── scripts/                          # NEW - Utility scripts
│   ├── clean_dashboard_7tabs.py
│   └── clean_dashboard_tab7.py
│
├── config/                           # UNCHANGED - Shared configurations
│   ├── config_institutional_flow_hybrid.json
│   ├── config_institutional_matrix.json
│   ├── config_obv_wavetrend_scalper.json
│   ├── config_sma_crossover_9_21.json
│   ├── config_smc_luxalgo.json
│   ├── config_squeeze_flow_expansion.json
│   ├── config_supertrend_btc_4h.json
│   ├── settings.json
│   └── strategy_template.json
│
├── docs/                             # UNCHANGED - Documentation
├── deploy/                           # UNCHANGED - Deployment scripts
├── aws-configs/                      # UNCHANGED - AWS configurations
│
├── .github/
│   └── workflows/
│       ├── deploy.yml
│       └── phase5-ci.yml
│
├── README.md                         # Will need updates
├── PRD_TRADING_SYSTEMS_COMBINED.md
├── TRADINGVIEW_BOT_DOCUMENTATION.md
├── pytest.ini
└── .gitignore
```

## Migration Plan

### Phase 1: Pre-Migration Preparation

1. **Create backup branch**
   ```bash
   git checkout -b backup-before-reorganization
   git push origin backup-before-reorganization
   ```

2. **Create new directories**
   ```bash
   mkdir -p tradingview-webhook-bot/{core,exchange,utils,storage}
   mkdir -p strategies
   mkdir -p scripts
   ```

### Phase 2: File Movement

#### 2.1 Move TradingView Bot Files

| Source | Destination |
|--------|-------------|
| `main_enhanced.py` | `tradingview-webhook-bot/main_enhanced.py` |
| `core/__init__.py` (create) | `tradingview-webhook-bot/core/__init__.py` |
| `core/circuit_breaker.py` | `tradingview-webhook-bot/core/circuit_breaker.py` |
| `core/enhanced_order_manager.py` | `tradingview-webhook-bot/core/enhanced_order_manager.py` |
| `core/order_monitor.py` | `tradingview-webhook-bot/core/order_monitor.py` |
| `core/signal_processor.py` | `tradingview-webhook-bot/core/signal_processor.py` |
| `core/webhook_server.py` | `tradingview-webhook-bot/core/webhook_server.py` |
| `exchange/__init__.py` (create) | `tradingview-webhook-bot/exchange/__init__.py` |
| `exchange/execution_engine.py` | `tradingview-webhook-bot/exchange/execution_engine.py` |
| `utils/__init__.py` (create) | `tradingview-webhook-bot/utils/__init__.py` |
| `utils/client_order_id_generator.py` | `tradingview-webhook-bot/utils/client_order_id_generator.py` |
| `utils/dashboard_updater.py` | `tradingview-webhook-bot/utils/dashboard_updater.py` |
| `utils/event_logger.py` | `tradingview-webhook-bot/utils/event_logger.py` |
| `utils/health_checker.py` | `tradingview-webhook-bot/utils/health_checker.py` |
| `utils/instance_lock.py` | `tradingview-webhook-bot/utils/instance_lock.py` |
| `utils/logger.py` | `tradingview-webhook-bot/utils/logger.py` |
| `utils/position_reconciler.py` | `tradingview-webhook-bot/utils/position_reconciler.py` |
| `utils/telegram_alerter.py` | `tradingview-webhook-bot/utils/telegram_alerter.py` |
| `storage/__init__.py` (create) | `tradingview-webhook-bot/storage/__init__.py` |
| `storage/idempotency_store.py` | `tradingview-webhook-bot/storage/idempotency_store.py` |
| `storage/jsonl_consumer.py` | `tradingview-webhook-bot/storage/jsonl_consumer.py` |
| `storage/jsonl_queue.py` | `tradingview-webhook-bot/storage/jsonl_queue.py` |

#### 2.2 Move Pine Script Files to Strategies/

| Source | Destination |
|--------|-------------|
| `ema_sma_crossover_webhook.pine` | `strategies/ema_sma_crossover_webhook.pine` |
| `enhanced_atr_supertrend_config.json` | `strategies/enhanced_atr_supertrend_config.json` |
| `enhanced_atr_supertrend_webhook.pine` | `strategies/enhanced_atr_supertrend_webhook.pine` |
| `institutional_matrix_webhook.pine` | `strategies/institutional_matrix_webhook.pine` |
| `lorentzian_classification_webhook.pine` | `strategies/lorentzian_classification_webhook.pine` |
| `obv_wavetrend_scalper_webhook.pine` | `strategies/obv_wavetrend_scalper_webhook.pine` |
| `sma_crossover_9_21_webhook.pine` | `strategies/sma_crossover_9_21_webhook.pine` |
| `squeeze_flow_expansion_webhook.pine` | `strategies/squeeze_flow_expansion_webhook.pine` |
| `supertrend_btc_4h_webhook.pine` | `strategies/supertrend_btc_4h_webhook.pine` |

#### 2.3 Move Utility Scripts to scripts/

| Source | Destination |
|--------|-------------|
| `clean_dashboard_7tabs.py` | `scripts/clean_dashboard_7tabs.py` |
| `clean_dashboard_tab7.py` | `scripts/clean_dashboard_tab7.py` |

### Phase 3: Import Statement Updates

**IMPORTANT:** After moving files to `tradingview-webhook-bot/`, we need to decide on the import strategy:

#### Option A: Use Package Imports (Recommended)

Add `tradingview-webhook-bot/` to Python path and use:
```python
from tradingview_webhook_bot.core.enhanced_order_manager import EnhancedOrderManager
from tradingview_webhook_bot.exchange.execution_engine import get_execution_engine
```

#### Option B: Adjust PYTHONPATH in Launch Scripts

Set `PYTHONPATH` before running:
```bash
export PYTHONPATH=/path/to/tradingview-webhook-bot:$PYTHONPATH
python3 tradingview-webhook-bot/main_enhanced.py
```

Then imports remain:
```python
from core.enhanced_order_manager import EnhancedOrderManager
from exchange.execution_engine import get_execution_engine
```

### Phase 4: Documentation Updates

1. **README.md** - Update directory structure diagram
2. **docs/TRADINGVIEW_BOT_DOCUMENTATION.md** - Update paths
3. **.github/workflows/deploy.yml** - Update any hardcoded paths
4. **deploy/deploy.sh** - Update deployment paths

### Phase 5: Cleanup

1. Remove old `__pycache__` directories from root
2. Update `.gitignore` if needed
3. Delete old empty directories

## Critical Issues to Resolve

### Missing Module Files

The following imports in `main_enhanced.py` reference non-existent files. These must be created OR the imports must be removed/refactored:

| Missing File | Options |
|--------------|---------|
| `exchange/binance_client.py` | Create file OR refactor code to not need it |
| `exchange/price_provider.py` | Create file OR refactor code |
| `core/strategy_engine.py` | Create file OR refactor code |
| `core/position_manager.py` | Create file OR refactor code |
| `core/risk_manager.py` | Create file OR refactor code |
| `core/balance_manager.py` | Create file OR refactor code |
| `exchange/enhanced_order_executor.py` | Create file OR refactor code |
| `utils/signal_archiver.py` | Create file OR refactor code |
| `utils/helpers.py` | Create file OR refactor code |

**Recommendation:** Before reorganizing, verify if:
1. This code was ever working
2. These classes were moved into existing files
3. These files exist elsewhere (maybe in liquidation-heatmap-bot/)

## Testing Checklist

After reorganization:

- [ ] Python syntax check: `python -m py_compile tradingview-webhook-bot/**/*.py`
- [ ] Import test: Create test script to verify all imports resolve
- [ ] Verify `main_enhanced.py` can still be executed
- [ ] Verify `liquidation-heatmap-bot/` still works independently
- [ ] Check for any remaining hardcoded paths
- [ ] Update systemd service files if they reference old paths
- [ ] Update deployment scripts

## Rollback Procedure

If reorganization causes issues:

```bash
# Reset to backup branch
git checkout main
git branch -D reorganization-attempt
git checkout backup-before-reorganization
```

## Next Steps

1. **User Decision:** Confirm whether to proceed with reorganization
2. **Resolve Missing Modules:** Address the 9+ missing module imports first
3. **Create Test Script:** Verify current state before making changes
4. **Execute Migration:** Follow phases 1-5
5. **Test Thoroughly:** Run testing checklist
