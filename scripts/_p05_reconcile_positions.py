#!/usr/bin/env python3
"""P-05: Reconcile and quarantine stale open positions in ledger_state.json.

Classification:
  ETHUSDT SHORT -0.256 @ 2321.78 : STALE_TESTNET_PRE_GOVERNANCE
    - NOT from Donchian_40 (Donchian_40 sends BUY/LONG; this is SHORT)
    - From pre-governance paper_only strategy (G99 or similar)
    - No corresponding trade history entry after 2026-04-19
  BTCUSDT SHORT -0.0047 @ 82471.6 : QUARANTINED_LEDGER_STALE
    - Already in stale_position_quarantine.json (flattened 2026-05-05)
    - Ledger was never zeroed after testnet flat
  OPUSDT SHORT -2000 @ 0.1488 : STALE_TESTNET_UNAPPROVED
    - Not in quarantine file
    - Non-approved pair (-2000 qty = $297 notional, testnet only)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
QUARANTINE_PATH = PROJECT_ROOT / "storage" / "stale_position_quarantine.json"
LEDGER_PATH = PROJECT_ROOT / "tradingview_webhook_bot" / "storage" / "ledger_state.json"

NOW = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
RECONCILED_BY = "Harsh"
REASON = "P-05 Sainath audit: stale pre-governance testnet positions zeroed. ETHUSDT NOT from Donchian_40 (Donchian_40 is BUY/LONG; position is SHORT). BTCUSDT already in quarantine but ledger not zeroed. OPUSDT unapproved pair."


def update_quarantine() -> None:
    q = json.loads(QUARANTINE_PATH.read_text(encoding="utf-8"))

    existing_keys = {p["key"] for p in q.get("positions", [])}

    new_entries = []
    if "binance:ETHUSDT" not in existing_keys:
        new_entries.append({
            "key": "binance:ETHUSDT",
            "symbol": "ETHUSDT",
            "side": "SHORT",
            "qty": -0.256,
            "entry": 2321.78,
            "note": "Stale pre-governance SHORT from paper_only strategy (NOT Donchian_40 which is BUY/LONG). No trade history after 2026-04-19. Zeroed in ledger 2026-05-07.",
            "classification": "STALE_TESTNET_PRE_GOVERNANCE",
            "status": "CLOSED",
            "flattened": True,
            "flattened_at": NOW,
            "flattened_method": "ledger_zero_p05_reconciliation_2026-05-07",
        })

    if "binance:OPUSDT" not in existing_keys:
        new_entries.append({
            "key": "binance:OPUSDT",
            "symbol": "OPUSDT",
            "side": "SHORT",
            "qty": -2000.0,
            "entry": 0.1488,
            "note": "Unexpected stale SHORT on non-approved pair. Origin unknown (not from any governed strategy). Notional $297 testnet only. Zeroed in ledger 2026-05-07.",
            "classification": "STALE_TESTNET_UNAPPROVED",
            "status": "CLOSED",
            "flattened": True,
            "flattened_at": NOW,
            "flattened_method": "ledger_zero_p05_reconciliation_2026-05-07",
        })

    # Update BTCUSDT entry to note ledger was also zeroed
    for pos in q.get("positions", []):
        if pos["key"] == "binance:BTCUSDT":
            pos["ledger_zero_at"] = NOW
            pos["ledger_note"] = "Ledger quantity zeroed P-05 2026-05-07 (was -0.0047 @ 82471.6, different qty from original quarantine -0.0162 @ 71675.32 suggesting partial close occurred)"

    q["positions"].extend(new_entries)
    q["last_reconciled_at"] = NOW
    q["last_reconciled_by"] = RECONCILED_BY
    q["reconciliation_note"] = REASON
    q["status"] = "RESOLVED"

    QUARANTINE_PATH.write_text(json.dumps(q, indent=2) + "\n", encoding="utf-8")
    print(f"Quarantine updated: added {len(new_entries)} entries, updated BTCUSDT")


def zero_ledger_positions() -> None:
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    positions = ledger.get("positions", {})

    zeroed = []
    for key in ["binance:ETHUSDT", "binance:BTCUSDT", "binance:OPUSDT"]:
        if key in positions:
            orig_qty = positions[key].get("quantity", 0)
            orig_price = positions[key].get("avg_price", 0)
            positions[key]["quantity"] = 0.0
            positions[key]["avg_price"] = 0.0
            positions[key]["_p05_zeroed_at"] = NOW
            positions[key]["_p05_original_qty"] = orig_qty
            positions[key]["_p05_original_price"] = orig_price
            positions[key]["_p05_reason"] = "stale_testnet_pre_governance"
            zeroed.append(key)
            print(f"Zeroed: {key} (was qty={orig_qty} @ {orig_price})")

    ledger["positions"] = positions
    LEDGER_PATH.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
    print(f"Ledger updated: zeroed {len(zeroed)} positions")


if __name__ == "__main__":
    print("=== P-05 Position Reconciliation ===")
    update_quarantine()
    zero_ledger_positions()
    print("Done. Verify with: cat storage/stale_position_quarantine.json | python3 -m json.tool")
