#!/usr/bin/env python3
"""Fix the Sainath audit table in DECISION_LANE_STATUS.md — restore stripped backtick content."""
from pathlib import Path

doc_path = Path(__file__).resolve().parents[1] / "docs" / "DECISION_LANE_STATUS.md"
text = doc_path.read_text(encoding="utf-8")

OLD_AUDIT_TABLE = """| Task | Owner | Status | Detail |
|------|-------|--------|--------|
| P-01 | Harsh | ✅ DONE | Server HEAD → = GitHub HEAD; manifest v30; heartbeat path confirmed |
| P-02 | Harsh | ✅ RESOLVED | signal_queue.db: 516 signals; 2 Donchian_40 BUY confirmed (2026-05-05 + 2026-05-06) |
| P-03 | Harsh | ✅ DONE | Heartbeat: NOT STARTED → **ACTIVE Day 0/30**. Root cause: ignored manifest . Fix: manifest fallback in  |
| P-04 | Harsh | ✅ DONE | Freeze diff resolved: 3 authorized changes documented + baseline refreshed.  |
| P-05 | Harsh | ✅ DONE | ETHUSDT SHORT (NOT DC40 — DC40 is LONG/BUY), BTCUSDT (quarantine stale), OPUSDT -2000 (unapproved). All zeroed in ledger. Open positions = 0 |
| P-06 | Harsh | ✅ DONE |  created. Day 0, 2 signals, 0 closed trades, IN_PROGRESS |
| P-07 | Harsh | ✅ DONE | Heartbeat System State block: Repo HEAD , Manifest v30, Signal DB path+size |
| P-08 | Garima | ✅ DONE | Pine audit completed |
| P-09 | Garima | ✅ DONE | TV alert for Donchian_40_ETHUSDT_4h created and live |
| P-10 | Garima | ✅ DONE | Signal flow verified |
| P-11 | Harsh | ✅ DONE | Multi-asset Donchian_40 sweep: BNBUSDT PASS (OOS PF=1.1440), XRPUSDT PASS (OOS PF=1.9047), SOLUSDT FAIL, BTCUSDT FAIL |
| P-12 | Harsh | ✅ DONE |  created — 8-step post-governance verification procedure |

**Commit:**  — """

NEW_AUDIT_TABLE = """| Task | Owner | Status | Detail |
|------|-------|--------|--------|
| P-01 | Harsh | ✅ DONE | Server HEAD `21225b3`→`02cb78c` = GitHub HEAD; manifest v30; heartbeat path confirmed |
| P-02 | Harsh | ✅ RESOLVED | signal_queue.db: 516 signals; 2 Donchian_40 BUY confirmed (2026-05-05 + 2026-05-06) |
| P-03 | Harsh | ✅ DONE | Heartbeat: NOT STARTED → **ACTIVE Day 0/30**. Root cause: ignored manifest `paper_window_status`. Fix: manifest fallback in `load_p07_nominees()` |
| P-04 | Harsh | ✅ DONE | Freeze diff resolved: 3 authorized changes documented + baseline refreshed. `execution diff = none` |
| P-05 | Harsh | ✅ DONE | ETHUSDT SHORT (NOT DC40 — DC40 is LONG/BUY), BTCUSDT (quarantine stale), OPUSDT -2000 (unapproved). All zeroed in ledger. Open positions = 0 |
| P-06 | Harsh | ✅ DONE | `storage/reports/donchian40_gate2_ledger.csv` created. Day 0, 2 signals, 0 closed trades, IN_PROGRESS |
| P-07 | Harsh | ✅ DONE | Heartbeat System State block: Repo HEAD `02cb78c`, Manifest v30, Signal DB path+size |
| P-08 | Garima | ✅ DONE | Pine audit completed |
| P-09 | Garima | ✅ DONE | TV alert for Donchian_40_ETHUSDT_4h created and live |
| P-10 | Garima | ✅ DONE | Signal flow verified |
| P-11 | Harsh | ✅ DONE | Multi-asset Donchian_40 sweep: BNBUSDT PASS (OOS PF=1.1440), XRPUSDT PASS (OOS PF=1.9047), SOLUSDT FAIL, BTCUSDT FAIL |
| P-12 | Harsh | ✅ DONE | `docs/DEPLOY_CHECKLIST.md` created — 8-step post-governance verification procedure |

**Commit:** `02cb78c` — `fix: P-03/P-04/P-05/P-06/P-07/P-12 — Sainath audit batch fixes`"""

if OLD_AUDIT_TABLE not in text:
    raise RuntimeError("Audit table target not found — check manually")

text = text.replace(OLD_AUDIT_TABLE, NEW_AUDIT_TABLE, 1)
doc_path.write_text(text, encoding="utf-8")
print("Audit table fixed OK")
