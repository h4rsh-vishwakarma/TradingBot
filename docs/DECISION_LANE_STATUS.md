# Decision Lane Status Report
> Refreshed 2026-04-25 15:44 IST
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

## Gate Verdict (live as of 2026-04-25 15:40 IST)

```
VERDICT: NO-GO  (1 of 28 gates FAILED)
[FAIL] Candidates have min closed paper trades (4H=5,1H=10,15m=20) -- CCI Trend:1(NEED 5); Donchian Trend:0(NEED 5)
```

**Gate history:**
- Before Apr 22 session: NO-GO (3/27 FAIL)
- After FIX-1/FIX-2 (morning): NO-GO (1/27 FAIL)
- After FIX-3 through FIX-11 + TV cleanup (afternoon): NO-GO (1/27 FAIL)
- After Apr 24 AM fixes (gate_check NameError + freeze baseline reset): NO-GO (1/27 FAIL)
- After Apr 24 PM fixes (H-06..H-09: recency hard gate 72h added as gate #28): NO-GO (2/28 FAIL)
- **Apr 25 15:44 IST — live gate check: NO-GO (3/28 FAIL)** ← current
  - Gate #1 (inventory): Donchian Trend still MISSING despite H-01 claim — alert may exist in TV but has never fired on ETHUSDT, so inventory check cannot verify it. Alert must fire at least once.
  - Gate #2 (trade count): unchanged — CCI 1/5, Donchian 0/5. Market-gated.
  - Gate #3 (signal recency): 118.4h since last ETHUSDT CCI signal. CCI Trend alert liveness must be confirmed in TradingView UI.

**ACTION REQUIRED (Harsh — manual, TradingView UI):**
1. **Donchian Trend:** Log into TradingView → confirm alert exists on ETHUSDT 4H chart with exact name `Donchian Trend`. Use the Test button to fire a test signal. Confirm receipt in server `auto_scan.log`.
2. **CCI Trend:** Confirm alert is Active (not Expired/Paused). If expired, re-enable and test-fire.
3. Both gates (#1 and #3) will clear once a real or test signal arrives from each strategy on ETHUSDT.
4. Gate #2 (trade count) clears only when live market signals execute and close — no manual workaround.

---

## Decision Lane Evidence — Last 24h (ETH CCI+Donchian ONLY)

| Metric | Value |
|--------|-------|
| Decision-lane signals (ETH CCI+Donchian, last 24h) | 0 |
| Research/other signals (excluded from decision) | 16 |
| Decision-lane closed trades (all-time) | 1 (CCI Trend, -$1.86) |
| Decision-lane realized P&L | -$1.86 |
| Last CCI Trend ETHUSDT signal | 2026-04-20 05:51 UTC (118.4h ago) |
| Last Donchian Trend ETHUSDT signal | Never |

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
- RUNTIME_LOG.md reflects v15, 2 candidates, NO-GO (3/28 as of Apr 25) ✅
- **Remaining gaps:** Donchian Trend TV alert unconfirmed (MISSING); CCI Trend silent 118h; both need 5 closed trades ❌

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

*This file is refreshed on demand. Last refresh: 2026-04-25 15:44 IST*
*Do not confuse full-system RUNTIME_LOG.md with this decision-lane-only report.*
