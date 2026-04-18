# Tracker Reconciliation — Source of Truth Reference
> Written: 2026-04-18 15:25 IST
> Purpose: Prevent future false-alarm loops from mixing backtest, paper-tracker, and live data.

---

## Data Source Map

| What you want to know | Authoritative file | NOT these files |
|---|---|---|
| Current live-candidate strategies | `config/approved_strategies.json` (label=ALPHA) | Chat reports, old manifests |
| Decision-lane paper signals/positions | `docs/DECISION_LANE_STATUS.md` (ETH CCI+Donchian only) | `docs/RUNTIME_LOG.md` (full system) |
| Full system signals (all strategies) | `tradingview_webhook_bot/storage/signal_queue.db` | CSV exports, chat logs |
| Open positions (current) | `tradingview_webhook_bot/storage/ledger_state.json` | Binance UI (testnet may show $0 uPnL) |
| Historical backtest results | `backtesting/` and `storage/backtest_data/` | Signal DB, ledger, paper tracker |
| Gate verdict | `docs/RUNTIME_LOG.md` > Gate Check section | Cron logs, journal entries |
| Paper-window performance | `docs/DECISION_LANE_STATUS.md` > Evidence section | `docs/RUNTIME_LOG.md` (mixes all strategies) |
| Governance audit trail | `docs/DECISION_LANE_STATUS.md`, `config/approved_strategies.json` notes | Chat session reports |

---

## What Each File Contains

### config/approved_strategies.json
- **Contains:** Manifest of all approved strategies with label (ALPHA/paper_only/RESEARCH), symbols, timeframes, backtest hash, notes
- **ALPHA label** = decision-lane live candidates (currently: CCI Trend + Donchian Trend, ETHUSDT only)
- **paper_only label** = monitored for evidence but NOT eligible for capital allocation
- **Do NOT use** backtest CSVs or historical results files to infer current scope — always read this file

### docs/DECISION_LANE_STATUS.md
- **Contains:** Decision-lane-only signals, positions, gate verdict — filtered to ETH CCI+Donchian only
- **Use this for:** checkpoint evidence, promotion decisions, Sainath review
- **Do NOT mix** full-system signal counts from RUNTIME_LOG.md into decision-lane assessment

### docs/RUNTIME_LOG.md
- **Contains:** Full system health: all signals (56 in last 24h), all positions (10 open), gate, heartbeat, 401 count
- **Use this for:** operational monitoring, debugging, system health checks
- **Do NOT use** for checkpoint evidence — it includes all 31 strategies, not just the decision lane

### tradingview_webhook_bot/storage/signal_queue.db
- **Contains:** Raw signal records with payload, status, timestamps
- **Use this for:** debugging individual signals, verifying routing, audit trail
- **Filter required:** always filter by strategy + symbol when measuring decision-lane performance

### tradingview_webhook_bot/storage/ledger_state.json
- **Contains:** Current open positions (qty, avg_price, side) for ALL strategies
- **Note:** ETHUSDT position = decision-lane evidence; all others = paper_only research
- **Binance testnet uPnL shows $0** — this is a testnet limitation, NOT a bug. Orchestrator uses real-time prices.

### backtesting/ and storage/backtest_data/
- **Contains:** Historical OHLCV data and backtest result CSVs
- **Use this for:** strategy research, OOS validation, DSR/PBO inputs
- **NEVER** read these as current paper-trading results — they are historical simulation only

---

## Common Misread Patterns (Do Not Repeat)

| Misread | Reality |
|---|---|
| "56 signals received today" = 56 decision-lane signals | Reality: 56 is ALL strategies. Decision-lane had 0 ETH signals in the same window |
| "10 open positions" = 10 decision-lane trades | Reality: 1 ETHUSDT (decision lane) + 9 paper_only research positions |
| "day_pnl=$0.00" = no activity | Reality: realized PnL logs on close, not on open. No closed trades yet = $0 realized |
| Binance testnet shows $0 uPnL = something is wrong | Reality: testnet field limitation; orchestrator uses real-time prices correctly |
| Backtest CSV shows large loss = paper-trading loss | Reality: CSV is historical backtest, not live/paper signal data |

---

## Evidence Hierarchy for Promotion Decisions

```
Backtest (historical CSV)
    -> Paper window (DECISION_LANE_STATUS.md, ETH-only signals+positions)
        -> DSR validation (scripts/deflated_sharpe.py output)
            -> PBO/CSCV check (scripts/pbo_cscv.py output)
                -> Sainath review + Harsh approval
                    -> ALPHA promotion in config/approved_strategies.json
```

Each step requires the previous. Skipping any step is a governance violation.

---
*Written: 2026-04-18 15:25 IST | Do not edit manually — regenerate with: python3 scripts/gen_tracker_reconciliation.py*
