# Runtime Log — 2026-04-14

> Auto-generated — last updated `2026-04-14T21:10:01Z`
> GitHub repo: https://github.com/anythingai-labs/tradingview_webhook_bot

---

## Gate Check
| Item | Value |
|---|---|
| Verdict | **VERDICT: GO  (25/25 gates passed)** |
| Gates passed | VERDICT: GO  (25/25 gates passed) |
| Last run | 2026-04-14T21:10:01Z |

## Manifest — `config/approved_strategies.json`
| Item | Value |
|---|---|
| Version | v5 |
| Updated | 2026-04-14T13:16:04Z |
| Total candidates | 14 |
| ALPHA (live-ready) | 5 |
| RESEARCH (no Pine yet) | 9 |

### Apr 14 Production Decision Lane
| Strategy | Symbols | Timeframe | Label |
|---|---|---|---|
| CCI Trend | ['*'] | ['240'] | ALPHA |
| Donchian Trend | ['*'] | ['240'] | ALPHA |

### All ALPHA Strategies
- CCI Trend | ['*'] | label=ALPHA
- Donchian Trend | ['*'] | label=ALPHA
- 56_PSAR_Volume_Tight | ['*'] | label=ALPHA
- 44_PSAR_Volume_Surge | ['*'] | label=ALPHA
- 22_Ichimoku_Trend_Pro | ['*'] | label=ALPHA

### RESEARCH (placeholder — not yet on TradingView)
- 57_PSAR_Volume_Ultra
- 03_EMA_Break_Momentum
- 10_Aggressive_Entry
- 21_Full_Momentum
- 24_Keltner_Breakout
- RSI_x_BB_x_PSAR
- CCI_x_STOCH_x_OBV
- RSI_x_PSAR_x_STREND
- RSI_x_PSAR_x_OBV

## Signal Pipeline — Last 24h
| Item | Value |
|---|---|
| Signals received | 26 |
| Completed | 26 |
| Last signal | 2026-04-14 20:00 UTC |
| Last strategy | 03_EMA_Break_Momentum / ETHUSDT |
| 401 unauthorized (today) | 68 (38 plain-text, 30 JSON) |

## Heartbeat
| Item | Value |
|---|---|
| Last heartbeat file | heartbeat_20260414_2105 |
| Verdict | HEALTHY |
| Cron schedule | every hour at :05 UTC |

## Open Positions
- `binance:XRPUSDT` qty=-15.8 @ 1.3304
- `binance:BTCUSDT:21_Full_Momentum` qty=0.004899352849948881 @ 74187.55543478

## Stale Position Quarantine
| Item | Value |
|---|---|
| Status | **RESOLVED** |
| Count | 6 positions |
| File | `storage/stale_position_quarantine.json` |

## Known Issues — Requires Manual Action
1. **CCI Trend / LDOUSDT** — TradingView alert still using old plain-text order-fill format → 401
   - Fix: TradingView → Alert → Condition = "Any alert() function call" (not "Order fills")
2. **Garima test signals** — using wrong secret `test_secret_123` → 401
   - Fix: Use `squeeze_tradingview_cluster_2026_secure`

## Services
| Service | URL | Status |
|---|---|---|
| Webhook | https://tradingbot.operatorbrief.xyz/health | UP |
| Dashboard | http://15.207.152.119:8501 | UP |
| Orchestrator | process on EC2 | RUNNING |

## Commits Today (2026-04-14)
```
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
Runtime has 14 candidate_for_tiny_capital strategies.
Apr 14 decision scope is locked to: **CCI Trend + Donchian Trend on ETHUSDT 4h only.**
All other strategies are testnet/research — not part of Apr 14 go-live decision.

---
*This file is auto-generated every hour by `scripts/gen_runtime_log.py`*
*Do not edit manually — changes will be overwritten.*
