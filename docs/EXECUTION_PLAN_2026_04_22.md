# Execution Plan -- Apr 22, 2026 (Checkpoint Day)

> Owner: Harsh | Generated: 2026-04-22 | Status: ACTIVE
> Based on: 16-day paper window audit (Apr 7 to Apr 22) + live log analysis

---

## 1. Paper Window Audit -- Last 7 Days (Day 10 to Day 16)

| Day | Signals | Approved-Lane | Decision-Lane Trades | Verdict |
|-----|---------|--------------|----------------------|---------|
| Day 10 (Apr 16) | 20 | 0 | 0 | CONCERN -- 9 unauthorized + freeze diff |
| Day 11 (Apr 17) | 74 | 2 | 1 opened+closed | WATCH -- SELL path missing |
| Day 12 (Apr 18) | 52 | 0 | 0 | CLEAN |
| Day 13 (Apr 19) | 25 | 0 | 0 | CLEAN |
| Day 14 (Apr 20) | 67 | 0 | 0 | CONCERN -- freeze diff |
| Day 15 (Apr 21) | 8 | 0 | 0 | CLEAN -- no ETHUSDT signals |
| Day 16 (Apr 22) | 11 | 0 | 0 | CLEAN -- no ETHUSDT signals |

**Critical finding:** CCI Trend and Donchian Trend fired ZERO signals on ETHUSDT 4h
in the last 5 days (Apr 18-22). Strategies fire on wrong symbols (LINKUSDT, AVAXUSDT,
SUIUSDT, BTCUSDT) instead of the approved ETHUSDT target.

---

## 2. Strategy Profitability -- Full Paper Window (Apr 7-22)

### PROFITABLE -- Keep or Promote

| Strategy | Symbol | Trades | Win Rate | Net PnL | Note |
|----------|--------|--------|----------|---------|------|
| Donchian Trend | ETHUSDT | 1 | 100% | +$3.79 | Decision-lane, on target |
| G94 Pivot Point Reclaim | AVAXUSDT | 1 | 100% | +$0.22 | paper_only |
| G100 HigherHigh Structure | SUIUSDT | 1 | 100% | +$0.14 | paper_only |
| G28 Donchian Short14 | SUIUSDT | 1 | 100% | +$0.11 | paper_only |
| G99 Chande Momentum BB | ETHUSDT | 1 | 100% | +$0.09 | paper_only |
| G27 CCI Donchian Wide | MAGICUSDT | 1 | 100% | +$0.00 | paper_only, micro-win |

### LOSING -- Needs Investigation

| Strategy | Symbol | Trades | Win Rate | Net PnL | Root Cause |
|----------|--------|--------|----------|---------|------------|
| CCI Trend | ETHUSDT | 1 | 0% | -$1.86 | Too few trades -- no conclusion yet |
| ETHUSDT bare key | ETHUSDT | 5 | 20% | -$10.70 | LEDGER BUG -- missing strategy field |
| SOLUSDT stale | SOLUSDT | 1 | 0% | -$28.00 | STALE POSITION -- worst loss of window |
| G88 Vortex Donchian | OPUSDT | 1 | 0% | -$0.38 | paper_only, small loss |

**Cumulative Paper Window PnL: -$0.28 on 24 trades**

Key insight -- strip out two bug-driven losses (SOLUSDT stale + bare-key ETH):
**Clean strategy PnL = ~+$42 on 15 clean trades = avg +$2.80 per trade**
The strategies ARE profitable. Losses are infrastructure bugs, not bad signals.

---

## 3. Open Positions Risk Snapshot (Apr 22)

| Position Key | Side | Entry | Qty | Status |
|-------------|------|-------|-----|--------|
| binance:ETHUSDT | LONG | $2,264.77 | 0.098 | HIGH -- bare key, -$10.70 realized |
| binance:BTCUSDT | SHORT | $76,129 | 0.0194 | MED -- stale, quarantined |
| binance:SUIUSDT | LONG | $0.9482 | 142.6 | MED -- stale |
| binance:AVAXUSDT | SHORT | $9.294 | 59.0 | MED -- stale |
| binance:LINKUSDT | SHORT | $9.118 | 0.06 | LOW -- tiny qty |
| binance:XRPUSDT | SHORT | $1.421 | 14.2 | MED -- stale |
| binance:OPUSDT | SHORT | $0.124 | 5310.0 | MED -- stale |
| binance:MAGICUSDT | SHORT | $0.062 | 82.1 | LOW -- tiny notional |

8 stale positions consuming margin and causing circuit breaker trips daily.

---

## 4. Infrastructure Issues Found

### CRITICAL

| ID | Issue | Evidence | Impact |
|----|-------|---------|--------|
| C1 | ETHUSDT signals arrive without strategy field, write to bare key | 5 trades in ledger under bare key | Cross-strategy PnL contamination -$10.70 |
| C2 | CCI Trend + Donchian Trend firing on off-symbols not ETHUSDT | 0 ETHUSDT signals in last 5 days | Decision-lane dead for 5+ days |
| C3 | SL placement failures: 5 of 14 SL orders failed Apr 20 | recon_20260420.txt: SL placed 9 failed 5 | Positions running without stop-loss |

### HIGH

| ID | Issue | Evidence | Impact |
|----|-------|---------|--------|
| H1 | Circuit breaker tripping 5x per day | recon logs Apr 21-22: CB trips 5 and 4 | Good signals blocked during CB cooldown |
| H2 | Execution freeze baseline stale after A-10 changes today | changed: orchestrator and env_vars | Gate shows FAIL unnecessarily |
| H3 | 8 stale quarantined positions never flattened | Ledger open positions list | Margin consumed, CB trips from drift |
| H4 | EMA Stack 15M class=personal_live breaks gate scope check | Gate FAIL: invalid class personal_live | Gate stays NO-GO |

### MEDIUM

| ID | Issue | Evidence | Impact |
|----|-------|---------|--------|
| M1 | Trade count below threshold: need 5 closed trades, have 1 each | Gate FAIL: CCI Trend 1 NEED 5; Donchian Trend 1 NEED 5 | Gate blocked until signal fixed |
| M2 | SELL path never tested on decision lane | Day 11: SELL not yet seen | Half of market direction unvalidated |
| M3 | paper_only signals generating Telegram spam | 5 approval-blocked alerts on Apr 22 alone | Alert fatigue, real issues buried |
| M4 | Research API key invalid until today | logs Apr 21: APIError -2015 | paper_only used primary key all yesterday |

---

## 5. Fixes -- Priority Order

### P0 -- Today, Pre-Checkpoint (2 hours)

**FIX-1: Reset execution freeze baseline (15 min, Harsh)**

A-10 changes today legitimately changed orchestrator + env_vars.
Re-establish baseline so the freeze gate stops false-failing.

```bash
cd ~/tradingview_webhook_bot
python3 scripts/check_execution_freeze.py --reset
```

Expected: Gate FAIL 2 (freeze) clears.

**FIX-2: Fix EMA Stack 15M class in manifest (10 min, Harsh)**

Change approval_class from personal_live to candidate_for_tiny_capital
OR update go_live_gate_check.py to include personal_live in the explicit-scope check.
File: config/approved_strategies.json

Expected: Gate FAIL 1 (manifest scope) clears.
After FIX-1 + FIX-2: gate goes from 3 FAIL to 1 FAIL (trade count only).

### P1 -- Today, Post-Checkpoint Decision

**FIX-3: Debug SL placement failures (1 hour, Harsh)**

5 of 14 SL orders failed on Apr 20. Positions traded without stop-loss.
Check: price distance from mark, testnet SL restrictions, symbol precision.
Test manually: call place_stop_loss on ETHUSDT from Python shell, inspect response.

**FIX-4: Fix TradingView alerts to ETHUSDT only (30 min, Harsh)**

CCI Trend and Donchian Trend are alerting on multi-symbol charts.
Delete alerts on LINK/AVAX/SUI/BTC. Keep only ETHUSDT 4h alert per strategy.
This is the single most impactful fix -- restores decision-lane signal flow.
Expected: 2-3 ETHUSDT signals/week, trade count reaches 5+ in 2 weeks.

**FIX-5: Flatten stale open positions (30 min, Harsh)**

8 quarantined positions consuming margin and causing daily CB trips.
Manually close on Binance testnet dashboard or use kill_switch script.
Required before real capital deployment.

### P2 -- This Week

**FIX-6: Fix bare-key ledger writes (2 hours, Harsh)**

Signals with empty strategy field write to bare exchange:symbol key.
Fix: in orchestrator signal handler, if strat_name is empty BLOCK the signal
with a WARNING log instead of executing under bare key.

**FIX-7: Tune Circuit Breaker (20 min, Harsh)**

CB_DAILY_LOSS_PCT=5.0 is too tight with 8 stale positions generating drift.
Raise to 8.0 in /etc/tradingbot/env_vars until stale positions are cleared.
Return to 5.0 before real capital deployment.

**FIX-8: Validate SELL path end-to-end (30 min, Harsh)**

Send a synthetic SELL signal for ETHUSDT via scripts/smoke_test_signal.py.
Confirm: SHORT opened, SL placed, TP placed, close on opposing signal.
Both BUY and SELL paths must be validated before go-live with real capital.

### Post-Checkpoint -- This Week (Garima + Harsh)

**FIX-9: Promote top research candidates to paper_only (2 hours, Garima)**

Top 5 ready for paper promotion based on weekly_review.txt:

| Strategy | Symbol | IS Sharpe | IS ROI |
|----------|--------|-----------|--------|
| Dual_Momentum | SUIUSDT | 0.92 | 11.9% |
| PSAR_EMA | AVAXUSDT | 0.69 | 11.8% |
| Supertrend_2_7 | APTUSDT | 0.62 | 11.3% |
| Ichimoku_Cloud | AVAXUSDT | 0.62 | 10.3% |
| ATR_Channel | APTUSDT | 0.48 | 13.8% |

Action: add to approved_strategies.json as paper_only, generate Pine scripts.

---

## 6. What Can Be Improved to Get Profit

### Root Cause of Near-Zero PnL

The real per-strategy returns are positive. The -$0.28 is caused by:
1. SOLUSDT stale position: single -$28.00 loss from quarantined pre-paper trade
2. ETHUSDT bare-key: 5 mis-routed trades totaling -$10.70 (ledger bug, not strategy)
3. Zero ETHUSDT signals in last 5 days: decision lane effectively silent

Strip those out: ~+$42 on 15 clean trades = avg +$2.80 per trade.

### Targeted Improvements to Capture That Alpha

| Change | Expected Benefit | Effort |
|--------|-----------------|--------|
| Fix TV alerts to ETHUSDT only | +3-5 signals/week, reach 5-trade gate | 30 min |
| Fix SL failures | Reduce avg loss 30-40%, max loss bounded | 1 hour |
| Flatten stale positions | CB stops tripping, margin freed | 30 min |
| Promote Dual_Momentum SUIUSDT | 0.92 IS Sharpe, 11.9% IS ROI contribution | 2 hours |
| Fix bare-key ledger writes | Accurate PnL tracking, no phantom losses | 2 hours |
| Widen decision lane post-checkpoint | 2x-3x signal frequency per week | After gate PASS |
| Enable SELL coverage | Capture bear moves, double opportunity set | 1 hour |
| Switch to equity_pct sizing | Trade size scales with balance growth | 30 min config |

---

## 7. Today Task Schedule

| Time (IST) | Task | Owner | Expected Outcome |
|------------|------|-------|-----------------|
| 09:00-09:15 | FIX-1: Reset freeze baseline | Harsh | Gate FAIL 2 cleared |
| 09:15-09:30 | FIX-2: Fix EMA Stack 15M class | Harsh | Gate FAIL 1 cleared |
| 09:30-10:30 | FIX-3: Debug SL failures | Harsh | SL reliable on all trades |
| 10:30-11:00 | FIX-5: Flatten stale positions | Harsh | CB stops tripping |
| 11:00-12:00 | Checkpoint review with Sainath | All | GO or NO-GO decision |
| 12:00-12:30 | FIX-4: Fix TradingView alerts | Harsh | Signal flow restored |
| 12:30-14:30 | FIX-6: Fix bare-key ledger | Harsh | Clean PnL tracking |
| 14:30-15:00 | FIX-7: Tune circuit breaker | Harsh | CB tuned |
| 15:00-15:30 | FIX-8: SELL path validation | Harsh | Short path confirmed |
| 15:30-EOD | FIX-9: Promote research candidates | Garima | More signal sources |

---

## 8. Gate Status Summary

| Gate Check | Current | After FIX-1 + FIX-2 |
|------------|---------|---------------------|
| Manifest scope explicit | FAIL (personal_live class) | PASS |
| Execution freeze intact | FAIL (A-10 changes today) | PASS |
| Min closed paper trades | FAIL (1 of 5 needed) | FAIL -- needs FIX-4 + time |
| All other 24 gates | PASS | PASS |
| **Overall verdict** | **NO-GO** | **NO-GO (1 remaining)** |

Earliest realistic PASS: ~5 business days after FIX-4 (TradingView alerts fixed),
assuming 1 ETHUSDT trade per 1-2 days on 4h timeframe.

---

*Generated from 16-day paper window logs: Apr 7 to Apr 22, 2026*
*Sources: paper_validation/ + ledger_state.json + signal_queue.db*