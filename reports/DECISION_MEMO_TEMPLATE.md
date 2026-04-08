# Day-8 Decision Memo — Trading System Go-Live

**Date:** ___________
**Author:** ___________
**Paper Window:** 2026-04-07 to 2026-04-14

---

## 1. Executive Summary

**VERDICT:** [ ] NO_GO  [ ] PAPER_ONLY  [ ] READY_FOR_TINY_CAPITAL

**Confidence:** ___/10
**Reason (1 sentence):** ___________

---

## 2. Evidence Summary

### 2.1 Paper Window Results (7 days)

| Metric | Value |
|--------|-------|
| Total signals received | |
| Total trades executed | |
| Trades blocked (manifest/cooldown/CB) | |
| Win rate | |
| Cumulative PnL | |
| Max daily drawdown | |
| Max cumulative drawdown | |

### 2.2 Reconciler Incidents

| Severity | Count |
|----------|-------|
| CRITICAL (side mismatch) | |
| HIGH (unexpected flat/open) | |
| MEDIUM (position mismatch) | |

### 2.3 Shortlist Provenance

| Strategy | Backtest Hash | Realistic Params | OOS Validated |
|----------|--------------|-------------------|---------------|
| | | | |

### 2.4 Go-Live Gate Check

| Gate | Status |
|------|--------|
| CI green (no bypass) | |
| Auth mode strict | |
| Manifest populated with provenance | |
| Inventory LIVE_VERIFIED | |
| Paper window complete (7 days) | |
| Zero CRITICAL drifts | |
| Dead letter queue clean | |

---

## 3. Verdict Branches

### NO_GO
- Any CRITICAL reconciler incident during window
- PnL diverges significantly from backtest expectations
- Shortlist provenance gap remains open
- Go-live gate check fails

### PAPER_ONLY
- Window clean but edge cases observed
- PnL positive but below expectations
- Minor operational issues to resolve

### READY_FOR_TINY_CAPITAL
- All go-live gates PASS
- Zero CRITICAL/HIGH drifts
- PnL tracks backtest expectations within tolerance
- Shortlist fully traceable to realistic reruns
- Recommended initial capital: $___

---

## 4. Risk Acknowledgements

- [ ] Max loss at tiny capital is bounded to $___
- [ ] Kill switch tested and operational
- [ ] Circuit breaker tested and operational
- [ ] Rollback plan documented

---

## 5. Sign-off

| Role | Name | Decision | Date |
|------|------|----------|------|
| Engineer | | | |
| Researcher | | | |
| CEO | | | |
