"""P-08: Apply manifest v21 changes locally.

Changes:
  - CCI Trend: R04_PASS → R01_RETIRED (TV rerun PF=1.08, below practical gate)
  - Donchian Trend: R04_PASS → R01_RETIRED (TV rerun PF=0.93 < 1.0)
  - G83 DeMarker Donchian: ALPHA → P07_NOMINEE, locked to ETHUSDT, OOS PF=1.18 n=217
  - G88 Vortex Donchian: paper_only → P07_NOMINEE, locked to XRPUSDT, OOS PF=1.10 n=325
  - G111 Supertrend Donchian: NEW entry, P07_NOMINEE, SUIUSDT, OOS PF=1.55 n=75
  - version: 20 → 21
"""

import json
import sys
from pathlib import Path

MANIFEST_PATH = Path(__file__).resolve().parents[1] / "config" / "approved_strategies.json"

with open(MANIFEST_PATH) as f:
    manifest = json.load(f)

updated = {}

for entry in manifest["approvals"]:
    name = entry["strategy"]

    if name == "CCI Trend":
        entry["label"] = "R01_RETIRED"
        entry["shortlist_priority"] = False
        entry["r01_tv_rerun_pf"] = 1.08
        entry["r01_retired_at"] = "2026-05-01T07:30:00Z"
        entry["class_reason"] = (
            "R01_RETIRED 2026-05-01: TV rerun with corrected 4% trail yields PF=1.08 — "
            "below practical Gate 1 threshold. Large TV/Python gap (PF 3.998 Python vs 1.08 TV) "
            "indicates strategy behavior diverges from OOS assumptions. Retired per Garima R-01 decision."
        )
        entry["notes"] = entry.get("notes", "") + (
            " | R-01 2026-05-01: TV rerun at corrected 4% trail: PF=1.08. Python/TV gap too large "
            "(7x). Retired. Cannot be shortlisted for capital."
        )
        updated["CCI Trend"] = "R01_RETIRED"

    elif name == "Donchian Trend":
        entry["label"] = "R01_RETIRED"
        entry["shortlist_priority"] = False
        entry["r01_tv_rerun_pf"] = 0.93
        entry["r01_retired_at"] = "2026-05-01T07:30:00Z"
        entry["class_reason"] = (
            "R01_RETIRED 2026-05-01: TV rerun with corrected 4% trail yields PF=0.93 — below 1.0, "
            "hard fail. Large TV/Python gap (PF 7.175 Python vs 0.93 TV). Retired per Garima R-01 decision."
        )
        entry["notes"] = entry.get("notes", "") + (
            " | R-01 2026-05-01: TV rerun at corrected 4% trail: PF=0.93 (<1.0, hard fail). "
            "Python/TV gap enormous (7.7x). Retired."
        )
        updated["Donchian Trend"] = "R01_RETIRED"

    elif name == "G83 DeMarker Donchian":
        entry["label"] = "P07_NOMINEE"
        entry["symbols"] = ["ETHUSDT"]
        entry["shortlist_priority"] = True
        entry["p07_oos_pf"] = 1.18
        entry["p07_oos_n"] = 217
        entry["p07_nominated_at"] = "2026-05-01T07:30:00Z"
        entry["backtest_hash"] = "p07_oos_g83_demarker_donchian_ETHUSDT_4h_20260501"
        entry["class_reason"] = (
            "P07_NOMINEE 2026-05-01: Python OOS PF=1.18 n=217 on ETHUSDT 4H. "
            "Gate 1 candidate. Paper window to start after P-09 TV alerts deployed. "
            "Symbol locked to ETHUSDT (XRPUSDT dropped — OOS data not validated this run)."
        )
        entry["notes"] = entry.get("notes", "") + (
            " | P-07 2026-05-01: Selected as paper window nominee. OOS PF=1.18, n=217, ETHUSDT 4H. "
            "Awaiting TV alert creation (P-09) to start paper window."
        )
        updated["G83 DeMarker Donchian"] = "P07_NOMINEE/ETHUSDT"

    elif name == "G88 Vortex Donchian":
        entry["label"] = "P07_NOMINEE"
        entry["symbols"] = ["XRPUSDT"]
        entry["shortlist_priority"] = True
        entry["p07_oos_pf"] = 1.10
        entry["p07_oos_n"] = 325
        entry["p07_nominated_at"] = "2026-05-01T07:30:00Z"
        entry["backtest_hash"] = "p07_oos_g88_vortex_donchian_XRPUSDT_4h_20260501"
        entry["class_reason"] = (
            "P07_NOMINEE 2026-05-01: Python OOS PF=1.10 n=325 on XRPUSDT 4H. "
            "Gate 1 candidate. Paper window to start after P-09 TV alerts deployed. "
            "Symbol locked to XRPUSDT."
        )
        entry["notes"] = entry.get("notes", "") + (
            " | P-07 2026-05-01: Selected as paper window nominee. OOS PF=1.10, n=325, XRPUSDT 4H. "
            "Awaiting TV alert creation (P-09) to start paper window."
        )
        updated["G88 Vortex Donchian"] = "P07_NOMINEE/XRPUSDT"

# Add G111 Supertrend Donchian (new entry)
g111 = {
    "strategy": "G111 Supertrend Donchian",
    "exchange": "binance",
    "symbols": ["SUIUSDT"],
    "timeframes": ["240"],
    "operator": "garima",
    "approved_at": "2026-05-01T07:30:00Z",
    "backtest_hash": "p07_oos_g111_supertrend_donchian_SUIUSDT_4h_20260501",
    "label": "P07_NOMINEE",
    "notes": (
        "P-07 2026-05-01: Python OOS PF=1.55, n=75, SUIUSDT 4H. "
        "Supertrend signal + Donchian channel filter. Selected as P-07 paper window nominee. "
        "Awaiting TV alert creation (P-09) to start paper window."
    ),
    "approval_class": "paper_only",
    "class_reason": (
        "P07_NOMINEE 2026-05-01: Python OOS PF=1.55 n=75 on SUIUSDT 4H. "
        "Gate 1 candidate. Paper window to start after P-09 TV alerts deployed."
    ),
    "shortlist_priority": True,
    "p07_oos_pf": 1.55,
    "p07_oos_n": 75,
    "p07_nominated_at": "2026-05-01T07:30:00Z"
}
manifest["approvals"].append(g111)
updated["G111 Supertrend Donchian"] = "P07_NOMINEE/SUIUSDT (NEW)"

manifest["version"] = 21
manifest["updated_at"] = "2026-05-01T07:30:00Z"

with open(MANIFEST_PATH, "w") as f:
    json.dump(manifest, f, indent=2)

print("Manifest v21 written.")
for k, v in updated.items():
    print(f"  {k}: {v}")
print(f"  G111 Supertrend Donchian: added")
