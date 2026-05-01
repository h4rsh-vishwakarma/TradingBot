# Position Reconciliation — 2026-05-01
**Prepared by:** Harsh Vishwakarma
**Re:** P-02 — CEO audit item: open LDOUSDT and ETHUSDT positions under empty decision lane

---

## Finding from CEO Audit

Runtime heartbeat showed open LDOUSDT and ETHUSDT positions while the manifest v19 decision lane was empty (zero candidate_for_tiny_capital entries). Source/lane ownership was flagged as unresolved.

---

## Reconciliation

### Category A — Stale testnet positions (pre-governance, RESOLVED)

These were opened by webhook signals before the manifest gate existed (before 2026-04-30, commit 8470c86).
All manually closed 2026-04-13T07:18:30Z and quarantined.

| Symbol | Side | Entry | Strategy | Source | Status |
|--------|------|-------|----------|--------|--------|
| BTCUSDT | SHORT | 71675.32 | Pre-governance test | Non-approved pair | CLOSED Apr 13 |
| SUIUSDT | SHORT | 0.89 | Pre-governance test | Non-approved pair | CLOSED Apr 13 |
| AVAXUSDT | SHORT | 8.67 | Pre-governance test | Non-approved pair | CLOSED Apr 13 |
| LDOUSDT | SHORT | 0.31 | Pre-governance test | Non-approved pair | CLOSED Apr 13 |
| LINKUSDT | SHORT | 9.34 | Pre-governance test | Non-approved pair | CLOSED Apr 13 |
| XRPUSDT | LONG | 1.3318 | Demo_Momentum_Test debug | Non-approved | CLOSED Apr 13 |

Evidence: storage/stale_position_quarantine.json (status=RESOLVED, flattened_at=2026-04-13T07:18:30Z)

### Category B — Paper-only strategy signals (ongoing, testnet, expected)

These are NOT real positions. They are paper_only strategy signals processed by the orchestrator
on Binance Testnet. No real capital is involved. The open state reflects paper-lane monitoring
for approved paper_only entries in the manifest.

| Symbol | Strategy | Lane | Evidence |
|--------|----------|------|----------|
| ETHUSDT | CCI Trend | paper_only (manifest) | execution_metrics.jsonl — is_exit=False entries |
| ETHUSDT | G94 Pivot Point Reclaim | paper_only (manifest) | execution_metrics.jsonl |
| ETHUSDT | G99 Chande Momentum BB | paper_only (manifest) | execution_metrics.jsonl |
| LDOUSDT | ML Lorentzian Classification | paper_only (manifest) | execution_metrics.jsonl |
| LDOUSDT | G92 RSI Divergence MACD | paper_only (manifest) | execution_metrics.jsonl |
| LDOUSDT | G27 CCI Donchian Wide | paper_only (manifest) | execution_metrics.jsonl |

These signals were accepted by the webhook and processed as paper trades. They represent expected
behavior for paper_only monitoring. They show paper trade entries but exits may not be matched
due to the paper sim running separately from the execution metrics log.

**This is not a governance risk.** All strategies are in the manifest as paper_only. No capital is deployed.

---

## Root Cause of Heartbeat Confusion

The heartbeat combines Category A (stale closed testnet positions) and Category B (live paper_only signals)
in its position display, making it appear that there are unauthorized open positions. The distinction is:

- Category A: All CLOSED as of Apr 13. Evidence file updated, status=RESOLVED.
- Category B: Expected paper_only activity. Not capital-at-risk.

---

## What Changed to Prevent Recurrence

1. Hard-403 manifest gate (commit 8470c86, 2026-04-30): All signals checked against manifest before processing.
2. Symbol lock (G-01): Both candidates locked to ETHUSDT only.
3. Demo/test strategy block (P-01, 2026-05-01): Explicit denial for test/demo strategy names before manifest check.

---

## Open Action Items

None. All positions either CLOSED+quarantined or expected paper_only activity with manifest entries.
If the heartbeat display should distinguish paper-only positions from execution-lane positions, this is a
UI enhancement (not a governance issue) that can be addressed in the next sprint.

Evidence files:
- storage/stale_position_quarantine.json
- storage/reports/paper_validation/execution_metrics.jsonl
