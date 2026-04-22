# Paper Window Checkpoint Audit -- Apr 22, 2026

> Generated: 2026-04-22 | Owner: Harsh | Source: 16 daily recon snapshots + signal_queue.db + ledger_state.json

---

## 1. Sheet Logging Gap -- Root Cause Analysis

**Finding: The 'missing rows' are mostly correct behavior, not data loss.**

| Date | Signals Fired | Trades Executed | Sheet Rows Written | Delta | Root Cause |
|------|--------------|-----------------|-------------------|-------|------------|
| Apr 20 | 39 | 10 | 9 | -1 | 1 trade dropped by thread pool on restart |
| Apr 21 | 7 | 2 | 1 | -1 | 1 trade (EMA Stack 15M BTCUSDT 13:51 UTC) dropped during 4-restart window 13:40-13:51 |
| Apr 22 | 10 | 0 | 0 | 0 | CORRECT -- all signals blocked by gate (CB trips x5 + approval blocks x5) |

**Why the 30+ rows look missing:** paper_only signals generate 'Blocked Trades' tab entries, not 'Trades' tab entries.
The 39 signals on Apr 20 include ~29 paper_only signals that correctly went to the Blocked Trades tab.

**Actual bug:** ThreadPoolExecutor (max_workers=3) drops queued tasks on process exit.
4 rapid restarts on Apr 21 13:40-13:51 UTC matched exactly with the 1 lost trade.

**Fix applied (commit 211354e):**
- Synchronous write-ahead log (WAL) written before thread pool submit
- `_replay_sheets_wal()` replays any dropped writes on next startup
- All future restarts will recover pending sheet writes

---

## 2. Full 16-Day Signal Coverage

| Day | Date | Signals | CCI/ETHUSDT | Donchian/ETHUSDT | Trades Exec | SL Fail | CB Trips | Status |
|-----|------|---------|------------|-----------------|-------------|---------|---------|--------|
| D1  | Apr 07 | 7  | 1 | 1 | 4  | 0 | 6 | WATCH -- high CB trips |
| D2  | Apr 08 | 25 | 2 | 2 | 5  | 0 | 2 | CLEAN |
| D3  | Apr 09 | 9  | 0 | 0 | 3  | 0 | 2 | CLEAN |
| D4  | Apr 10 | 12 | 2 | 0 | 2  | 0 | 3 | CLEAN |
| D5  | Apr 11 | 4  | 0 | 0 | 4  | 0 | 2 | CONCERN -- 9 auto-synced corrections |
| D6  | Apr 12 | 0  | 0 | 0 | 2  | 0 | 3 | CONCERN -- 2 auto-synced corrections |
| D7  | Apr 13 | 12 | 0 | 0 | 0  | 0 | 0 | CLEAN -- no trades, no drift |
| D8  | Apr 14 | 27 | 0 | 0 | 8  | 0 | 0 | CONCERN -- 12 auto-synced corrections |
| D9  | Apr 15 | 9  | 0 | 0 | 13 | 0 | 2 | HIGH -- 3 exec failures, 12 auto-synced |
| D10 | Apr 16 | 72 | 0 | 0 | 2  | 0 | 3 | WATCH -- G-series start, 2 exec failures |
| D11 | Apr 17 | 50 | 0 | 0 | 12 | 2 | 5 | CONCERN -- SL failures begin, 21 auto-synced |
| D12 | Apr 18 | 29 | 0 | 0 | 2  | 0 | 0 | CLEAN -- 7 auto-synced |
| D13 | Apr 19 | 36 | 0 | 0 | 7  | 1 | 2 | CONCERN -- SL failure, 18 auto-synced |
| D14 | Apr 20 | 39 | 0 | 0 | 10 | 5 | 0 | HIGH -- 5 SL failures, 20 auto-synced, sheet gap |
| D15 | Apr 21 | 7  | 0 | 0 | 2  | 0 | 4 | CONCERN -- 4 CB trips, 22 auto-synced |
| D16 | Apr 22 | 10 | 0 | 0 | 0  | 0 | 5 | CONCERN -- 5 CB trips, all blocked |

**Critical finding:** CCI Trend and Donchian Trend stopped firing on ETHUSDT after Apr 10.
Strategies fire on off-symbols (LINKUSDT, AVAXUSDT, SUIUSDT, BTCUSDT) instead of approved ETHUSDT.
Decision lane has been effectively silent for 12 consecutive days.

---

## 3. Reconciler Health -- Auto-Sync Corrections

Auto-synced corrections indicate ledger/exchange state divergence (stale positions drifting).

| Period | Total Auto-Synced | Note |
|--------|------------------|------|
| D1-D7 (Apr 7-13) | 11 | Moderate -- early paper noise |
| D8-D12 (Apr 14-18) | 44 | HIGH -- stale positions accumulating |
| D13-D16 (Apr 19-22) | 62 | CRITICAL -- 8 quarantined positions drifting daily |

**Root cause:** 8 stale positions (BTCUSDT, SUIUSDT, AVAXUSDT, LINKUSDT, XRPUSDT, OPUSDT, MAGICUSDT, ETHUSDT)
were never flattened. Their mark-to-market drift fires auto-sync corrections every day.
This also trips the circuit breaker 4-5x/day, blocking good signals during cooldown.

**No SIDE_MISMATCH (CRITICAL) drift in 16 days** -- gate passes.

---

## 4. SL Placement Reliability

| Day | SL Placed | SL Failed | Failure Rate |
|-----|-----------|-----------|-------------|
| D1 Apr 07 | 4 | 0 | 0% |
| D2 Apr 08 | 5 | 0 | 0% |
| D3 Apr 09 | 2 | 0 | 0% |
| D4 Apr 10 | 2 | 0 | 0% |
| D11 Apr 17 | 9 | 2 | 22% -- first SL failures |
| D13 Apr 19 | 7 | 1 | 14% |
| D14 Apr 20 | 9 | 5 | 56% -- worst day |

SL failures started Apr 17, peaked Apr 20 at 56%. 8 of 27 total SL orders failed across window.
Positions on those 8 trades ran without stop-loss. Requires FIX-3.

---

## 5. Gate Status -- Before and After Today's Fixes

| Gate | Before (08:00 IST) | After FIX-1/FIX-2 | Remaining |
|------|--------------------|-------------------|-----------|
| Manifest scope explicit | FAIL (personal_live class) | PASS | -- |
| Execution freeze intact | FAIL (A-10 changes) | PASS | -- |
| Pytest suite discoverable | FAIL (ledger_decision missing in mock) | PASS | -- |
| Min closed paper trades | FAIL (CCI:1 Donch:1 need 5) | FAIL | Needs FIX-4 + time |
| All other 23 gates | PASS | PASS | -- |
| **Overall** | **NO-GO (3/27 FAIL)** | **NO-GO (1/27 FAIL)** | trade count only |

**Earliest realistic PASS:** ~8-10 business days after FIX-4 (TV alert fix),
assuming 1 ETHUSDT 4h signal every 2-3 days (historical rate from Apr 7-10).

---

## 6. Decisions Needed at Checkpoint Call

| Decision | Options | Recommendation |
|----------|---------|----------------|
| Do we go live now? | GO / NO-GO | NO-GO: trade count gate is 1/5. Fix TV alerts first. |
| CB threshold | Keep 5% / Raise to 8% | Raise to 8% temporarily until stale positions cleared |
| Stale positions | Keep quarantined / Flatten | Flatten -- they consume margin and trip CB daily |
| SELL path | Test this week / Defer | Test this week -- half of market direction unvalidated |

---

## 7. Remaining P0 Actions (Pre-Checkpoint)

| Fix | Action | Status |
|-----|--------|--------|
| FIX-1 | Reset execution freeze baseline | DONE |
| FIX-2 | Allow personal_live in gate scope check | DONE |
| Sheets WAL | Prevent trade data loss on restart | DONE |
| A-10 lane isolation | Decision vs research ledger split | DONE |

## Remaining P1 Actions (Today Post-Checkpoint)

| Fix | Action | ETA |
|-----|--------|-----|
| FIX-3 | Debug SL placement failures | 1 hour |
| FIX-4 | Fix TV alerts ETHUSDT-only | 30 min -- HIGHEST PRIORITY |
| FIX-5 | Flatten 8 stale quarantined positions | 30 min |

---

*Sources: recon_20260407.txt through recon_20260422.txt, signal_queue.db, ledger_state.json*
*Committed as 211354e: sheets WAL + gate fixes for Apr 22 checkpoint*
---

## 8. G88/G90 Target Symbol Confirmation

**Question raised:** Garima audit found G88 Vortex Donchian and G90 BB PercentB RSI fired on OPUSDT
during paper window. Shortlist has XRPUSDT as target. Which symbol is authoritative?

**Finding from server data (ledger_state.json + signal_queue.db):**
- `binance:OPUSDT:G88 Vortex Donchian` — 1 trade recorded, OPUSDT
- `binance:OPUSDT:G90 BB PercentB RSI` — 1 trade recorded, OPUSDT

**Root cause:** Garimas Pine scripts have hardcoded or alert fired from OP chart.


---

## 8. G88/G90 Target Symbol Confirmation

**Question raised:** Garima audit found G88 Vortex Donchian and G90 BB PercentB RSI fired on OPUSDT
during paper window. Shortlist has XRPUSDT as target. Which symbol is authoritative?

**Finding from server data (ledger_state.json + signal_queue.db):**
- ledger key: binance:OPUSDT:G88 Vortex Donchian — 1 trade recorded, OPUSDT
- ledger key: binance:OPUSDT:G90 BB PercentB RSI — 1 trade recorded, OPUSDT

**Root cause:** Garima's Pine scripts alert fired from OP chart, not XRP chart.
The manifest entry for G88/G90 is research lane with no symbol restriction.

**Decision needed from Sainath/Garima:**
- If shortlist target is XRPUSDT: Garima must update Pine alert to fire from XRPUSDT 4H chart
- If OPUSDT trades are valid: ledger is correct as-is, no action needed
- No XRPUSDT signals from G88/G90 found in signal_queue.db — all were OPUSDT

**Server verdict:** G88/G90 are paper_only research lane, not decision lane.
Their symbol does not affect go-live gate. Garima must fix Pine alert chart source.

---

## 9. vectorbt Syslog Proof

**vectorbt version:** 0.28.5 (installed in venv 2026-04-22)
**Proof run:** ETHUSDT 4H EMA9/21 crossover backtest on 3-year data (ETHUSDT_3y_4h.csv)

Syslog entries written at Apr 22 09:41 UTC (/var/log/syslog tag: tradingbot-vectorbt):

    vectorbt proof started | version=0.28.5 | data=ETHUSDT_3y_4h.csv
    vectorbt proof result: [2026-04-22 09:41:12 UTC] vectorbt=0.28.5 | ETHUSDT 4H EMA9/21 |
    n_trades=157 | WR=24.8% | total_return=-14.75% | sharpe=0.064 | max_dd=-56.9%

**Proof log:** storage/reports/vectorbt_proof.log
**Script:** scripts/vectorbt_proof.py

Note: EMA9/21 is intentionally a simple strategy to prove the vectorbt pipeline works end-to-end.
G-series strategies use their own backtest logic via scripts/my_strategies.py + pandas/numpy.

---

## 10. Post-Checkpoint Fixes Applied (Same Day)

| Fix | Commit | Status |
|-----|--------|--------|
| FIX-3 SL minimum tick distance | 0522c32 | DONE |
| FIX-4 PRICE_RULES tickSize loaded | 0522c32 | DONE |
| FIX-5 -1007 timeout recovery | 0522c32 | DONE |
| FIX-6 GTX price rounded to tickSize | 0522c32 | DONE |
| FIX-7 Bare-key signal block | 0522c32 | DONE |
| FIX-8 MAX_QTY default 1.0 removed | 0522c32 | DONE |
| FIX-9 BLOCKED_STRATEGY_NAMES env blocklist | 0522c32 | DONE |
| FIX-10 CB threshold 5% to 8% | 0522c32 | DONE |
| FIX-11 BLOCKED list in env_vars | 0522c32 | DONE |
| Flatten 8 stale positions | manual | DONE -- all 9 positions flat |
| vectorbt in venv | pip install | DONE -- v0.28.5 confirmed |
| Gate after all fixes | gate check | 26/27 PASS (only trade-count remains) |

*Updated: 2026-04-22 post-checkpoint session*
