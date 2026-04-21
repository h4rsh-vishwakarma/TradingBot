#!/usr/bin/env python3
"""
Testnet/mainnet safety invariant check.

Hard rule:
  If BINANCE_TESTNET is NOT true (i.e., running on mainnet real money),
  then LIVE_APPROVAL_CLASSES must NOT contain paper_only. Running paper_only
  strategies on mainnet real capital would live-execute unvetted tournament
  strategies immediately, bypassing M-10 enforcement.

This script is called from Orchestrator.__init__ at startup. If the invariant
is violated, it raises SystemExit with a clear error, preventing the
orchestrator from booting against real capital with the wrong gate config.

Can also be run standalone:
    venv/bin/python scripts/check_testnet_invariant.py
Exit code 0 = invariant holds, 1 = violated.
"""
from __future__ import annotations

import os
import sys


def is_testnet() -> bool:
    """True when ALL configured exchanges are on their testnet endpoints."""
    binance_testnet = os.getenv("BINANCE_TESTNET", "true").strip().lower() == "true"
    hl_testnet = os.getenv("HL_IS_TESTNET", "true").strip().lower() == "true"
    lighter_url = os.getenv("LIGHTER_API_URL", "").lower()
    lighter_real = os.getenv("LIGHTER_ALLOW_REAL_TRADES", "false").strip().lower() == "true"
    lighter_testnet = (not lighter_real) and ("testnet" in lighter_url or not lighter_url)
    return binance_testnet and hl_testnet and lighter_testnet


def live_approval_classes() -> set[str]:
    raw = os.getenv(
        "LIVE_APPROVAL_CLASSES",
        "candidate_for_tiny_capital,live_approved,approved",
    )
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def check() -> tuple[bool, str]:
    classes = live_approval_classes()
    testnet = is_testnet()
    if "paper_only" in classes and not testnet:
        return False, (
            "TESTNET INVARIANT VIOLATED: LIVE_APPROVAL_CLASSES contains \"paper_only\" "
            "but at least one exchange is on MAINNET real capital. "
            "Refusing to start orchestrator. Either remove paper_only from "
            "LIVE_APPROVAL_CLASSES, or set BINANCE_TESTNET=true / HL_IS_TESTNET=true "
            "/ LIGHTER_ALLOW_REAL_TRADES=false as appropriate before restarting."
        )
    if "paper_only" in classes and testnet:
        return True, "testnet mode confirmed; paper_only strategies allowed to execute on testnet"
    return True, "mainnet-safe gate config (paper_only excluded)"


def main() -> int:
    ok, message = check()
    prefix = "[testnet-invariant OK]" if ok else "[testnet-invariant FAIL]"
    stream = sys.stdout if ok else sys.stderr
    print(f"{prefix} {message}", file=stream)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
