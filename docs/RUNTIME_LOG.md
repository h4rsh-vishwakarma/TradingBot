# Runtime Log — 2026-04-24

> Auto-generated — last updated `2026-04-24T23:10:02Z`
> GitHub repo: https://github.com/anythingai-labs/tradingview_webhook_bot

---

## Gate Check
| Item | Value |
|---|---|
| Verdict | **VERDICT: NO-GO  (3 of 28 gates FAILED)** |
| Gates passed | ? |
| Last run | 2026-04-24T23:10:02Z |

## Manifest — `config/approved_strategies.json`
| Item | Value |
|---|---|
| Version | v14 |
| Updated | 2026-04-23T13:47:09.093889+00:00 |
| Total candidates | 2 |
| ALPHA (live-ready) | 2 |
| RESEARCH (no Pine yet) | 0 |

### Production Decision Lane (ETH 4h ONLY)
| Strategy | Symbols | Timeframe | Label |
|---|---|---|---|
| CCI Trend | ['ETHUSDT'] | ['240'] | ALPHA |
| Donchian Trend | ['ETHUSDT'] | ['240'] | ALPHA |

### All ALPHA Strategies
- CCI Trend | ['ETHUSDT'] | label=ALPHA
- Donchian Trend | ['ETHUSDT'] | label=ALPHA

### RESEARCH (placeholder — not yet on TradingView)


## Decision-Lane Scoreboard (ETHUSDT 4H)
| Strategy | Closed ETHUSDT Trades | Last ETHUSDT Signal |
|---|---|---|
| CCI Trend | 1/5 (NEED MORE) | 2026-04-20T05:51:09 UTC |
| Donchian Trend | 0/5 (NEED MORE) | never |
> Gate requires 5 closed ETHUSDT trades per strategy. OK = threshold met.

## Signal Pipeline — Last 24h
| Item | Value |
|---|---|
| Signals received | 15 |
| Completed | 15 |
| Last signal | 2026-04-24 16:01 UTC |
| Last strategy | G68 OBV CCI Cross / MAGICUSDT |
| 401 unauthorized (today) | 0 (0 plain-text, 0 JSON) |

## Heartbeat
| Item | Value |
|---|---|
| Last heartbeat file | heartbeat_20260424_2305 |
| Verdict | HEALTHY |
| Cron schedule | every hour at :05 UTC |

## Open Positions -- Decision Lane (Harsh / live-approved)
- None
Realized P&L: $0.00

## Open Positions -- Research Lane (Garima / paper_only)
- None
Realized P&L: $0.00

## Stale Position Quarantine
| Item | Value |
|---|---|
| Status | **RESOLVED** |
| Count | 6 positions |
| File | `storage/stale_position_quarantine.json` |

## Known Issues — Requires Manual Action
_None outstanding as of 2026-04-16. All legacy 401 sources resolved (G-series JSON format + auth bypass + SKIP_PYTEST cron noise)._

**Resolved today (2026-04-16):**
- G-series alerts: now sending JSON format with correct strategy names (Harsh Pine Script update)
- CCI Trend / LDOUSDT old plain-text format: superseded by server-side TV order-fill bypass
- Garima test signals (`test_secret_123`): no hits since 2026-04-13; stale note removed
- TestStrategy: pytest-only infrastructure (operator=harsh), no manifest entry, no live alerts

## Services
| Service | URL | Status |
|---|---|---|
| Webhook | https://tradingbot.operatorbrief.xyz/health | UP |
| Dashboard | https://tradingbot.operatorbrief.xyz/ | UP |
| Orchestrator | process on EC2 | RUNNING |

## Commits Today (2026-04-24)
```
8157fa2 | 2026-04-24 22:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-24T22:10:01Z
e0db2bc | 2026-04-24 21:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-24T21:10:01Z
9d0a4e9 | 2026-04-24 20:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-24T20:10:01Z
c5f55cc | 2026-04-24 19:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-24T19:10:01Z
cb97051 | 2026-04-24 18:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-24T18:10:02Z
dcf3c97 | 2026-04-24 17:10:02 +0000 | chore: auto-update RUNTIME_LOG 2026-04-24T17:10:01Z
2c6b185 | 2026-04-24 16:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-24T16:10:01Z
6fe97af | 2026-04-24 15:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-24T15:10:01Z
2fef574 | 2026-04-24 14:10:02 +0000 | chore: auto-update RUNTIME_LOG 2026-04-24T14:10:01Z
d8d311a | 2026-04-24 13:10:02 +0000 | chore: auto-update RUNTIME_LOG 2026-04-24T13:10:01Z
1b8174a | 2026-04-24 12:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-24T12:10:01Z
0e26b97 | 2026-04-24 12:01:20 +0000 | fix(tests): extend Orchestrator import guard to test_lighter_client + test_strategy_decision_alerts
5fdeaf5 | 2026-04-24 11:55:21 +0000 | fix(audit): resolve H-02 H-03 H-04 H-05 from CEO Apr 24 audit
a4f73a6 | 2026-04-24 11:55:00 +0000 | chore: auto-update RUNTIME_LOG 2026-04-24T11:54:59Z
1c9075d | 2026-04-24 11:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-24T11:10:01Z
28212fd | 2026-04-24 10:10:04 +0000 | chore: auto-update RUNTIME_LOG 2026-04-24T10:10:02Z
3a3a00f | 2026-04-24 09:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-24T09:10:01Z
a97b248 | 2026-04-24 08:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-24T08:10:01Z
a55611f | 2026-04-24 08:05:59 +0000 | chore: auto-update RUNTIME_LOG 2026-04-24T08:05:58Z
b556d0e | 2026-04-24 08:05:47 +0000 | fix(docs): correct DECISION_LANE_STATUS gate verdict 2/27 → 1/27
3c62bf4 | 2026-04-24 08:04:39 +0000 | chore: auto-update RUNTIME_LOG 2026-04-24T08:04:38Z
eb70b1e | 2026-04-24 07:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-24T07:10:01Z
04202cc | 2026-04-24 06:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-24T06:10:01Z
4d34459 | 2026-04-24 05:14:16 +0000 | fix: resolve all 6 CEO-flagged doc/code issues
7894090 | 2026-04-24 05:10:02 +0000 | chore: auto-update RUNTIME_LOG 2026-04-24T05:10:01Z
eb00436 | 2026-04-24 04:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-24T04:10:01Z
0d0fe9f | 2026-04-24 03:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-24T03:10:02Z
9e211de | 2026-04-24 02:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-24T02:10:01Z
06e197c | 2026-04-24 01:10:05 +0000 | chore: auto-update RUNTIME_LOG 2026-04-24T01:10:02Z
281513d | 2026-04-24 00:10:04 +0000 | chore: auto-update RUNTIME_LOG 2026-04-24T00:10:01Z
1061db8 | 2026-04-23 23:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-23T23:10:01Z
886712b | 2026-04-23 22:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-23T22:10:01Z
69abab2 | 2026-04-23 21:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-23T21:10:01Z
7c97ef8 | 2026-04-23 20:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-23T20:10:02Z
1756d67 | 2026-04-23 19:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-23T19:10:01Z
e84079e | 2026-04-23 18:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-23T18:10:01Z
e80e83a | 2026-04-23 17:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-23T17:10:02Z
029ca4c | 2026-04-23 16:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-23T16:10:01Z
31cb0fc | 2026-04-23 15:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-23T15:10:01Z
b4a0469 | 2026-04-23 14:10:04 +0000 | chore: auto-update RUNTIME_LOG 2026-04-23T14:10:02Z
78460bb | 2026-04-23 13:49:39 +0000 | fix(audit): fix all 15 issues found in full application audit
b5be85a | 2026-04-23 13:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-23T13:10:02Z
b090526 | 2026-04-23 12:10:04 +0000 | chore: auto-update RUNTIME_LOG 2026-04-23T12:10:01Z
cdd6191 | 2026-04-23 11:33:46 +0000 | fix(report): 3 bugs in daily top-10 — REJECT filter, diversity bypass, add live section
595ed7a | 2026-04-23 11:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-23T11:10:01Z
deb25d4 | 2026-04-23 10:10:04 +0000 | chore: auto-update RUNTIME_LOG 2026-04-23T10:10:01Z
9659570 | 2026-04-23 10:05:56 +0000 | fix(P1-P5): shortlist priority cap, EMA alias, flatten ledger, pine stamps, vbt replay
38b1c6d | 2026-04-23 09:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-23T09:10:01Z
7303a4e | 2026-04-23 08:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-23T08:10:01Z
93c8f48 | 2026-04-23 07:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-23T07:10:01Z
527e632 | 2026-04-23 06:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-23T06:10:01Z
37e0145 | 2026-04-23 05:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-23T05:10:01Z
cd9e5be | 2026-04-23 04:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-23T04:10:01Z
e4c65cb | 2026-04-23 03:10:04 +0000 | chore: auto-update RUNTIME_LOG 2026-04-23T03:10:01Z
733f3ef | 2026-04-23 02:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-23T02:10:01Z
51b9b47 | 2026-04-23 01:10:02 +0000 | chore: auto-update RUNTIME_LOG 2026-04-23T01:10:01Z
22cbd74 | 2026-04-23 00:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-23T00:10:01Z
71061fc | 2026-04-22 23:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-22T23:10:01Z
bfb4cb8 | 2026-04-22 22:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-22T22:10:02Z
5f44730 | 2026-04-22 21:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-22T21:10:01Z
ccb5bf1 | 2026-04-22 20:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-22T20:10:01Z
8b3f71c | 2026-04-22 19:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-22T19:10:01Z
44577ec | 2026-04-22 18:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-22T18:10:02Z
a39e157 | 2026-04-22 17:10:04 +0000 | chore: auto-update RUNTIME_LOG 2026-04-22T17:10:02Z
9f0fe9f | 2026-04-22 16:10:02 +0000 | chore: auto-update RUNTIME_LOG 2026-04-22T16:10:01Z
08a01e9 | 2026-04-22 15:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-22T15:10:01Z
8918ebc | 2026-04-22 14:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-22T14:10:01Z
3e3ed90 | 2026-04-22 13:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-22T13:10:01Z
1787e97 | 2026-04-22 12:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-22T12:10:02Z
d7846ed | 2026-04-22 11:48:40 +0000 | docs(G-items): close G-01/G-02/G-04, freeze-block G-03 — Garima-side all items resolved 2026-04-22
d291aca | 2026-04-22 11:10:04 +0000 | chore: auto-update RUNTIME_LOG 2026-04-22T11:10:01Z
8036626 | 2026-04-22 10:11:46 +0000 | docs(H-02): refresh DECISION_LANE_STATUS.md — Apr 22 post-fix state
b2b4fa2 | 2026-04-22 10:11:36 +0000 | chore: auto-update RUNTIME_LOG 2026-04-22T10:11:35Z
00361a6 | 2026-04-22 10:10:04 +0000 | chore: auto-update RUNTIME_LOG 2026-04-22T10:10:01Z
f580fb2 | 2026-04-22 09:55:16 +0000 | docs: mark TV alert cleanup done + ledger reconciled clean
529a41b | 2026-04-22 09:44:22 +0000 | docs: add G88/G90 symbol confirmation + vectorbt syslog proof to checkpoint audit
0522c32 | 2026-04-22 09:15:54 +0000 | fix: apply FIX-3 through FIX-11 — SL, GTX, -1007, bare-key, MAX_QTY, blocklist, CB
d95d4f1 | 2026-04-22 09:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-22T09:10:01Z
eee430b | 2026-04-22 08:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-22T08:10:01Z
1aa156f | 2026-04-22 07:10:04 +0000 | chore: auto-update RUNTIME_LOG 2026-04-22T07:10:01Z
52e02ac | 2026-04-22 06:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-22T06:10:02Z
1508fdd | 2026-04-22 05:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-22T05:10:01Z
9cf0243 | 2026-04-22 05:09:37 +0000 | docs: add Apr 22 checkpoint audit + execution plan
211354e | 2026-04-22 05:08:15 +0000 | fix: sheets WAL + gate fixes for Apr 22 checkpoint
f6c589a | 2026-04-22 04:34:02 +0000 | chore: auto-update RUNTIME_LOG 2026-04-22T04:34:00Z
2b07cf3 | 2026-04-22 04:10:04 +0000 | chore: auto-update RUNTIME_LOG 2026-04-22T04:10:02Z
62fd397 | 2026-04-22 03:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-22T03:10:01Z
216cbe3 | 2026-04-22 02:10:04 +0000 | chore: auto-update RUNTIME_LOG 2026-04-22T02:10:01Z
bee2b03 | 2026-04-22 01:10:04 +0000 | chore: auto-update RUNTIME_LOG 2026-04-22T01:10:01Z
bd1b626 | 2026-04-22 00:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-22T00:10:02Z
50b07df | 2026-04-21 23:10:04 +0000 | chore: auto-update RUNTIME_LOG 2026-04-21T23:10:02Z
f7513e9 | 2026-04-21 22:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-21T22:10:01Z
5d1440e | 2026-04-21 21:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-21T21:10:02Z
d8ca641 | 2026-04-21 20:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-21T20:10:01Z
633edf0 | 2026-04-21 19:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-21T19:10:01Z
a67f4ef | 2026-04-21 18:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-21T18:10:02Z
a82dfba | 2026-04-21 17:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-21T17:10:01Z
0f9e8a8 | 2026-04-21 16:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-21T16:10:01Z
2d0714c | 2026-04-21 15:10:03 +0000 | chore: auto-update RUNTIME_LOG 2026-04-21T15:10:01Z
e64baa1 | 2026-04-21 20:03:03 +0530 | infra: freeze auto_promote + auto-push RUNTIME_LOG to GitHub hourly
68448e0 | 2026-04-21 19:21:19 +0530 | feat: add EMA Stack 15M as personal_live strategy (v11 manifest)
88963db | 2026-04-21 19:15:15 +0530 | governance: A-05 — record side/qty/entry_price in trade_history on close
29e4ba1 | 2026-04-21 19:09:40 +0530 | governance: Q-04 — wire lane isolation using BINANCE_RESEARCH_API_KEY
9c2159d | 2026-04-21 18:50:39 +0530 | governance: Q-01 Q-02 Q-03 — fix RUNTIME_LOG symbols + add TRACKER_SOURCE_OF_TRUTH
c95d7b5 | 2026-04-21 18:47:45 +0530 | merge: resolve conflicts accepting origin/main versions
ec11252 | 2026-04-18 12:25:57 +0000 | fix: timeframe-aware closed-trade threshold + normalized name matching
db8dadb | 2026-04-18 12:18:15 +0000 | feat: promotion_score + family/symbol concentration gate (Phase 1/2)
42be1a1 | 2026-04-18 12:14:09 +0000 | feat: gross_dd in discovery + min_closed_trades gate (Phase 1/2)
b25feff | 2026-04-18 11:50:29 +0000 | fix: exit signals bypass cooldown + log cooldown blocks to Sheets
bb143fd | 2026-04-18 10:01:36 +0000 | governance: G-01..G-05 CEO audit fixes — ETH-only lock, split reporting, tracker note
5ddcfd1 | 2026-04-18 07:45:35 +0000 | governance: sync runtime state to GitHub — manifest v10 freeze, F-01..F-04 fixes
399bd27 | 2026-04-18 04:42:28 +0000 | fix: update secretless order-fill test + telegram 429 retry hardening
7a42f6c | 2026-04-15 12:51:24 +0000 | fix: remove orphaned TV alert aliases + mark strategies no-script
9cff284 | 2026-04-15 12:26:28 +0000 | test: update exit-fallback test to verify cross-routing prevention
fe9ce75 | 2026-04-15 12:24:57 +0000 | fix: pre-7-day testing hardening — cross-routing, manifest, gate
b0e6822 | 2026-04-15 10:10:08 +0000 | chore: auto-update RUNTIME_LOG
2007bc9 | 2026-04-15 09:10:09 +0000 | chore: auto-update RUNTIME_LOG
1c54e00 | 2026-04-15 08:10:08 +0000 | chore: auto-update RUNTIME_LOG
988e21d | 2026-04-15 07:10:08 +0000 | chore: auto-update RUNTIME_LOG
db55945 | 2026-04-15 06:10:08 +0000 | chore: auto-update RUNTIME_LOG
98efed0 | 2026-04-15 05:10:09 +0000 | chore: auto-update RUNTIME_LOG
01a7497 | 2026-04-15 04:10:08 +0000 | chore: auto-update RUNTIME_LOG
29b9823 | 2026-04-15 03:10:10 +0000 | chore: auto-update RUNTIME_LOG
7ccc26a | 2026-04-15 02:10:08 +0000 | chore: auto-update RUNTIME_LOG
7649bdb | 2026-04-15 01:10:09 +0000 | chore: auto-update RUNTIME_LOG
10caff7 | 2026-04-15 00:10:09 +0000 | chore: auto-update RUNTIME_LOG
ea3681b | 2026-04-14 23:10:09 +0000 | chore: auto-update RUNTIME_LOG
23465b9 | 2026-04-14 22:10:08 +0000 | chore: auto-update RUNTIME_LOG
728ec0e | 2026-04-14 21:10:08 +0000 | chore: auto-update RUNTIME_LOG
25c9de7 | 2026-04-14 20:10:08 +0000 | chore: auto-update RUNTIME_LOG
b0efb04 | 2026-04-14 19:10:08 +0000 | chore: auto-update RUNTIME_LOG
c8ecdad | 2026-04-14 18:10:08 +0000 | chore: auto-update RUNTIME_LOG
a8c7ded | 2026-04-14 17:10:08 +0000 | chore: auto-update RUNTIME_LOG
2a97a62 | 2026-04-14 16:10:09 +0000 | chore: auto-update RUNTIME_LOG
e3a09ae | 2026-04-14 15:10:08 +0000 | chore: auto-update RUNTIME_LOG
2826ca5 | 2026-04-14 14:10:08 +0000 | chore: auto-update RUNTIME_LOG
98ccc75 | 2026-04-14 13:10:08 +0000 | chore: auto-update RUNTIME_LOG
ac65487 | 2026-04-14 12:10:08 +0000 | chore: auto-update RUNTIME_LOG
fe84a94 | 2026-04-14 11:10:08 +0000 | chore: auto-update RUNTIME_LOG
ab85132 | 2026-04-14 10:10:08 +0000 | chore: auto-update RUNTIME_LOG
5e04a4f | 2026-04-14 09:10:09 +0000 | chore: auto-update RUNTIME_LOG
c791cb9 | 2026-04-14 08:10:08 +0000 | chore: auto-update RUNTIME_LOG
e566fb0 | 2026-04-14 07:10:08 +0000 | chore: auto-update RUNTIME_LOG
cd8fbd5 | 2026-04-14 06:59:40 +0000 | paper: add G79 Fisher Donchian to paper lane — ETH+XRP only, DOT excluded
18551c6 | 2026-04-14 06:17:46 +0000 | fix: correct executedQty string key bug + update test for webhook allowlist
0c401b9 | 2026-04-14 06:10:38 +0000 | fix: use exchange-reported filled qty for ledger to stop reconciler drift
ad83aca | 2026-04-14 06:10:08 +0000 | chore: auto-update RUNTIME_LOG
6958940 | 2026-04-14 05:10:08 +0000 | chore: auto-update RUNTIME_LOG
c842805 | 2026-04-14 05:00:04 +0000 | fix: silently drop signals from unapproved/test strategies at webhook level
d0bd65f | 2026-04-14 04:10:08 +0000 | chore: auto-update RUNTIME_LOG
4227465 | 2026-04-14 03:10:09 +0000 | chore: auto-update RUNTIME_LOG
b1bda3e | 2026-04-14 02:10:10 +0000 | chore: auto-update RUNTIME_LOG
a2345ac | 2026-04-14 01:10:10 +0000 | chore: auto-update RUNTIME_LOG
5a2d699 | 2026-04-14 00:10:09 +0000 | chore: auto-update RUNTIME_LOG
28ad4c5 | 2026-04-13 23:10:08 +0000 | chore: auto-update RUNTIME_LOG
9f2817b | 2026-04-13 22:10:08 +0000 | chore: auto-update RUNTIME_LOG
fda5372 | 2026-04-13 21:10:08 +0000 | chore: auto-update RUNTIME_LOG
2f1b29b | 2026-04-13 20:10:08 +0000 | chore: auto-update RUNTIME_LOG
34ab5c6 | 2026-04-13 19:10:08 +0000 | chore: auto-update RUNTIME_LOG
5e25c17 | 2026-04-13 18:10:08 +0000 | chore: auto-update RUNTIME_LOG
4f57b42 | 2026-04-13 17:10:08 +0000 | chore: auto-update RUNTIME_LOG
c0e0f5b | 2026-04-13 16:10:08 +0000 | chore: auto-update RUNTIME_LOG
3aeda2c | 2026-04-13 15:10:08 +0000 | chore: auto-update RUNTIME_LOG
f1f4de5 | 2026-04-13 14:10:08 +0000 | chore: auto-update RUNTIME_LOG
e5cad7b | 2026-04-13 13:10:08 +0000 | chore: auto-update RUNTIME_LOG
6659cef | 2026-04-13 12:55:22 +0000 | docs: EOD report 2026-04-13 - reformatted per-task with exec summary, subtasks, timeline, code sync
80093d2 | 2026-04-13 12:50:49 +0000 | docs: add EOD report 2026-04-13 - full day summary T01-T13, 21 commits, 25/25 gates GO
aa6b186 | 2026-04-13 12:11:42 +0000 | feat: add 4 new combo strategies to manifest (OOS-validated by combo builder)
f36a47b | 2026-04-13 12:10:08 +0000 | chore: auto-update RUNTIME_LOG
cc40fc1 | 2026-04-13 12:07:37 +0000 | fix: ta.cci() takes 2 args in Pine V5 - changed ta.cci(high,low,close,20) to ta.cci(hlc3,20)
923ff90 | 2026-04-13 11:58:43 +0000 | fix: remove message= from alertcondition() - Pine V5 requires const string, payload sent via strategy.entry alert_message instead
e523609 | 2026-04-13 11:55:59 +0000 | fix: update webhook URL to https://tradingbot.operatorbrief.xyz across all scripts
862553c | 2026-04-13 11:50:30 +0000 | feat: /get_pine command - download Pine script file directly from Telegram
eb5120a | 2026-04-13 11:39:20 +0000 | feat: auto strategy discovery + TV alert guide + auto-promote pipeline
153abc8 | 2026-04-13 11:10:08 +0000 | chore: auto-update RUNTIME_LOG
3c244f0 | 2026-04-13 10:10:09 +0000 | chore: auto-update RUNTIME_LOG
b84f382 | 2026-04-13 09:45:34 +0000 | ops: add RUNTIME_LOG.md + gen_runtime_log.py - hourly auto-push to GitHub
23af41a | 2026-04-13 08:39:10 +0000 | fix: dedupe manifest, mark Garima G27/Aroon/G28 as RESEARCH, raise MAX_CANDIDATES to 15
a13c7da | 2026-04-13 07:18:59 +0000 | resolved: all stale positions closed on Binance Testnet 2026-04-13
8b27e24 | 2026-04-13 07:15:49 +0000 | fix: quarantine XRPUSDT test position from debug session
d961663 | 2026-04-13 07:05:32 +0000 | fix: heartbeat scope cap and inventory RESEARCH exemption
2a0fbb5 | 2026-04-13 07:02:41 +0000 | fix: normalize all manifest symbols to wildcard only
826660d | 2026-04-13 06:18:49 +0000 | fix: accept ticker field as fallback for symbol in webhook payload
2f90c45 | 2026-04-13 06:16:02 +0000 | fix: stale_position_gate honour wildcard * in approved_symbols
776d6d6 | 2026-04-13 06:14:22 +0000 | fix: expand CCI Trend and Donchian Trend symbols to wildcard for multi-asset alerts
1d21ee7 | 2026-04-13 05:43:28 +0000 | fix: gate checks for 10-strategy testnet research run
b04fc1b | 2026-04-13 05:38:47 +0000 | feat: promote all 8 strategies to candidate_for_tiny_capital for testnet live trading
be1cc5d | 2026-04-13 05:11:32 +0000 | fix(ops): R-04/R-05/R-10 operational hardening for Apr 14 gate
```

## Governance Note (P-01)
Runtime has 2 candidate_for_tiny_capital strategies.
Apr 14 decision scope is locked to: **CCI Trend + Donchian Trend on ETHUSDT 4h only.**
All other strategies are testnet/research — not part of Apr 14 go-live decision.

---
*This file is auto-generated every hour by `scripts/gen_runtime_log.py`*
*Do not edit manually — changes will be overwritten.*
