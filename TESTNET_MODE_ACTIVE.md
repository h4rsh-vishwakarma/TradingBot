# TESTNET MODE IS ACTIVE

This bot is currently configured to execute `paper_only` manifest entries
against real exchange APIs for realistic infrastructure validation, but ALL
exchanges are pointed at their TESTNET endpoints (no real capital at risk).

## Current gate config (relaxed for testnet)

```
LIVE_APPROVAL_CLASSES=candidate_for_tiny_capital,live_approved,approved,paper_only
```

## Why this is safe today

| Control | Value | Meaning |
|---|---|---|
| `BINANCE_TESTNET` | `true` | Binance client uses testnet API (fake USDT) |
| `HL_IS_TESTNET` | `True` | Hyperliquid testnet |
| `LIGHTER_API_URL` | `https://testnet.zklighter.elliot.ai` | Lighter testnet |
| `LIGHTER_ALLOW_REAL_TRADES` | `false` | Extra kill switch |

The orchestrator now refuses to boot if any of these is flipped to mainnet
while `paper_only` is still in `LIVE_APPROVAL_CLASSES`. See
`scripts/check_testnet_invariant.py`.

## MANDATORY CHECKLIST BEFORE SWITCHING TO MAINNET

Do all 6 steps in order. Skipping any step risks live-executing unvetted
tournament strategies against real capital.

### 1. Tighten the gate

```bash
sudo nano /etc/tradingbot/env_vars   # or edit directly
# change LIVE_APPROVAL_CLASSES back to:
# LIVE_APPROVAL_CLASSES=candidate_for_tiny_capital,live_approved,approved
```

### 2. Review every manifest entry

```bash
venv/bin/python -c "import json; d=json.load(open(\"config/approved_strategies.json\")); \
  [print(a[\"strategy\"], a[\"exchange\"], a[\"symbols\"], a[\"approval_class\"]) for a in d[\"approvals\"]]"
```

Every entry marked `candidate_for_tiny_capital` MUST have:

- Realistic backtest evidence in `notes` (fixed $500, 0.1% slippage, 30% OOS)
- A completed paper window documented in `class_reason`
- Operator-level sign-off

If any entry does not meet this bar, demote it back to `paper_only` via
`scripts/approve_strategy.py --approval-class paper_only`.

### 3. Flatten all open testnet positions

```bash
# Confirm ledger state first
cat tradingview_webhook_bot/storage/ledger_state.json | python3 -m json.tool | head -60

# Flatten via scripts/kill_switch.py (dry run then real)
venv/bin/python scripts/kill_switch.py --dry-run
venv/bin/python scripts/kill_switch.py --confirm
```

Starting mainnet mode with stale testnet positions in the ledger is a data
corruption risk - the reconciler will see a phantom position on the real
exchange and misbehave.

### 4. Swap exchange keys

```bash
sudo nano /etc/tradingbot/env_vars
# Replace:
#   BINANCE_API_KEY / BINANCE_API_SECRET  -> real mainnet keys
#   BINANCE_TESTNET=true                  -> BINANCE_TESTNET=false
#   HL_IS_TESTNET="True"                  -> HL_IS_TESTNET="False"
#   LIGHTER_API_URL=...testnet...         -> mainnet URL
#   LIGHTER_ALLOW_REAL_TRADES=false       -> true (only if Lighter mainnet approved)
```

### 5. Rebaseline the execution freeze

```bash
venv/bin/python scripts/check_execution_freeze.py --refresh-baseline
```

### 6. Run the full go-live gate

```bash
venv/bin/python scripts/go_live_gate_check.py
```

Verdict MUST be `GO` with all 22 gates passing BEFORE restarting the
orchestrator against real capital. If anything fails, stop and fix it -
do NOT restart the orchestrator with real keys on a failing gate.

### 7. Restart orchestrator

```bash
sudo systemctl restart trading_orchestrator.service
sudo journalctl -u trading_orchestrator.service -n 50 --no-pager
```

The startup log MUST contain:

```
[testnet-invariant OK] mainnet-safe gate config (paper_only excluded)
```

If it instead logs `TESTNET INVARIANT VIOLATED`, the orchestrator has
refused to start - fix the config before proceeding.

---

## Rollback (if mainnet switch goes wrong)

```bash
# Revert env_vars from backup
sudo cp /tmp/env_vars.bak_<timestamp> /etc/tradingbot/env_vars
sudo systemctl restart trading_orchestrator.service
```

---

## Who edited this file and when

- Created: 2026-04-11 (Phase 1 testnet expansion)
- Guard script: scripts/check_testnet_invariant.py
- Linked commit: (will be filled by git commit message)
---
## Audit Confirmation — 2026-04-28

Confirmed by system audit on 2026-04-28:

| Item | Status | Evidence |
|---|---|---|
| Exchange mode | **TESTNET** | `BINANCE_TESTNET=true`, `HL_IS_TESTNET=True` in `/etc/tradingbot/env_vars` |
| Real capital at risk | **NO** | All exchanges on testnet endpoints — fake USDT only |
| Open positions | 1 open — LDOUSDT SHORT -1071 @ 0.4519 | Testnet position, paper_only lane (G94 Pivot Point Reclaim) |
| Decision-lane positions | None open | CCI Trend / Donchian Trend — no live testnet positions |
| Balance shown in circuit breaker | $3,767.27 | Binance **testnet** balance (fake USDT) |

This file must be updated before any mainnet switch.
