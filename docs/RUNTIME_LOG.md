# Runtime Log — 2026-04-13

> Auto-generated — last updated `2026-04-13T10:10:01Z`
> GitHub repo: https://github.com/anythingai-labs/tradingview_webhook_bot

---

## Gate Check
| Item | Value |
|---|---|
| Verdict | **VERDICT: GO  (25/25 gates passed)** |
| Gates passed | VERDICT: GO  (25/25 gates passed) |
| Last run | 2026-04-13T10:10:01Z |

## Manifest — `config/approved_strategies.json`
| Item | Value |
|---|---|
| Version | v4 |
| Updated | 2026-04-13T08:38:51Z |
| Total candidates | 13 |
| ALPHA (live-ready) | 5 |
| RESEARCH (no Pine yet) | 8 |

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
- G27 CCI Donchian Wide
- Aroon Oscillator Fusion
- G28 Donchian Short14

## Signal Pipeline — Last 24h
| Item | Value |
|---|---|
| Signals received | 3 |
| Completed | 3 |
| Last signal | 2026-04-13 06:18 UTC |
| Last strategy | Donchian Trend / LINKUSDT |
| 401 unauthorized (today) | 34 (18 plain-text, 16 JSON) |

## Heartbeat
| Item | Value |
|---|---|
| Last heartbeat file | heartbeat_20260413_1005 |
| Verdict | HEALTHY |
| Cron schedule | every hour at :05 UTC |

## Open Positions
- `binance:ETHUSDT` qty=0.074 @ 2251.05
- `binance:XRPUSDT` qty=-15.8 @ 1.3304

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
| Webhook | http://15.207.152.119:5000/health | UP |
| Dashboard | http://15.207.152.119:8501 | UP |
| Orchestrator | process on EC2 | RUNNING |

## Commits Today (2026-04-13)
```
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
Runtime has 13 candidate_for_tiny_capital strategies.
Apr 14 decision scope is locked to: **CCI Trend + Donchian Trend on ETHUSDT 4h only.**
All other strategies are testnet/research — not part of Apr 14 go-live decision.

---
*This file is auto-generated every hour by `scripts/gen_runtime_log.py`*
*Do not edit manually — changes will be overwritten.*
