#!/usr/bin/env python3
"""Fail CI when Git-tracked files contain common credential material.

Only finding type and location are printed. Secret values are never printed.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

MAX_FILE_BYTES = 5 * 1024 * 1024
PLACEHOLDERS = (
    "changeme",
    "change-me",
    "dummy",
    "example",
    "placeholder",
    "replace",
    "test_key",
    "test_secret",
    "your_",
)

PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b"),
    "OpenAI key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
}

ASSIGNMENT = re.compile(
    r"(?im)^\s*(?:export\s+)?"
    r"(?:AWS_SECRET_ACCESS_KEY|BINANCE_API_SECRET|TELEGRAM_TOKEN|WEBHOOK_SECRET|"
    r"PRIVATE_KEY|CLIENT_SECRET|API_SECRET)\s*[=:]\s*[\"']?([^\s\"'#]+)"
)


def tracked_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [root / item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def is_placeholder(value: str) -> bool:
    normalized = value.lower()
    return len(value) < 8 or any(marker in normalized for marker in PLACEHOLDERS)


def should_scan_assignments(path: Path) -> bool:
    name = path.name.lower()
    if name.endswith((".example", ".template")):
        return False
    return name.startswith(".env") or path.suffix.lower() in {
        ".ini",
        ".json",
        ".toml",
        ".yaml",
        ".yml",
    }


def scan_file(path: Path) -> list[tuple[int, str]]:
    try:
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            return []
        data = path.read_bytes()
    except OSError:
        return []
    if b"\0" in data[:8192]:
        return []
    text = data.decode("utf-8", errors="replace")
    findings: list[tuple[int, str]] = []
    for label, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            findings.append((text.count("\n", 0, match.start()) + 1, label))
    if should_scan_assignments(path):
        for match in ASSIGNMENT.finditer(text):
            if not is_placeholder(match.group(1)):
                findings.append((text.count("\n", 0, match.start()) + 1, "hardcoded secret"))
    return findings


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    findings: list[tuple[Path, int, str]] = []
    for path in tracked_files(root):
        for line, label in scan_file(path):
            findings.append((path.relative_to(root), line, label))
    if findings:
        print("Secret scan failed. Values are intentionally redacted:", file=sys.stderr)
        for path, line, label in findings:
            print(f"- {path}:{line}: {label}", file=sys.stderr)
        print("Remove the secret, rotate it, and purge it from Git history.", file=sys.stderr)
        return 1
    print(f"Secret scan passed ({len(tracked_files(root))} tracked files checked).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
