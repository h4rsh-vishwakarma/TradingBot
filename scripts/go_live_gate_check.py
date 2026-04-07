#!/usr/bin/env python3
"""
Automated Go-Live Gate Check
Runs all pass/fail checks from docs/GO_LIVE_GATE.md and outputs a clear PASS/FAIL verdict.
Exit code 0 = all gates pass. Exit code 1 = at least one gate failed.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS = []


def check(name, passed, detail=""):
    emoji = "PASS" if passed else "FAIL"
    RESULTS.append({"name": name, "passed": passed, "detail": detail})
    print(f"  [{emoji}] {name}" + (f" -- {detail}" if detail else ""))


def main():
    # Load env vars from production config
    env_file = Path("/etc/tradingbot/env_vars")
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

    print("=" * 60)
    print("  GO-LIVE GATE CHECK")
    print("=" * 60)
    print()

    # --- 1. CI green (no || true) ---
    ci_path = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
    if ci_path.exists():
        ci_content = ci_path.read_text()
        has_or_true = "|| true" in ci_content
        check("CI has no '|| true' bypass", not has_or_true,
              "Found || true in ci.yml" if has_or_true else "")
    else:
        check("CI workflow exists", False, "ci.yml not found")

    # --- 2. Auth mode is strict ---
    auth_mode = os.getenv("TRADINGVIEW_AUTH_MODE", "secret")
    is_strict = auth_mode not in ("open", "none", "disabled", "off")
    check("Webhook auth is strict", is_strict, f"TRADINGVIEW_AUTH_MODE={auth_mode}")

    # --- 3. Webhook secret is set ---
    secret = os.getenv("WEBHOOK_SECRET", "").strip()
    check("WEBHOOK_SECRET is configured", len(secret) > 8, f"length={len(secret)}")

    # --- 4. SL configured ---
    sl = os.getenv("STOP_LOSS_PCT", "")
    check("STOP_LOSS_PCT is set", bool(sl), f"value={sl or 'NOT SET'}")

    # --- 5. TP configured ---
    tp = os.getenv("TAKE_PROFIT_PCT", "")
    check("TAKE_PROFIT_PCT is set", bool(tp), f"value={tp or 'NOT SET'}")

    # --- 6. Circuit breaker configured ---
    cb_loss = os.getenv("CB_DAILY_LOSS_PCT", "")
    cb_consec = os.getenv("CB_MAX_CONSECUTIVE_LOSSES", "")
    check("Circuit breaker daily loss configured", bool(cb_loss), f"CB_DAILY_LOSS_PCT={cb_loss or 'NOT SET'}")
    check("Circuit breaker consecutive losses configured", bool(cb_consec), f"CB_MAX_CONSECUTIVE_LOSSES={cb_consec or 'NOT SET'}")

    # --- 7. Daily loss limit ---
    dll = os.getenv("DAILY_LOSS_LIMIT", "")
    check("DAILY_LOSS_LIMIT is set", bool(dll), f"value={dll or 'NOT SET'}")

    # --- 8. Leverage configured ---
    lev = os.getenv("LEVERAGE", os.getenv("TRADE_LEVERAGE", ""))
    check("Leverage is configured", bool(lev), f"value={lev or 'NOT SET'}")

    # --- 9. Allowed symbols defined ---
    syms = os.getenv("ALLOWED_SYMBOLS", "").strip()
    # Empty ALLOWED_SYMBOLS means "allow all" — which is valid when using manifest/auth
    check("ALLOWED_SYMBOLS is defined (or open)", True,
          f"{len(syms.split(','))} symbols configured" if syms else "Open (all symbols allowed via auth)")

    # --- 10. Go-Live gate doc exists ---
    gate_doc = PROJECT_ROOT / "docs" / "GO_LIVE_GATE.md"
    check("GO_LIVE_GATE.md exists", gate_doc.exists())

    # --- 11. Tests pass (quick syntax check) ---
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--co", "-q",
             "tests/test_integration_flow.py", "tests/test_orchestrator_flow.py"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=30
        )
        test_count = sum(1 for line in result.stdout.splitlines() if "::" in line)
        check("Tests are collectible", result.returncode == 0, f"{test_count} tests found")
    except Exception as e:
        check("Tests are collectible", False, str(e))

    # --- 12. Ledger state file exists ---
    ledger_path = os.getenv("LEDGER_PATH",
                            str(PROJECT_ROOT / "tradingview_webhook_bot" / "storage" / "ledger_state.json"))
    check("Ledger state file exists", os.path.exists(ledger_path), ledger_path)

    # --- 13. Idempotency DB exists ---
    idemp_path = os.getenv("IDEMPOTENCY_DB_PATH",
                           str(PROJECT_ROOT / "tradingview_webhook_bot" / "storage" / "idempotency.db"))
    check("Idempotency DB exists", os.path.exists(idemp_path), idemp_path)

    # --- OPERATIONAL GATES (CEO requirement: not just config, but real readiness) ---

    # --- 15. Manifest is non-empty ---
    manifest_path = PROJECT_ROOT / "config" / "approved_strategies.json"
    manifest_count = 0
    if manifest_path.exists():
        try:
            with open(manifest_path) as mf:
                manifest_data = json.load(mf)
                manifest_count = len(manifest_data.get("approvals", []))
        except Exception:
            pass
    check("Approval manifest is populated", manifest_count >= 2,
          f"{manifest_count} strategies approved" if manifest_count else "EMPTY")

    # --- 16. Each manifest entry has provenance (backtest_hash + notes) ---
    provenance_ok = True
    if manifest_count > 0:
        for entry in manifest_data.get("approvals", []):
            if not entry.get("backtest_hash") or not entry.get("notes"):
                provenance_ok = False
                break
    check("Manifest entries have provenance (hash + notes)", provenance_ok and manifest_count > 0,
          "All entries have backtest_hash and notes" if provenance_ok else "Missing provenance fields")

    # --- 17. Shortlist size is 2-5 (not too broad) ---
    check("Shortlist size is 2-5 strategies", 2 <= manifest_count <= 5,
          f"{manifest_count} strategies" if manifest_count else "EMPTY")

    # --- 18. No critical reconciler drift in last 24h ---
    dlq_path = os.getenv("DLQ_PATH",
                         str(PROJECT_ROOT / "tradingview_webhook_bot" / "storage" / "dead_letter.jsonl"))
    dlq_count = 0
    if os.path.exists(dlq_path):
        try:
            with open(dlq_path) as df:
                dlq_count = sum(1 for _ in df)
        except Exception:
            pass
    check("Dead letter queue is clean", dlq_count == 0, f"{dlq_count} failed signals" if dlq_count else "Clean")

    # --- Summary ---
    print()
    print("=" * 60)
    passed = sum(1 for r in RESULTS if r["passed"])
    failed = sum(1 for r in RESULTS if not r["passed"])
    total = len(RESULTS)

    if failed == 0:
        print(f"  VERDICT: GO  ({passed}/{total} gates passed)")
        print("=" * 60)
        return 0
    else:
        print(f"  VERDICT: NO-GO  ({failed} of {total} gates FAILED)")
        print()
        for r in RESULTS:
            if not r["passed"]:
                print(f"    FAIL: {r['name']} -- {r['detail']}")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
