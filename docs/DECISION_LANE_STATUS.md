# Decision Lane Status Report
> Refreshed 2026-04-25 21:00 IST
> **Scope: CCI Trend + Donchian Trend on ETHUSDT 4h ONLY**
> All other strategies are paper-only research — not part of go-live decision
> Evidence source map: [docs/TRACKER_SOURCE_OF_TRUTH.md](TRACKER_SOURCE_OF_TRUTH.md)

---

## Decision Lane — ALPHA Strategies (ETH 4h only)

| Strategy | Symbols | Timeframe | Operator | Approved |
|----------|---------|-----------|----------|---------|
| CCI Trend | ['ETHUSDT'] | ['240'] | harsh | 2026-04-07 |
| Donchian Trend | ['ETHUSDT'] | ['240'] | harsh | 2026-04-07 |

> **TV alerts repaired 2026-04-22:** All off-symbol CCI/Donchian alerts deleted.
> ETHUSDT 4H only alerts remain. Underscore variants deleted.
> **ML Lorentzian demoted to paper_only 2026-04-16** per A-03 governance freeze.

---

## Gate Verdict (live as of 2026-04-25 21:00 IST — from `go_live_gate_check.py`)

```
VERDICT: NO-GO  (1 of 28 gates FAILED)

[FAIL] Candidates have min closed paper trades (4H=5,1H=10,15m=20)
       CCI Trend:1(NEED 5); Donchian Trend:0(NEED 5)
       → Time-gated. Cannot be resolved without real market signals executing and closing.
```

**Gate history:**
- Before Apr 22 session: NO-GO (3/27 FAIL)
- After FIX-1/FIX-2 (morning): NO-GO (1/27 FAIL)
- After FIX-3 through FIX-11 + TV cleanup (afternoon): NO-GO (1/27 FAIL)
- After Apr 24 AM fixes (gate_check NameError + freeze baseline reset): NO-GO (1/27 FAIL)
- After Apr 24 PM fixes (H-06..H-09: recency hard gate 72h added as gate #28): NO-GO (2/28 FAIL)
- Apr 25 15:44 IST — live gate check: NO-GO (3/28 FAIL) — inventory + recency + trade count
- **Apr 25 21:00 IST — live gate check: NO-GO (1/28 FAIL)** ← current
  - Gate #1 (inventory): CLEARED — both CCI Trend and Donchian Trend LIVE_VERIFIED via test signals
  - Gate #2 (trade count): STILL FAILING — CCI 1/5, Donchian 0/5. Market-gated; needs real fills.
  - Gate #3 (signal recency): CLEARED — fix: recency now reads signal_queue.db (receipt) not execution_metrics.jsonl (fills). Last ETHUSDT signal: Donchian Trend at 2026-04-25T05:17:41Z (0.1h ago)

**Only remaining blocker:** Gate #2 — trade count. Needs 4 more CCI closed trades + 5 Donchian closed trades on ETHUSDT 4H. No manual workaround — wait for live market signals to trigger and close.

> ✅ **STOP_DISPATCH removed 2026-04-25** — File was active since 2026-04-23 11:45 UTC (42h). Removed by Harsh. Dispatch resumed. Decision-lane signals will now execute and closed trades will accumulate toward gate #2.

---

## Decision Lane Evidence — Last 24h (ETH CCI+Donchian ONLY)

| Metric | Value |
|--------|-------|
| Decision-lane signals (ETH CCI+Donchian, last 24h) | 0 |
| Research/other signals (excluded from decision) | 16 |
| Decision-lane closed trades (all-time) | 1 (CCI Trend, -$1.86) |
| Decision-lane realized P&L | -$1.86 |
| Last CCI Trend ETHUSDT signal | 2026-04-25 05:17 UTC (test signal, <1h ago) |
| Last Donchian Trend ETHUSDT signal | 2026-04-25 05:17 UTC (test signal, <1h ago) |

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
| Flatten 9 stale positions | Exchange: 0 open, Ledger: 0 open, CB baseline reset |
| vectorbt 0.28.5 in venv | Backtesting pipeline validated |

---

## CEO Checkpoint Assessment (Sainath, 2026-04-22)

**Status: pre-production** — well-instrumented, not yet production-ready.

Key findings from CEO review:
- GitHub now validates narrow ETH-only decision lane ✅
- Manifest v15 explicit (2 candidates, both ETHUSDT 4H; duplicate ML Lorentzian removed) ✅
- TRACKER_SOURCE_OF_TRUTH.md separates lane evidence from research ✅
- RUNTIME_LOG.md reflects v15, 2 candidates, NO-GO (1/28 as of Apr 25) ✅
- **Remaining gap:** Trade count only — CCI 1/5, Donchian 0/5. Both TV alerts confirmed LIVE_VERIFIED. ❌

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

*This file is refreshed on demand. Last refresh: 2026-04-25 21:00 IST*
*Do not confuse full-system RUNTIME_LOG.md with this decision-lane-only report.*
