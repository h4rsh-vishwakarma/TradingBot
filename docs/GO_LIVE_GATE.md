# Go-Live Gate

This document defines the minimum pass criteria before enabling autonomous real-money trading.

## Scope

The gate applies to:

- live webhook ingress
- orchestrator execution policy
- approval manifest workflow
- alpha shortlist promotion
- paper-trading validation
- reconciler/drift health

## Hard Requirements

All items below must pass. A single failing item means `NO_GO`.

### 1. Repo / Server Convergence

- GitHub `main` and the deployed server revision must match.
- A clean clone of the approved commit must start the bot successfully.
- CI for the approved commit must be green without ignored test failures.

Evidence:

- `git rev-parse HEAD` matches deployed revision
- GitHub Actions CI green on the same commit

### 2. Strict TradingView Auth

- Every inbound TradingView signal must contain a valid configured secret.
- Missing secret, placeholder secret, or invalid secret must return `401`.
- No secret may be injected server-side for plain-text fallback formats.

Evidence:

- webhook tests pass
- negative auth tests pass
- recent webhook logs show unauthorized requests rejected

### 3. Immutable Live Approval

- `REQUIRE_APPROVAL_MANIFEST=true`
- only strategies present in `config/approved_strategies.json` may execute
- approval entries must include operator, timestamp, exchange, symbol scope, timeframe scope, and backtest hash

Evidence:

- `scripts/approve_strategy.py` used for promotion
- unknown strategy test is blocked
- approved strategy test is allowed

### 4. Safety Policy

- deny paths must be deterministic and operator-visible
- duplicate, cooldown, candle-lock, circuit-breaker, kill-switch, and no-position exit cases must send Telegram decision alerts
- exit handling must not resize or cap a closing order into a new exposure

Evidence:

- orchestrator decision tests pass
- skip/block alerts visible in Telegram
- exit fallback tests pass

### 5. Research / Live Separation

- research outputs must not directly alter live execution without manifest approval
- `tournament_winners.csv` and batch backtest results are advisory only
- the live path must read only the approved manifest and runtime risk controls

Evidence:

- orchestrator checks approval manifest before execution
- removing a strategy from manifest blocks it immediately

### 6. Realism-Normalized Research

- shortlist must be produced from realism-aware backtests
- required knobs:
  - fixed-notional or capped-fraction sizing
  - slippage applied
  - OOS holdout results
  - walk-forward pass rate

Evidence:

- `scripts/batch_backtest.py` summary contains:
  - `Sizing Mode`
  - `Fixed Notional`
  - `Slippage Bps`
  - `OOS ROI %`
  - `WF Pass Rate %`
  - `Reality Score`
  - `Shortlist Eligible`

### 7. Frozen Shortlist

- only `3-5` paper-trade candidates may be active at once
- shortlisted strategies must have:
  - approved manifest entry
  - generated webhook-ready Pine file
  - matching symbol/timeframe

Evidence:

- `storage/reports/alpha_shortlist.csv`
- `storage/reports/tv_inventory_report.csv`

### 8. Paper Validation Window

- a frozen shortlist must run in paper or testnet mode for at least `7` consecutive days
- no bypasses added during the observation window

Minimum acceptance:

- auth failures: all invalid requests rejected
- signal ingestion: no unexplained queue stalls
- drift rate: `0` repeated critical drifts on approved symbols
- execution consistency: no duplicate fills from one signal
- skip/block visibility: every non-executed signal has a Telegram reason
- shortlist behavior: no strategy exceeds allowed drawdown cap during paper run

Evidence:

- paper-trade report
- reconciler logs
- queue status
- Telegram decision audit

## Pass / Fail Thresholds

Use these thresholds for final sign-off.

### Must Pass

- CI status: `PASS`
- strict auth tests: `PASS`
- manifest enforcement tests: `PASS`
- reconciler structured alert tests: `PASS`
- inventory verification: `100% READY` for approved shortlist
- paper window length: `>= 7 days`

### Must Stay Below

- repeated critical reconciliation drift: `0`
- unexplained skipped signals without Telegram reason: `0`
- server/repo revision mismatch: `0`

### Shortlist Limits

- shortlist size: `3-5`
- max gross drawdown threshold from alpha engine: project-configured active rule
- max net drawdown threshold from alpha engine: project-configured active rule

## Operator Workflow

1. Run realism-aware batch backtest.
2. Generate alpha reports and shortlist.
3. Review shortlist manually.
4. Approve shortlisted strategies with `scripts/approve_strategy.py`.
5. Verify Pine deployment artifacts with `scripts/verify_tv_inventory.py`.
6. Run the frozen shortlist in paper/testnet mode for 7 days.
7. Review paper metrics against this gate.
8. Enable live capital only after all gate items pass.

## Promotion Commands

Approve a strategy:

```bash
python scripts/approve_strategy.py \
  --strategy "Example Strategy" \
  --exchange binance \
  --symbols BTCUSDT \
  --timeframes 4h \
  --operator your_name \
  --backtest-hash sha256:example
```

Verify alert inventory:

```bash
python scripts/verify_tv_inventory.py
```

Run alpha pipeline:

```bash
python scripts/run_alpha_pipeline.py --notify-telegram
```

## Status Labels

- `NO_GO`: one or more hard requirements failed
- `PAPER_ONLY`: code and controls pass, but paper window is incomplete
- `READY_FOR_TINY_CAPITAL`: all hard requirements pass and paper window passes
- `READY_FOR_CAPPED_SCALE`: tiny-capital stage passes under a separate review


## Paper Window Hard-Stop Conditions (NO_GO Triggers)

If ANY of the following occur during the 7-day paper window, the result is **immediate NO_GO**:

### Critical (Stop immediately)
1. **Duplicate execution** — same signal executes twice on exchange
2. **Auth bypass** — signal accepted without valid secret
3. **Manifest bypass** — unapproved strategy reaches execution
4. **Critical reconciler drift** — SIDE_MISMATCH or repeated UNEXPECTED_FLAT/OPEN (>3 in 24h)
5. **Circuit breaker failure** — trades continue after daily loss limit hit

### High (Investigate within 1 hour)
6. **Missing SL/TP** — any approved strategy entry trade has no SL or TP placed
7. **Queue stall** — no signals processed for >6 hours during market hours
8. **Inventory regression** — LIVE_VERIFIED drops to MISSING mid-window
9. **DLQ growth** — dead letter queue exceeds 5 signals in 24h
10. **Unexplained signal skip** — signal blocked without a logged reason in Telegram

### Warning (Log and continue)
11. **Single reconciler drift** — MEDIUM severity, auto-corrected
12. **Candle lock / cooldown blocks** — expected behavior for anti-flip-flop
13. **No signals for 4h** — may be quiet market (check TradingView chart)

### Pass Criteria (Day 8 review)
- Zero critical incidents
- Zero high incidents unresolved
- PF > 0.8 (allowing for thin edge in 7 days)
- Max DD < 15% of paper capital
- Signal-to-execution latency < 5 seconds (median)
- All daily reports sent successfully
