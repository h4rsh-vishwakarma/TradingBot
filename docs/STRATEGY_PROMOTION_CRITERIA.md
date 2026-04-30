# Strategy Promotion Criteria

> Canonical document for moving strategies from Garima research lane into
> Harsh's .
>
> Last updated: 2026-04-29
> Owners: Garima (research output) + Harsh (manifest authority) + Sainath (final sign-off)

---

## Promotion Ladder



No step may be skipped. Research-lane evidence does not substitute for
paper-window evidence on the production exchange.

---

## Gate 1 — Backtest Provenance (required before paper_only entry)

| Requirement | Value |
|-------------|-------|
| Fixed notional per trade | 00 |
| Slippage | 0.1% per side |
| Commission | 0.04% taker (Binance Futures) |
| Out-of-sample split | 30% held out (time-ordered, no leakage) |
| Minimum total trades (full period) | 100 |
| Minimum OOS trades | 30 |
| OOS Sharpe | ≥ 0.5 |
| OOS Profit Factor | ≥ 1.05 |
| Max drawdown (full period) | ≤ 25% |
| Lookahead bias | Must be explicitly verified absent |
| Backtest hash | Required in manifest  field |

Garima's  uses a stricter threshold (Sharpe ≥ 0.8,
DSR_TCA > 0) — strategies that clear auto_discovery automatically satisfy Gate 1.

---

## Gate 2 — Paper Window (required before candidate_for_tiny_capital)

| Requirement | Value |
|-------------|-------|
| Minimum paper-window duration | 7 days |
| Minimum bot-visible signals | 5 |
| Minimum closed paper trades | 5 (4H strategies), 10 (1H), 20 (15m) |
| Signal source | Must arrive via TradingView webhook on production server |
| Exchange | Must execute on the same Binance Futures endpoint (testnet) |
| Paper P&L vs backtest OOS | Must be within ±40% of expected OOS daily ROI |


---

## Gate 3 — Human Review (required before candidate_for_tiny_capital with real capital)

1. Sainath reviews the backtest hash + OOS metrics.
2. Harsh verifies TradingView alert is correctly wired and signals are flowing.
3. Manifest entry is updated with  and .
4.  must return VERDICT: GO (all 30 gates pass).
5.  6-step checklist must be completed.

AUTO_PROMOTED entries (set by ) skip step 1–2 above only if
 is explicitly set. The default is  (frozen).

---

## Canonical Repository

- **Harsh execution repo** (source of truth for manifest): 
- **Garima research repo** (source of truth for discoveries):  on GitHub
- **Nomination path**: Garima posts discovery hash + metrics → Harsh adds  entry →
  paper window runs →  or manual promotion to  →
  Sainath review → 

---

## What Is NOT Sufficient for Promotion

- Backtest profit alone (without OOS split and hash)
- Paper sim engine results (these use different SL/TP/notional than the live strategy)
- Garima's  results alone (they satisfy Gate 1 only)
- Runtime logs or Telegram reports without corresponding committed evidence
