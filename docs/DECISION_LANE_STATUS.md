# Decision Lane Status Report
> **Last updated: 2026-05-01 (P-08 — manifest v21: CCI/Donchian retired, G83/G88/G111 nominated)**
> **Scope: EMPTY — 0 active candidates**
> **Manifest v21** — 0 candidate_for_tiny_capital; 31 paper_only; 3 P07_NOMINEE; 2 R01_RETIRED
> Evidence source map: [docs/TRACKER_SOURCE_OF_TRUTH.md](TRACKER_SOURCE_OF_TRUTH.md)

---

## Current State

**DECISION LANE IS EMPTY.** No candidate_for_tiny_capital entries exist in the manifest.
Capital discussion is not permitted until a replacement candidate completes the full promotion ladder:
Gate 1 (Python OOS) → Gate 2 (30-day paper window) → Gate 3 (Sainath sign-off).

---

## P-07 Nominees (paper window pending P-09 TV alerts)

| Strategy | Symbol | TF | Python OOS PF | OOS n | Gate 1 | Paper Window |
|----------|--------|----|--------------|-------|--------|-------------|
| G83 DeMarker Donchian | ETHUSDT | 4H | 1.18 | 217 | PASS | NOT STARTED — awaiting P-09 TV alert |
| G88 Vortex Donchian | XRPUSDT | 4H | 1.10 | 325 | PASS | NOT STARTED — awaiting P-09 TV alert |
| G111 Supertrend Donchian | SUIUSDT | 4H | 1.55 | 75 | PASS | NOT STARTED — awaiting P-09 TV alert |

**P-09 is the blocker.** Harsh must manually create TV alerts for all 3 nominees before the paper window clock starts. Paper window = 30 days from first live signal. Target capital review: ~2026-06-01.

---

## Former Candidates — Retired

| Strategy | Final Label | R-04 Python OOS PF | TV Rerun PF (corrected 4% trail) | Disposition |
|----------|-------------|-------------------|----------------------------------|-------------|
| CCI Trend (ETHUSDT 4H) | R01_RETIRED | 3.998 | 1.08 | Retired 2026-05-01 — TV/Python gap too large (3.7x), below practical gate |
| Donchian Trend (ETHUSDT 4H) | R01_RETIRED | 7.175 | 0.93 | Retired 2026-05-01 — TV rerun PF<1.0 (hard fail), gap 7.7x |

**History:** Both cleared Gate 1 on Python OOS (R-04, 2026-05-01) after trail bug fix. Garima's TV rerun with corrected 4% trail revealed large TV/Python divergence — CCI 1.08 (marginal), Donchian 0.93 (hard fail). Both retired per R-01 decision. Paper counts accumulated under buggy trail are moot.

---

## Gate Verdict (live as of 2026-05-01)

```
VERDICT: NO-GO  (4 of 31 gates FAILED)
[FAIL] Manifest scope is explicit and limited -- 0 candidate_for_tiny_capital; 31 paper_only
[FAIL] Candidate paper-lane inventory verified -- No candidate_for_tiny_capital rows in inventory
[FAIL] Approved-lane signals fired during paper window -- 0 decision-lane signals recorded
[FAIL] Decision-lane ETHUSDT signal active (<72h) -- No decision-lane signal ever recorded
```

All 4 remaining FAIL gates are structural. They clear only when P-07 nominees complete the full
promotion ladder and a fresh paper window accumulates evidence.

---

## Infra Fixes Applied 2026-05-01

| Fix | Commit | Impact |
|-----|--------|--------|
| Removed stale trading_orchestrator.service | H-01/H-02 (6dc96dc) | Eliminated duplicate orchestrator respawn loop |
| APPROVAL_MANIFEST_PATH env var in webhook_server + tests | T-B (5c4139b) | Integration tests pass; 403 gate testable in isolation |
| Gunicorn service file aligned with live config | T-D (615d406) | Deploy artifact matches running config |
| R-04 Pine trail bug fixed; manifest v20; R04_PASS labels | H-03 (f63ee6b) | CCI Trend + Donchian Trend cleared Gate 1 (since retired) |
| Test/demo strategy hard-block added (before manifest check) | P-01 (34692b8) | Defense-in-depth: test/demo names rejected at boundary |
| TV order-fill path uses APPROVAL_MANIFEST_PATH | P-01 (34692b8) | Consistent manifest path across all signal routes |
| P-08: manifest v21 — CCI/Donchian retired, G83/G88/G111 nominated | P-08 (this commit) | Fresh nominee slate after R-01 retirements |

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
| **P-09 — TV alerts** | Harsh creates TV alerts for G83/ETH 4H, G88/XRP 4H, G111/SUI 4H | ASAP (manual TradingView UI action) |
| Gate 2 — Paper window start | First live signal fires after TV alert creation | After P-09 |
| Gate 2 — Paper window complete | 30 days of clean paper signals | ~2026-06-01 |
| Gate 3 — Sainath sign-off | Review paper evidence + request candidate_for_tiny_capital promotion | After 2026-06-01 |

---

*Historical fix logs, gate histories, and checkpoint assessments have been moved to commit history and RUNTIME_LOG.md.*
*This file contains only current decision-lane state.*
