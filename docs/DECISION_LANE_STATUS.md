# Decision Lane Status Report
> Auto-generated 2026-04-18 15:24 IST
> **Scope: CCI Trend + Donchian Trend on ETHUSDT 4h ONLY**
> All other strategies are paper-only research — not part of go-live decision

---

## Decision Lane — ALPHA Strategies (ETH 4h only)

| Strategy | Exchange | Symbols | Timeframe | Operator | Approved |
|----------|----------|---------|-----------|----------|---------|
| CCI Trend | binance | ['ETHUSDT'] | ['240'] | harsh | 2026-04-07 |
| Donchian Trend | binance | ['ETHUSDT'] | ['240'] | harsh | 2026-04-07 |

> **ML Lorentzian demoted to paper_only 2026-04-16** per A-03 governance freeze.
> Reinstate only after: 7-day paper window + >=5 closed trades + DSR validation.

---

## Decision Lane Evidence — Last 24h (ETH CCI+Donchian ONLY)

| Metric | Value |
|--------|-------|
| Gate verdict | VERDICT: NO-GO  (1 of 25 gates FAILED) |
| Decision-lane signals (ETH CCI+Donchian) | 0 |
| Decision-lane completed | 0 |
| Total system signals (all strategies) | 56 |
| Non-lane signals (paper/research — excluded from decision evidence) | 56 |

### Decision Lane Open Positions (ETHUSDT only — counts as evidence)
| Symbol | Qty | Entry Price | Side |
|--------|-----|-------------|------|
| binance:ETHUSDT | 0.136 | 2324.58 | LONG |

### Research Lane Open Positions (paper_only — NOT decision-lane evidence)
| Symbol | Qty | Entry Price | Note |
|--------|-----|-------------|------|
| binance:BTCUSDT | -0.0162 | 76177.66790123 | paper_only — NOT decision evidence |
| binance:SUIUSDT | -330.0 | 0.9903 | paper_only — NOT decision evidence |
| binance:AVAXUSDT | -32.0 | 9.578 | paper_only — NOT decision evidence |
| binance:LDOUSDT | -1273.0 | 0.4216190887667 | paper_only — NOT decision evidence |
| binance:LINKUSDT | -0.02 | 9.561 | paper_only — NOT decision evidence |
| binance:XRPUSDT | 0.5 | 1.4463 | paper_only — NOT decision evidence |
| binance:OPUSDT | -2000.0 | 0.1303 | paper_only — NOT decision evidence |
| binance:MAGICUSDT | 585.0 | 0.0711051073447 | paper_only — NOT decision evidence |
| binance:UNIUSDT | 80.0 | 3.466 | paper_only — NOT decision evidence |

> **Important:** Research lane positions above are paper_only monitoring.
> They do NOT count as decision-lane evidence for checkpoint assessment.

---

## Evidence Mode — Long + Short (intentional)

The decision lane runs **both LONG and SHORT** during the current paper window.
CCI Trend and Donchian Trend are trend-following strategies that generate signals in both directions.
Short positions are valid evidence, not bugs. Long-only mode was evaluated but rejected:
it would halve the signal sample and bias the window. If the checkpoint requires long-only mode,
this can be switched before the next window with a single manifest flag.

---

## Paper-Only Research Lane (9 strategies)

These strategies are monitored but **not eligible for capital allocation** without:
1. 7-day closed paper window with 5+ trades
2. DSR (Deflated Sharpe Ratio) validation
3. Explicit promotion review by Harsh + Sainath

| Strategy | Operator | Notes |
|----------|----------|-------|
| G100 HigherHigh Structure | garima | PF=8.71, WR=84.5%, Sharpe=2.94, DSR>0 |
| G88 Vortex Donchian | garima | PF=6.11, WR=80.7%, Sharpe=2.64, DSR>0 |
| G89 Coppock Donchian | garima | PF=5.75, WR=80.1%, Sharpe=2.58, DSR>0 |
| G90 BB PercentB RSI | garima | PF=5.06, WR=80.0%, Sharpe=2.54, DSR>0 |
| G91 ATR Compression Breakout | garima | PF=10.88-13.49, WR=73-87%, Sharpe=2.73-3.24, DSR>0 |
| G92 RSI Divergence MACD | garima | PF=9.61-10.54, WR=80-87%, Sharpe=2.61-2.75, DSR>0 |
| G94 Pivot Point Reclaim | garima | PF=10.01-19.84, WR=74-85%, Sharpe=2.65-3.50, DSR>0, PBO=0.00 |
| G95 Inside Bar Breakout | garima | PF=11.26-14.90, WR=73-85%, Sharpe=2.73-3.36, DSR>0 |
| G99 Chande Momentum BB | garima | PF=9.06-17.29, WR=72-87%, Sharpe=2.55-3.73, DSR>0, PBO=0.00 |

---

## Governance Rules

- **Decision scope locked:** CCI Trend + Donchian Trend on ETHUSDT 4h only
- **Symbol enforcement (G-01):** Both ALPHA strategies restricted to ETHUSDT in manifest as of 2026-04-18
- **Reporting split (G-02):** This file shows decision-lane-only evidence. RUNTIME_LOG.md shows full system.
- **ML Lorentzian:** testnet research only — no live paper trades counted
- **Combo builder output:** DISCOVERY_ONLY — hard RuntimeError guard prevents manifest promotion
- **Promotion gate:** paper_only to ALPHA requires DSR + OOS + 5+ closed trades + Sainath review
- **Research positions:** non-ETH open positions are paper_only and excluded from checkpoint evidence

---
*Auto-generated 2026-04-18 15:24 IST | Manifest v10 | Gate: VERDICT: NO-GO  (1 of 25 gates FAILED)*