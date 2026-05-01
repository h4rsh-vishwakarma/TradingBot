# Decision Lane Status Report
> Refreshed 2026-04-30 19:00 IST
> **Scope: EMPTY — 0 active candidates**
> CCI Trend + Donchian Trend DEMOTED to paper_only on 2026-04-29 (R-03)
> All strategies are paper-only research — no candidate_for_tiny_capital entries exist
> Evidence source map: [docs/TRACKER_SOURCE_OF_TRUTH.md](TRACKER_SOURCE_OF_TRUTH.md)

---

## Decision Lane — ALPHA Strategies

**DECISION LANE IS EMPTY — manifest v19 has zero candidate_for_tiny_capital entries.**

### Former candidates — DEMOTED (R-03, 2026-04-29)

| Strategy | Demotion Reason | Python OOS PF | Trail Bug |
|----------|----------------|--------------|-----------|
| CCI Trend | trail_pct/100 bug — effective trail 0.04% not 4%. Python OOS PF=0.702, ROI=-0.065%/day | 0.702 ❌ | confirmed |
| Donchian Trend | trail_pct/100 bug — effective trail 0.04% not 4%. Python OOS PF=0.662, ROI=-0.071%/day | 0.662 ❌ | confirmed |

> **Old paper counts (CCI 1/5, Donchian 0/5) are MOOT** — these counts were accumulated
> under buggy TV trail settings. They cannot carry forward to any future paper window.
> Any re-nomination requires: Pine fix + TV rerun + Python OOS rerun + fresh paper window from zero.

---

## Gate Verdict (live as of 2026-05-01 10:40 IST)

```
VERDICT: NO-GO  (4 of 31 gates FAILED)
[FAIL] Manifest scope is explicit and limited -- 0 candidate_for_tiny_capital; 30 paper_only
[FAIL] Candidate paper-lane inventory verified -- No candidate_for_tiny_capital rows found in inventory report
[FAIL] Approved-lane signals fired during paper window -- 0 approved-lane signal(s) recorded since 2026-04-07
[FAIL] Decision-lane ETHUSDT signal active (<72h) -- No ETHUSDT decision-lane signal ever recorded in execution_metrics
```

> Infra fixes applied 2026-05-01:
> - Old trading_orchestrator.service stopped, disabled, and deleted from disk
> - 2 integration test failures fixed (APPROVAL_MANIFEST_PATH env var)
> - Execution freeze baseline refreshed -- CLEAN
> - Gunicorn service file aligned with running config (4w/4t, 127.0.0.1:5000)
> - 4 remaining FAIL gates are structural -- clear only when replacement candidates complete Gate 1 + paper window
**Gate history:**
- Before Apr 22 session: NO-GO (3/27 FAIL)
- After FIX-1/FIX-2 (morning): NO-GO (1/27 FAIL)
- After FIX-3 through FIX-11 + TV cleanup (afternoon): NO-GO (1/27 FAIL)
- After Apr 24 AM fixes (gate_check NameError + freeze baseline reset): NO-GO (1/27 FAIL)
- After Apr 24 PM fixes (H-06..H-09: recency hard gate 72h added as gate #28): NO-GO (2/28 FAIL)
- Apr 25 15:44 IST — live gate check: NO-GO (3/28 FAIL) — stale doc (predated 05:17 UTC signals)
- **Apr 25 19:10 IST — live gate check: NO-GO (1/28 FAIL)** (corrected)
  - Gate #1 (inventory): ✅ PASSED — CCI Trend:ETHUSDT=LIVE_VERIFIED; Donchian Trend:ETHUSDT=LIVE_VERIFIED (signals at 05:17 UTC confirmed in signal_queue.db)
  - Gate #2 (trade count): ❌ FAIL — CCI 1/5, Donchian 0/5. Market-gated. No workaround — requires live closed trades.
  - Gate #3 (signal recency): ✅ PASSED — Last ETHUSDT signal: Donchian Trend at 2026-04-25T05:17:41Z (8.4h ago, within 72h threshold).
  - H-21 fix applied: BLOCKED_STRATEGY_NAMES cleaned. Orchestrator restarted. Trade accumulation now unblocked.
- **Apr 25 19:30 IST — H-26..H-29 applied:** ← current
  - STOP_LOSS_PCT corrected 0.5 → 2.0; verified in /proc/474914/environ
  - ExecStartPre kill guard added to orchestrator service (H-27)
  - Gunicorn + telegram moved under live systemd (H-28)
  - deploy/env_vars.template created; gate check now validates SL 0.5–5.0% + BLOCKED list (H-29)
  - Gate count unchanged: 1/28 FAIL (trade count only — market-gated)

**ACTION REQUIRED (Harsh — manual, TradingView UI):**
1. **Donchian Trend:** Log into TradingView → confirm alert exists on ETHUSDT 4H chart with exact name `Donchian Trend`. Use the Test button to fire a test signal. Confirm receipt in server `auto_scan.log`.
2. **CCI Trend:** Confirm alert is Active (not Expired/Paused). If expired, re-enable and test-fire.
3. Both gates (#1 and #3) will clear once a real or test signal arrives from each strategy on ETHUSDT.
4. Gate #2 (trade count) clears only when live market signals execute and close — no manual workaround.

---

## Decision Lane Evidence — Last 24h (ETH CCI+Donchian ONLY)

| Metric | Value |
|--------|-------|
| Decision-lane signals (ETH CCI+Donchian, last 24h) | 2 (received at 05:17 UTC — were blocked by BLOCKED_STRATEGY_NAMES, now unblocked) |
| Research/other signals (excluded from decision) | 16 |
| Decision-lane closed trades (all-time) | 1 (CCI Trend, -$1.86) |
| Decision-lane realized P&L | -$1.86 |
| Last CCI Trend ETHUSDT signal | 2026-04-25 05:17 UTC (8.4h ago) — was blocked by BLOCKED_STRATEGY_NAMES, now unblocked (H-21) |
| Last Donchian Trend ETHUSDT signal | 2026-04-25 05:17 UTC (8.4h ago) — was blocked, now unblocked (H-21) |

*No decision-lane (ETH CCI+Donchian) signals in last 24h. Research-lane signals continue on MAGIC/LDO/SUI.*


---

## Decision Lane Open Positions (ledger_decision.json)

*No open decision-lane positions — exchange and ledger clean.*


---

## Decision Lane Closed Trades (most recent 10)

*No closed decision-lane trades yet.*


---

## Research Lane Open Positions (ledger_research.json — NOT decision evidence)

*No open research-lane positions — exchange and ledger clean.*

Research lane realized P&L: $0.0

> **Important:** Research lane positions above do NOT count as decision-lane evidence.
> They are paper_only monitoring under A-10 lane isolation.

---

## Post-Checkpoint Fixes Applied (2026-04-25 — H-26 through H-28)

| Fix ID | Fix | Impact |
|--------|-----|--------|
| H-26 | STOP_LOSS_PCT: 0.5 → 2.0 | Eliminates $11 stop on $2300 ETH — now $46, within 4H ATR range |
| H-27 | ExecStartPre kill guard in orchestrator.service | Prevents duplicate orchestrator PIDs on systemd restart |
| H-28 | Gunicorn + telegram_listener moved under systemd | All 3 processes now auto-restart, survive reboots |
| H-29 | deploy/env_vars.template created | env_vars is now version-controlled (redacted); gate check validates SL bounds + BLOCKED list |

**Applied:** 2026-04-25 19:30 IST by Harsh
**Orchestrator PID after fix:** 474914 (single, systemd-managed)
**STOP_LOSS_PCT confirmed in /proc/474914/environ:** 2.0

---

## Post-Checkpoint Fixes Applied (2026-04-25 — H-21 through H-25)

| Fix ID | Fix | Impact |
|--------|-----|--------|
| H-21 | BLOCKED_STRATEGY_NAMES: removed CCI Trend + Donchian Trend | Decision-lane can now execute; only test strategies blocked |
| H-22 | SL/TP fallback logic verified | Orchestrator uses env var when signal has sl_pct=0; env var was 0.5% (fixed in H-26) |
| H-23 | DECISION_LANE_STATUS.md corrected | Stale 3/28 FAIL → corrected to 1/28 FAIL |
| H-24 | Systemd service files created for all 3 processes | Orchestrator moved to systemd |
| H-25 | paper_sim_engine verified | 208 simulated trades, 41 strategy-symbol pairs confirmed running |

---

## Post-Checkpoint Fixes Applied (2026-04-22)

| Fix | Impact |
|-----|--------|
| FIX-3: SL minimum tick distance | Prevents "immediately trigger" on micro-price coins |
| FIX-4: PRICE_RULES tickSize loaded | 705 symbols get correct precision on startup |
| FIX-5: -1007 timeout recovery | Ghost position prevention |
| FIX-6: GTX price rounded to tickSize | Prevents precision rejection fallback to MARKET |
| FIX-7: Empty strategy field blocked | No more bare-key ledger writes |
| FIX-8: MAX_QTY default 1.0 removed | MAGIC/OP no longer get capped to $0.06 notional |
| FIX-9: BLOCKED_STRATEGY_NAMES | Server-side blocklist active |
| FIX-10: CB 5% → 8% | Stale-position drift no longer trips CB |
| FIX-11: Env blocklist added | CCI_Trend, Donchian_Trend, 44_PSAR blocked |
| H-21: Remove CCI/Donchian from blocklist | CCI Trend + Donchian Trend unblocked — trade-count gate can now accumulate. Orchestrator restarted via systemd. |
| H-22: SL/TP enforcement verified | Orchestrator fallback to STOP_LOSS_PCT=0.5 + TAKE_PROFIT_PCT=12.0 confirmed. Zero payload SL handled correctly. |
| H-24: Systemd service files created | tradingbot-orchestrator, tradingbot-webhook, tradingbot-telegram — all enabled, auto-restart on reboot. |
| Flatten 9 stale positions | Exchange: 0 open, Ledger: 0 open, CB baseline reset |
| vectorbt 0.28.5 in venv | Backtesting pipeline validated |

---

## CEO Checkpoint Assessment (Sainath, 2026-04-22)

**Status: pre-production** — well-instrumented, not yet production-ready.

Key findings from CEO review:
- GitHub now validates narrow ETH-only decision lane ✅
- Manifest v15 explicit (2 candidates, both ETHUSDT 4H; duplicate ML Lorentzian removed) ✅
- TRACKER_SOURCE_OF_TRUTH.md separates lane evidence from research ✅
- RUNTIME_LOG.md reflects v15, 2 candidates, NO-GO (3/28 as of Apr 25) ✅
- **Remaining gaps:** Both TV alerts LIVE_VERIFIED ✅; BLOCKED_STRATEGY_NAMES cleaned (H-21) ✅; both strategies need 5 closed trades ❌ (market-gated)

**What must not be widened yet:** candidate_for_tiny_capital, G94, ML Lorentzian, combos, broader asset scope.

**Critical path:** ETH-only alert repair ✅ → stale position clear ✅ → execution bug fixes ✅ → wait for 5 closed ETHUSDT trades → refresh docs → checkpoint verdict.

---

## Garima-Side G-Item Closure (2026-04-22 17:18 IST)

| Task | Status | Notes |
|------|--------|-------|
| G-01: Hold all promotions until gate clears | ✅ Closed | No paper_only strategy promoted. Manifest v11 unchanged. |
| G-02: Shortlist trim done | ✅ Closed | Trim complete. Add-coverage deferred to post-verdict. |
| G-03: search_budget wire into deployment-time DSR | 🔒 Freeze-blocked | Code wiring deferred post-verdict. Freeze discipline maintained. |
| G-04: G88/G90 asset-routing verified (Pine + TV inventory) | ✅ Closed | G88=OPUSDT, G90=OPUSDT confirmed in TV inventory. Swap deferred post-verdict. |

**Garima-side summary:** 3 of 4 G-items closed. G-03 correctly freeze-blocked — not deferred by oversight, blocked by governance freeze. No open Garima-side action items until checkpoint gate clears.


---

*This file is refreshed on demand. Last refresh: 2026-04-25 19:30 IST*
*Do not confuse full-system RUNTIME_LOG.md with this decision-lane-only report.*
