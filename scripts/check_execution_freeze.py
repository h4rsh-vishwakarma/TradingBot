#!/usr/bin/env python3
"""Execution-plane freeze checker for the current paper-validation window."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

UTC = timezone.utc
PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = PROJECT_ROOT / "storage" / "reports" / "paper_validation"
BASELINE_PATH = REPORT_DIR / "execution_freeze_baseline.json"
LATEST_PATH = REPORT_DIR / "execution_freeze_latest.json"
LOG_PATH = REPORT_DIR / "execution_freeze.log"

TRACKED_PATHS = [
    ("webhook_server", PROJECT_ROOT / "tradingview_webhook_bot" / "core" / "webhook_server.py"),
    ("orchestrator", PROJECT_ROOT / "tradingview_webhook_bot" / "core" / "orchestrator.py"),
    ("position_manager", PROJECT_ROOT / "tradingview_webhook_bot" / "core" / "position_manager.py"),
    ("risk_manager", PROJECT_ROOT / "tradingview_webhook_bot" / "core" / "risk_manager.py"),
    ("execution_engine", PROJECT_ROOT / "tradingview_webhook_bot" / "exchange" / "execution_engine.py"),
    ("reconciler", PROJECT_ROOT / "tradingview_webhook_bot" / "recon" / "reconciler.py"),
    ("approval_manifest", PROJECT_ROOT / "config" / "approved_strategies.json"),
    ("env_vars", Path("/etc/tradingbot/env_vars")),
    ("webhook_service", Path("/etc/systemd/system/tradingbot-webhook.service")),
    ("orchestrator_service", Path("/etc/systemd/system/tradingbot-orchestrator.service")),
    ("telegram_service", Path("/etc/systemd/system/tradingbot-telegram.service")),
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def capture_snapshot() -> dict:
    recorded_at = datetime.now(UTC).replace(microsecond=0)
    entries = []
    for label, path in TRACKED_PATHS:
        resolved = path.resolve() if path.exists() else path
        entry = {
            "label": label,
            "path": str(resolved),
            "exists": path.exists(),
            "sha256": None,
            "size": 0,
        }
        if path.exists():
            entry["sha256"] = sha256_file(path)
            entry["size"] = path.stat().st_size
        entries.append(entry)
    return {
        "recorded_at": recorded_at.isoformat(),
        "tracked_count": len(entries),
        "tracked_entries": entries,
    }


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def compare_snapshots(baseline: dict, current: dict) -> list[str]:
    baseline_map = {entry["path"]: entry for entry in baseline.get("tracked_entries", [])}
    current_map = {entry["path"]: entry for entry in current.get("tracked_entries", [])}
    changed: list[str] = []

    for path, current_entry in current_map.items():
        baseline_entry = baseline_map.get(path)
        if baseline_entry is None:
            changed.append(f"added:{current_entry['label']}")
            continue
        if (
            baseline_entry.get("exists") != current_entry.get("exists")
            or baseline_entry.get("sha256") != current_entry.get("sha256")
        ):
            changed.append(current_entry["label"])

    for path, baseline_entry in baseline_map.items():
        if path not in current_map:
            changed.append(f"removed:{baseline_entry['label']}")

    return sorted(set(changed))


def main() -> int:
    parser = argparse.ArgumentParser(description="Check execution-plane freeze integrity.")
    parser.add_argument(
        "--refresh-baseline",
        action="store_true",
        help="Replace the stored freeze baseline with the current snapshot.",
    )
    args = parser.parse_args()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    current = capture_snapshot()

    baseline_note = ""
    if args.refresh_baseline or not BASELINE_PATH.exists():
        write_json(BASELINE_PATH, current)
        baseline = current
        baseline_note = "baseline refreshed" if args.refresh_baseline else "baseline initialized"
    else:
        baseline = load_json(BASELINE_PATH)

    changed = compare_snapshots(baseline, current)
    status = "none" if not changed else "detected"

    latest_payload = {
        "recorded_at": current["recorded_at"],
        "status": status,
        "tracked_count": current["tracked_count"],
        "changed": changed,
        "note": baseline_note,
        "baseline_path": str(BASELINE_PATH),
        "tracked_entries": current["tracked_entries"],
    }
    write_json(LATEST_PATH, latest_payload)

    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    line = f"{timestamp} execution diff = {status} | tracked={current['tracked_count']}"
    if changed:
        line += " | changed=" + ", ".join(changed)
    elif baseline_note:
        line += f" | note={baseline_note}"

    with open(LOG_PATH, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")

    print(line)
    return 0 if not changed else 1


if __name__ == "__main__":
    raise SystemExit(main())
