# Sign-Off Request — Stale Position Quarantine Resolution
**Date:** 2026-05-01
**From:** Harsh Vishwakarma
**To:** Sainath G (CEO)
**Re:** T-06 — Stale testnet position quarantine: evidence + sign-off request

---

## Summary

Six stale pre-window testnet positions were identified on 2026-04-13, quarantined, manually closed, and confirmed resolved. This document provides the evidence bundle and requests your formal sign-off so the incident can be closed in the tracker.

---

## What Happened

During the Mar-Apr 2026 integration testing phase, webhook alerts were accidentally fired on non-approved pairs (BTCUSDT, SUIUSDT, AVAXUSDT, LDOUSDT, LINKUSDT, XRPUSDT). These signals were processed by the bot and opened positions on Binance Testnet before the paper window governance was in place.

These positions were never part of the approved decision lane (ETHUSDT 4H only). They accumulated drift and were triggering false auto-sync corrections (+4-5 per day) that were masking legitimate circuit-breaker analysis.

---

## Positions Closed (All TESTNET — Zero Real Capital)

| Symbol | Side | Qty | Entry | Status |
|--------|------|-----|-------|--------|
| BTCUSDT | SHORT | 0.0162 | 71675.32 | CLOSED |
| SUIUSDT | SHORT | 1070.8 | 0.89 | CLOSED |
| AVAXUSDT | SHORT | 35.0 | 8.67 | CLOSED |
| LDOUSDT | SHORT | 1000.0 | 0.31 | CLOSED |
| LINKUSDT | SHORT | 6.8 | 9.34 | CLOSED |
| XRPUSDT | LONG | 15.8 | 1.3318 | CLOSED |

- All positions: Binance Testnet only. Zero real capital involved.
- Flattened at: 2026-04-13T07:18:30Z (manual close by Harsh)
- Quarantined at: 2026-04-13T10:30:00Z
- Evidence file: storage/stale_position_quarantine.json (status=RESOLVED)

---

## What Changed to Prevent Recurrence

1. Symbol lock enforced (G-01): Manifest now hard-restricts both CCI Trend and Donchian Trend to ETHUSDT only. Any signal on another symbol gets a 403 from the manifest gate (commit 8470c86, 2026-04-30).
2. Hard-403 manifest gate (T-01): All incoming signals are checked against approved_strategies.json before any processing. Unlisted strategy/symbol/timeframe combos are rejected at the server boundary.
3. Approved lane confirmed clean: Current execution freeze baseline shows tracked=11, diff=none. No drift on any approved symbol.

---

## Current State

| Item | Status |
|------|--------|
| Stale positions on testnet | All closed — none open |
| ETHUSDT execution lane | Clean — no unauthorized positions |
| Manifest gate | Active — hard-403 on unlisted entries |
| Symbol lock | ETHUSDT only for both candidates |
| Quarantine file | status=RESOLVED |

---

## Also: R-04 Re-Validation Complete (FYI)

While working on infra fixes today, the trail_pct bug in both Pine scripts was also corrected. Python OOS re-run with fixed 4% trail on 5Y ETHUSDT 4H data shows both strategies now pass Gate 1:

| Strategy | PF | Sharpe | Max DD | ROI/day | Gate 1 |
|---|---|---|---|---|---|
| CCI Trend | 3.998 | 9.03 | 4.74% | 0.529%/day | PASS |
| Donchian Trend | 7.175 | 12.91 | 2.85% | 0.894%/day | PASS |

Both are now in 30-day paper monitoring (label=R04_PASS, manifest v20). Tiny-capital promotion will require your sign-off after the paper window (~2026-06-01).

---

## Action Required (T-06)

Please reply to close T-06:

> T-06 acknowledged — stale position quarantine signed off.

Once received, T-06 will be marked CLOSED in the tracker.

---

*Commit trail: 8470c86 (symbol lock + manifest gate), 5c4139b (test isolation), f63ee6b (R-04 Pine fix + manifest v20)*
*Evidence: storage/stale_position_quarantine.json*
