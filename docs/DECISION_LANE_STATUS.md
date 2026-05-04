# Decision Lane Status Report
> **Last updated: 2026-05-04 (H-P01 — synced to manifest v24; P-11 withdrawals reflected)**
> **Scope: EMPTY — 0 active candidates, 0 P07 nominees**
> **Manifest v24** — 0 candidate_for_tiny_capital; 31 paper_only; 0 P07_NOMINEE; 3 P07_WITHDRAWN; 2 R01_RETIRED
> Evidence source map: [docs/TRACKER_SOURCE_OF_TRUTH.md](TRACKER_SOURCE_OF_TRUTH.md)

---

## Current State

**DECISION LANE IS EMPTY.** No candidate_for_tiny_capital entries exist in the manifest.
No P-07 nominees remain — all three were withdrawn per Sainath P-11 (2026-05-02) due to IS/OOS ratio failures.
Capital discussion is not permitted until a new candidate completes the full promotion ladder:
Gate 1 (Python OOS + IS/OOS ≤4x + TV rerun) → Gate 2 (20–30-day paper window) → Gate 3 (Sainath sign-off).

---

## P-07 Nominees — ALL WITHDRAWN (P-11, 2026-05-02)

| Strategy | Symbol | IS PF | OOS PF | IS/OOS Ratio | Withdrawal Reason |
|----------|--------|-------|--------|--------------|-------------------|
| G83 DeMarker Donchian | ETHUSDT | 6.38 | 0.52 | 12.3x | IS/OOS ratio 12.3x > 4x hard gate; OOS PF=0.52 <1.0 |
| G88 Vortex Donchian | XRPUSDT | 24.36 | 0.31 | 78.6x | IS/OOS ratio 78.6x > 4x hard gate; OOS PF=0.31 <1.0 |
| G111 Supertrend Donchian | LINKUSDT | 7.54 | 0.90 | 8.4x | IS/OOS ratio 8.4x > 4x hard gate; OOS PF=0.90 <1.0 |

All three withdrawn per Sainath P-11 decision (2026-05-02). No TV alerts created. No carry-forward to capital.
Next cycle: Garima must produce new Gate 1 nominees with IS/OOS ratio ≤4x and TV rerun PF confirmed before nomination.

---

## Former Candidates — Retired

| Strategy | Final Label | R-04 Python OOS PF | TV Rerun PF (corrected 4% trail) | Disposition |
|----------|-------------|-------------------|----------------------------------|-------------|
| CCI Trend (ETHUSDT 4H) | R01_RETIRED | 3.998 | 1.08 | Retired 2026-05-01 — TV/Python gap 3.7x, below practical gate |
| Donchian Trend (ETHUSDT 4H) | R01_RETIRED | 7.175 | 0.93 | Retired 2026-05-01 — TV rerun PF<1.0 (hard fail), gap 7.7x |

**History:** Both cleared Gate 1 on Python OOS (R-04, 2026-05-01) after trail bug fix. Garima TV rerun with corrected 4% trail revealed large TV/Python divergence. Both retired per R-01 decision.

---

## Gate Verdict

See  for the live verdict (updated nightly at 02:40 UTC).

5 structural FAILs remain that clear only when a new candidate completes the full promotion ladder:
- **Manifest scope:** 0 candidate_for_tiny_capital → clears when new nominee promoted
- **Candidate paper-lane inventory:** empty → clears with new candidate
- **Provenance fields missing:** partial → improving via manifest cleanup
- **Approved-lane signals fired:** 0 → clears when live TV alert + paper window runs
- **Decision-lane signal active:** never recorded → clears when candidate fires real TV signal

Non-structural FAILs cleared today:
- **Execution-plane freeze detected** → clearing via H-P02 baseline refresh (freeze triggered by P-11 manifest change)

---

## Infra Fixes Applied 2026-05-01 to 2026-05-04

| Fix | Commit | Impact |
|-----|--------|--------|
| Removed stale trading_orchestrator.service | H-01/H-02 (6dc96dc) | Eliminated duplicate orchestrator respawn loop |
| APPROVAL_MANIFEST_PATH env var in webhook_server + tests | T-B (5c4139b) | Integration tests pass; 403 gate testable in isolation |
| Gunicorn service file aligned with live config | T-D (615d406) | Deploy artifact matches running config |
| R-04 Pine trail bug fixed; manifest v20; R04_PASS labels | H-03 (f63ee6b) | CCI Trend + Donchian Trend cleared Gate 1 (since retired) |
| Test/demo strategy hard-block | P-01 (34692b8) | Defense-in-depth: test/demo names rejected at boundary |
| P-08: manifest v21 — CCI/Donchian retired, G83/G88/G111 nominated | P-08 (8365a42) | Fresh nominee slate after R-01 retirements |
| P-11: manifest v24 — G83/G88/G111 withdrawn (IS/OOS ratio fails) | 1d6a577 | Decision lane fully reset |
| H-P01: DECISION_LANE_STATUS.md synced to manifest v24 | H-P01 (this commit) | Governance doc no longer shows stale nominees |

---

## Position Reconciliation (P-02, 2026-05-01)

- **Category A (stale testnet, RESOLVED):** 6 pre-governance positions manually closed 2026-04-13. Evidence:  (status=RESOLVED).
- **Category B (paper_only activity, expected):** LDOUSDT/ETHUSDT entries from ML Lorentzian, G27, G92, G94 paper_only monitoring. Testnet paper trades only — no real capital.

Full reconciliation: 

---

## Next Milestone

| Gate | Requirement | ETA |
|------|-------------|-----|
| **G-R02 — IS/OOS gate upstream** | Garima adds IS/OOS ≤4x gate to strategy_promotion.py | 2026-05-04 |
| **Gate 1 — New nominees** | Garima: Python OOS + IS/OOS ≤4x + TV rerun on quarantined candidates or auto_alpha_discoveries | ~2026-05-06 |
| **Nomination** | Garima proposes 1–2 nominees; Sainath approval required | After Gate 1 |
| **P-09 equivalent — TV alerts** | Harsh creates TV alerts for approved nominees | After nomination |
| **Gate 2 — Paper window** | 20–30 days of clean live paper signals (real TradingView webhooks) | ~3–4 weeks after TV alerts |
| **Gate 3 — Sainath sign-off** | Review paper evidence + candidate_for_tiny_capital promotion request | After Gate 2 |

---

*Historical fix logs, gate histories, and checkpoint assessments have been moved to commit history and RUNTIME_LOG.md.*
*This file contains only current decision-lane state.*
