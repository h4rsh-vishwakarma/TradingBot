# Decision Lane Status Report
> **Last updated: 2026-05-01 (P-05 prune — stale historical sections removed)**
> **Scope: EMPTY — 0 active candidates**
> **Manifest v20** — 0 candidate_for_tiny_capital; 30 paper_only
> Evidence source map: [docs/TRACKER_SOURCE_OF_TRUTH.md](TRACKER_SOURCE_OF_TRUTH.md)

---

## Current State

**DECISION LANE IS EMPTY.** No candidate_for_tiny_capital entries exist in the manifest.
Capital discussion is not permitted until a replacement candidate completes the full promotion ladder:
Gate 1 (Python OOS) → Gate 2 (30-day paper window) → Gate 3 (Sainath sign-off).

---

## Former Candidates — Status

| Strategy | Current Label | Python OOS PF (Trail Fixed) | Gate 1 | Paper Window |
|----------|--------------|---------------------------|--------|-------------|
| CCI Trend (ETHUSDT 4H) | R04_PASS | 3.998 | PASS | Starting 2026-05-01 (fresh from zero) |
| Donchian Trend (ETHUSDT 4H) | R04_PASS | 7.175 | PASS | Starting 2026-05-01 (fresh from zero) |

**History:** Both were demoted to R03_FLAGGED on 2026-04-29 (Python OOS PF<1.0 + Pine trail bug at effective 0.04%). Trail bug fixed in Pine scripts 2026-05-01. R-04 OOS rerun at correct 4% trail passes Gate 1. Old paper counts (CCI 1/5, Donchian 0/5) are **MOOT** — accumulated under buggy trail and cannot carry forward.

---

## Gate Verdict (live as of 2026-05-01)

```
VERDICT: NO-GO  (4 of 31 gates FAILED)
[FAIL] Manifest scope is explicit and limited -- 0 candidate_for_tiny_capital; 30 paper_only
[FAIL] Candidate paper-lane inventory verified -- No candidate_for_tiny_capital rows in inventory
[FAIL] Approved-lane signals fired during paper window -- 0 decision-lane signals recorded
[FAIL] Decision-lane ETHUSDT signal active (<72h) -- No decision-lane signal ever recorded
```

All 4 remaining FAIL gates are structural. They clear only when replacement candidates complete the full
promotion ladder and a fresh paper window accumulates evidence.

---

## Infra Fixes Applied 2026-05-01

| Fix | Commit | Impact |
|-----|--------|--------|
| Removed stale trading_orchestrator.service | H-01/H-02 (6dc96dc) | Eliminated duplicate orchestrator respawn loop |
| APPROVAL_MANIFEST_PATH env var in webhook_server + tests | T-B (5c4139b) | Integration tests pass; 403 gate testable in isolation |
| Gunicorn service file aligned with live config | T-D (615d406) | Deploy artifact matches running config |
| R-04 Pine trail bug fixed; manifest v20; R04_PASS labels | H-03 (f63ee6b) | CCI Trend + Donchian Trend cleared for fresh paper window |
| Test/demo strategy hard-block added (before manifest check) | P-01 (this session) | Defense-in-depth: test/demo names rejected at boundary |
| TV order-fill path uses APPROVAL_MANIFEST_PATH | P-01 (this session) | Consistent manifest path across all signal routes |

---

## Position Reconciliation (P-02, 2026-05-01)

Two "open position" types visible in heartbeat — both are non-issues:

- **Category A (stale testnet, RESOLVED):** 6 pre-governance positions (BTCUSDT, SUIUSDT, AVAXUSDT, LDOUSDT, LINKUSDT, XRPUSDT) manually closed 2026-04-13. Evidence: `storage/stale_position_quarantine.json` (status=RESOLVED).
- **Category B (paper_only activity, expected):** LDOUSDT/ETHUSDT entries from ML Lorentzian, G27, G92, G94, CCI Trend paper_only monitoring. These are testnet paper trades from approved manifest entries — no real capital. Expected behavior.

Full reconciliation: `storage/reports/position_reconciliation_2026-05-01.md`

---

## Next Milestone

| Gate | Requirement | ETA |
|------|-------------|-----|
| Gate 2 — Paper window start | Fresh TV alerts for CCI Trend + Donchian Trend on ETHUSDT 4H with fixed Pine scripts | 2026-05-01 (TV alert recreation needed) |
| Gate 2 — Paper window complete | 30 days of clean paper signals | ~2026-06-01 |
| Gate 3 — Sainath sign-off | Review paper evidence + request candidate_for_tiny_capital promotion | After 2026-06-01 |

---

*Historical fix logs, gate histories, and checkpoint assessments have been moved to commit history and RUNTIME_LOG.md.*
*This file contains only current decision-lane state. Stale ACTION REQUIRED items for demoted strategies removed 2026-05-01.*
