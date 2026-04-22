# Decision Lane Status Report
> Auto-regenerated 2026-04-22 17:18 IST
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

## Gate Verdict (live as of 2026-04-22 15:41 IST)

```
VERDICT: NO-GO  (1 of 27 gates FAILED)
[FAIL] Candidates have min closed paper trades (4H=5,1H=10,15m=20) -- CCI Trend:1(NEED 5); Donchian Trend:1(NEED 5)
```

**Gate history:**
- Before Apr 22 session: NO-GO (3/27 FAIL)
- After FIX-1/FIX-2 (morning): NO-GO (1/27 FAIL)
- After FIX-3 through FIX-11 + TV cleanup (afternoon): NO-GO (1/27 FAIL)
- **Remaining blocker:** CCI Trend needs 5 closed paper trades (has 1); Donchian Trend needs 5 (has 1)
- **ETA to gate clear:** 8-10 business days of ETHUSDT 4H signals at historical rate

---

## Decision Lane Evidence — Last 24h (ETH CCI+Donchian ONLY)

| Metric | Value |
|--------|-------|
| Decision-lane signals (ETH CCI+Donchian, last 24h) | 0 |
| Research/other signals (excluded from decision) | 17 |
| Decision-lane closed trades (all-time) | 0 |
| Decision-lane realized P&L | $0.0 |

*No decision-lane (ETH CCI+Donchian) signals in last 24h.*


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
- Manifest v11 explicit (2 candidates, both ETHUSDT 4H) ✅
- TRACKER_SOURCE_OF_TRUTH.md separates lane evidence from research ✅
- RUNTIME_LOG.md reflects v11, 2 candidates, NO-GO (1/27) ✅
- **Remaining gap:** Too few closed decision-lane paper trades (need 5, have 1 each) ❌

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

*This file is regenerated on demand. Last refresh: 2026-04-22 17:18 IST*
*Do not confuse full-system RUNTIME_LOG.md with this decision-lane-only report.*
