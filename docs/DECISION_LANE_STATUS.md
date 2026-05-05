# Decision Lane Status Report
> **Last updated: 2026-05-05 (manifest v27; 1 P07_NOMINEE active)**
> **Scope: 1 P07_NOMINEE (Donchian_40 paper window ACTIVE day 2/30)**
> **Manifest v27** — 0 candidate_for_tiny_capital; 33 paper_only; 1 P07_NOMINEE; 4 P07_WITHDRAWN; 2 R01_RETIRED
> Evidence source map: [docs/TRACKER_SOURCE_OF_TRUTH.md](TRACKER_SOURCE_OF_TRUTH.md)

---

## Current State

**1 active P07 nominee:**
- `Donchian_40_ETHUSDT_4h` — Gate 1 PASS (2026-05-04), paper window **ACTIVE** (Day 2 of 30, started 2026-05-04T04:30Z)

No candidate_for_tiny_capital entries exist yet. Capital discussion remains blocked until Gate 2 (paper window) and Gate 3 (Sainath sign-off) complete.
Promotion ladder: Gate 1 ✓ → Gate 2 (30-day paper window) → Gate 3 (Sainath sign-off) → candidate_for_tiny_capital.

---

## P-07 Active Nominees

| Strategy | Symbol | Gate 1 IS PF | Gate 1 OOS PF | IS/OOS Ratio | OOS n | Status |
|----------|--------|-------------|--------------|--------------|-------|--------|
| Donchian_40_ETHUSDT_4h | ETHUSDT | 1.5214 | 1.7335 | 0.878x | 51 | ACTIVE (Day 2/30) |

Gate 1 evidence: `storage/gate1_results/gate1_oos_20260504T053215Z.json`
Governance: $500 fixed notional, 0.15%/side commission, 30% OOS holdout (2024-05-08 to 2026-03-20).
OOS outperformed IS (ratio <1x) — strong generalization. Paper window clock started 2026-05-04T04:30Z (TV alert deployed by Harsh).

Gate 1 evidence (PSAR_VolSurge/LINKUSDT): `storage/gate1_results/gate1_psar_keltner_20260505T060710Z.json`
⚠️ **Marginal pass:** IS PF=0.9326 < 1.0 (unprofitable in IS period); OOS MDD=-40.95% is high. OOS PF=1.0685 clears hard gate.
**Next action: create TradingView alert for LINKUSDT 4H PSAR + Volume Surge strategy to start paper window clock.**

---

## P-07 Nominees — ALL WITHDRAWN (P-11, 2026-05-02)

| Strategy | Symbol | IS PF | OOS PF | IS/OOS Ratio | Withdrawal Reason |
|----------|--------|-------|--------|--------------|-------------------|
| G83 DeMarker Donchian | ETHUSDT | 6.38 | 0.52 | 12.3x | IS/OOS ratio 12.3x > 4x hard gate; OOS PF=0.52 <1.0 |
| G88 Vortex Donchian | XRPUSDT | 24.36 | 0.31 | 78.6x | IS/OOS ratio 78.6x > 4x hard gate; OOS PF=0.31 <1.0 |
| G111 Supertrend Donchian | LINKUSDT | 7.54 | 0.90 | 8.4x | IS/OOS ratio 8.4x > 4x hard gate; OOS PF=0.90 <1.0 |
| PSAR_VolSurge_LINKUSDT_4h | LINKUSDT | 0.93 | 1.07 | 0.87x | Sainath decision 2026-05-05: IS PF<1.0 + OOS MDD=-40.95% — not suitable for paper window |

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

4 structural FAILs remain (all expected — paper window day 2):
- **Manifest scope:** 0 candidate_for_tiny_capital → clears when new nominee promoted
- **Candidate paper-lane inventory:** empty → clears with new candidate
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
| G-3: manifest v25 — Donchian_40_ETHUSDT_4h nominated as P07_NOMINEE | 7848b3e | 1 active nominee, Gate 1 PASS |
| H-P01: DECISION_LANE_STATUS.md synced to manifest v24 | H-P01 (this commit) | Governance doc no longer shows stale nominees |
| Paper window activated: Donchian_40 paper_window_start=2026-05-04T04:30Z | manifest v26 | 30-day clock running |
| Gate 1 PSAR/Keltner run: 1 PASS (LINKUSDT) / 8 FAIL — PSAR_VolSurge/LINKUSDT subsequently withdrawn per Sainath | manifest v27 | Gate 1 complete |
| Stale positions closed: 6 testnet positions flattened (BTCUSDT, LDOUSDT closed via market orders) | 2026-05-05 | Quarantine complete |

---

## Position Reconciliation (P-02, 2026-05-01)

- **Category A (stale testnet, RESOLVED):** 6 pre-governance positions manually closed 2026-04-13. Evidence:  (status=RESOLVED).
- **Category B (paper_only activity, expected):** LDOUSDT/ETHUSDT entries from ML Lorentzian, G27, G92, G94 paper_only monitoring. Testnet paper trades only — no real capital.

Full reconciliation: 

---

## Next Milestone

| Gate | Requirement | ETA |
|------|-------------|-----|
| **G-R02 — DONE** | IS/OOS gate added to strategy_promotion.py (check_is_oos_gate) | 2026-05-04 |
| **Gate 1 — DONE** | Donchian_40_ETHUSDT_4h: OOS PF=1.7335, IS/OOS=0.878x, OOS n=51. PASS. | 2026-05-04 |
| **Nomination — DONE** | Donchian_40_ETHUSDT_4h nominated to manifest v25 | 2026-05-04 |
| **P-09 — TV alert — DONE** | Harsh deployed ETHUSDT 4H Donchian(40) alert (2026-05-04 10:00 IST). Paper window ACTIVE. | 2026-05-04 |
| **Gate 2 — Paper window** | 20–30 days of clean live paper signals (real TradingView webhooks) | ~3–4 weeks after TV alerts |
| **Gate 3 — Sainath sign-off** | Review paper evidence + candidate_for_tiny_capital promotion request | After Gate 2 |

---

*Historical fix logs, gate histories, and checkpoint assessments have been moved to commit history and RUNTIME_LOG.md.*
*This file contains only current decision-lane state.*
