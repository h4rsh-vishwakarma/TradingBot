# P-10: Lane Isolation Architecture Design
> Status: OPEN (post-checkpoint)
> Created: 2026-04-20 by Harsh

## Problem Statement (P-03)
Currently both decision-lane (Harsh) and research-lane (Garima) trades:
- Execute against the SAME Binance testnet account (single BINANCE_API_KEY)
- Write to the SAME ledger_state.json
- Can affect each other margin-wise

This is a governance gap flagged in the Sainath CEO audit (P-03).

## Near-Term Mitigations (live now)
1. Ledger namespacing: each strategy has its own key (binance:SYMBOL:STRATEGY_NAME)
2. Guard 2: MAX_STRATEGIES_PER_SYMBOL=2 caps concurrent positions per symbol
3. Decision-lane reporting filters only candidate_for_tiny_capital strategies
4. DECISION_LANE_OPERATOR=harsh and DECISION_LANE_SYMBOLS=ETHUSDT in env_vars
5. DAILY_LOSS_LIMIT and circuit breaker protect account-level blowup

## Full Isolation Design (P-10 implementation)

### Option A: Separate Binance Testnet Account (RECOMMENDED)
- Requires: 2nd Binance testnet API key (from Sainath/user)
- DECISION_LANE_API_KEY, DECISION_LANE_API_SECRET env vars
- Orchestrator routes decision-lane signals to BINANCE_DL client
- Research-lane signals continue to BINANCE_RESEARCH client  
- Separate ledger files: ledger_decision.json vs ledger_research.json
- No margin interference between lanes

### Option B: Same Account, Separate Ledger Files
- Requires: env var DECISION_LANE_LEDGER_PATH
- Decision-lane writes to decision_ledger.json, research-lane to ledger_state.json
- Orchestrator checks signal.operator to route to correct ledger
- Limitation: still shares Binance margin (not truly isolated)

## Implementation Steps (post-checkpoint)

1. Get 2nd Binance testnet API key from user
2. Add BINANCE_RESEARCH_API_KEY + BINANCE_RESEARCH_API_SECRET to env_vars
3. Create BinanceClient factory that reads operator from signal
4. Instantiate two clients in orchestrator: exchange_decision + exchange_research  
5. Route apply_fill() to decision_ledger.json vs research_ledger.json
6. Update gen_runtime_log.py to read from correct ledger per lane
7. Update go_live_gate_check.py to use decision_ledger.json for gate evidence

## File Changes Required
- tradingview_webhook_bot/core/orchestrator.py: dual-client routing
- tradingview_webhook_bot/ledger/positions.py: dual-ledger init
- scripts/gen_runtime_log.py: lane-filtered ledger read
- scripts/go_live_gate_check.py: decision-ledger path
- /etc/tradingbot/env_vars: BINANCE_RESEARCH_API_KEY

## Blocker
Requires 2nd Binance testnet API key. Action: Sainath/user to provide.
Until then, Option B (separate ledger file with same account) can be implemented
as a partial isolation step.
