import csv
import re
import shutil
import subprocess
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
JOURNALCTL_BIN = shutil.which("journalctl") or "/usr/bin/journalctl"
AUDIT_LOG_FILE = PROJECT_ROOT / "trading_audit_12h.csv"
RAW_LOG_FILE = PROJECT_ROOT / "orchestrator_logs_12h.csv"
UNIT_NAME = "trading_orchestrator"


def _classify_event(message: str) -> str:
    message_lower = message.lower()
    if "order success" in message_lower or "trade success" in message_lower:
        return "TRADE_SUCCESS"
    if "signal received" in message_lower:
        return "SIGNAL_IN"
    if "safety gate block" in message_lower or "hybrid risk block" in message_lower:
        return "RISK_BLOCK"
    if "heartbeat" in message_lower:
        return "HEARTBEAT"
    if "error" in message_lower or "exception" in message_lower:
        return "ERROR"
    return "GENERAL"


def _load_journal(unit_name: str = UNIT_NAME, since: str = "12 hours ago") -> list[str]:
    result = subprocess.run(
        [JOURNALCTL_BIN, "-u", unit_name, "--since", since, "--no-pager", "--no-hostname", "-o", "short-iso"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.strip() or f"journalctl exited with {result.returncode}")
    return [line for line in result.stdout.splitlines() if line.strip()]


def export_to_csv():
    logs = _load_journal()

    audit_rows = []
    raw_rows = []
    for line in logs:
        parts = re.split(r"\s+", line, maxsplit=2)
        timestamp = parts[0].strip() if parts else ""
        message = parts[2].strip() if len(parts) >= 3 else line.strip()
        event_type = _classify_event(message)

        raw_rows.append([timestamp, UNIT_NAME, message])
        if event_type != "HEARTBEAT":
            audit_rows.append([timestamp, event_type, message])

    for output_path, rows in ((AUDIT_LOG_FILE, audit_rows), (RAW_LOG_FILE, raw_rows)):
        with output_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Timestamp", "Event", "Details"])
            writer.writerows(rows)

    df = pd.DataFrame(audit_rows, columns=["Timestamp", "Event", "Details"])
    summary = {
        "total_signals": len(df[df["Event"] == "SIGNAL_IN"]),
        "trades": len(df[df["Event"] == "TRADE_SUCCESS"]),
        "blocks": len(df[df["Event"] == "RISK_BLOCK"]),
        "errors": len(df[df["Event"] == "ERROR"]),
        "rows": len(df),
    }
    return summary, str(AUDIT_LOG_FILE)


if __name__ == "__main__":
    summary, log_file = export_to_csv()
    print(f"Exported {summary['rows']} audit rows to {log_file}")
