# Tracker Source of Truth
> Created: 2026-04-21 | Updated from TRACKER_RECONCILIATION.md
> Purpose: Single authoritative reference for which file answers which question.
> CEO audit Q-02 requirement: explicit evidence-class map on GitHub main.

---

## Quick Reference — Which File to Read

| Question | Authoritative Source | Do NOT Use |
|---|---|---|
| Current live-candidate strategies | `config/approved_strategies.json` (`approval_class=candidate_for_tiny_capital`) | Chat reports, old manifests |
| Decision-lane signals + positions | `docs/DECISION_LANE_STATUS.md` (ETH CCI+Donchian only) | `docs/RUNTIME_LOG.md` (full system) |
| Gate verdict (go/no-go) | `docs/RUNTIME_LOG.md` → Gate Check section | Cron logs, journal entries |
| Full system signals (all strategies) | `tradingview_webhook_bot/storage/signal_queue.db` | CSV exports, chat logs |
| Open positions (current state) | `tradingview_webhook_bot/storage/ledger_state.json` | Binance UI (testnet shows $0 uPnL — known limitation) |
| Historical backtest results | `backtesting/` and `storage/backtest_data/` | Signal DB, ledger, paper tracker |
| Checkpoint/promotion evidence | `docs/DECISION_LANE_STATUS.md` → Evidence section | Any full-system metric |
| Governance audit trail | `docs/DECISION_LANE_STATUS.md` + `config/approved_strategies.json` notes | Chat session reports |

---

## Evidence Classes

### Class 1 — Decision-Lane Evidence (counts for checkpoint)
- Source: `docs/DECISION_LANE_STATUS.md`
- Scope: CCI Trend + Donchian Trend on ETHUSDT 4h ONLY
- Includes: signal count, closed trades, open positions for ETHUSDT only
- Gate verdict from this file is what Sainath reviews

### Class 2 — Full-System Operational Data (does NOT count for checkpoint)
- Source: `docs/RUNTIME_LOG.md`, `storage/signal_queue.db`
- Scope: all 31 strategies, all symbols
- Use for: debugging, operational monitoring, system health
- Do NOT mix with Class 1 — they will always look different (56 vs 0 signals is expected)

### Class 3 — Research/Backtest Data (not live evidence)
- Source: `backtesting/`, `storage/backtest_data/`, tournament CSVs
- Scope: historical simulation only
- Use for: strategy ranking, OOS validation, DSR/PBO inputs
- NEVER read as current paper-trading results

---

## File-by-File Summary

### `config/approved_strategies.json` (v10)
- Manifest of all strategies: label, symbols, timeframes, backtest hash
- `approval_class=candidate_for_tiny_capital` → decision lane (currently 2: CCI Trend + Donchian Trend, ETHUSDT)
- `approval_class=paper_only` → research monitored, not capital-eligible (29 strategies)
- Source of truth for scope — always read this, not chat claims

### `docs/DECISION_LANE_STATUS.md`
- Auto-generated: decision-lane-only signals, positions, gate verdict
- ETH CCI+Donchian filtered — not polluted by paper_only activity
- Use for: checkpoint evidence, promotion decisions, Sainath review

### `docs/RUNTIME_LOG.md`
- Auto-generated hourly by `scripts/gen_runtime_log.py`
- Full system: all 31 strategies, all signals, all positions, gate, heartbeat
- Use for: operational health checks, debugging
- Do NOT use for checkpoint evidence

### `tradingview_webhook_bot/storage/ledger_state.json`
- Current open positions for ALL strategies (qty, avg_price, side)
- ETHUSDT position = decision-lane evidence; all others = paper_only research
- Testnet shows $0 uPnL — known limitation, orchestrator uses real-time prices

### `tradingview_webhook_bot/storage/signal_queue.db`
- Raw signal records: payload, status, timestamps
- Always filter by `strategy` + `symbol` for decision-lane metrics
- Unfiltered counts include all 31 strategies — do not report raw totals as lane evidence

---

## Common Misreads (Do Not Repeat)

| Misread | Reality |
|---|---|
| "56 signals today" = 56 decision-lane signals | 56 = ALL strategies. Decision lane had 0 ETH signals in same window |
| "10 open positions" = 10 decision-lane trades | 1 ETHUSDT (decision lane) + 9 paper_only research |
| "day_pnl=$0.00" = no activity | Realized PnL logs on close. No closed trades = $0 realized, not a bug |
| Binance testnet $0 uPnL = system error | Testnet field limitation — not a bug |
| Backtest CSV loss = live trading loss | CSV is historical simulation only |

---

## Promotion Evidence Hierarchy

```
Backtest (historical CSV)
    → Paper window (DECISION_LANE_STATUS.md, ETH-only signals + positions)
        → DSR validation (scripts/deflated_sharpe.py output)
            → PBO/CSCV check (scripts/pbo_cscv.py output)
                → Sainath review + Harsh approval
                    → ALPHA promotion in config/approved_strategies.json
```

Each step requires the previous. Skipping any step is a governance violation.

---

## Lane Isolation Status
- Harsh: decision-lane strategies on primary Binance testnet key
- Garima: paper_only strategies — manifest class enforced at webhook level
- Shared TradingView account risk: mitigated by strategy-name routing in webhook_server.py
- Full key isolation: pending (Q-04 in CEO audit — target post-checkpoint)

---
*Written: 2026-04-21 | Links from: docs/DECISION_LANE_STATUS.md, docs/RUNTIME_LOG.md*
