#!/usr/bin/env python3
# P2: Stamp all Pine scripts in strategies/ with // v1 2026-04-23 on line 1
# Skips files that already have a // vN comment. Going forward increment vN on every edit.
from pathlib import Path
import re

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATE_TAG     = "2026-04-23"
VERSION_RE   = re.compile(r"^//\s*v\d+", re.IGNORECASE)

stamped = skipped = errors = 0
for pine in sorted((PROJECT_ROOT / "strategies").rglob("*.pine")):
    try:
        text = pine.read_text(encoding="utf-8", errors="replace")
        first_line = text.split("\n")[0] if text else ""
        if VERSION_RE.match(first_line.strip()):
            skipped += 1
            continue
        pine.write_text(f"// v1 {DATE_TAG}\n" + text, encoding="utf-8")
        stamped += 1
        print(f"  STAMPED  {pine.relative_to(PROJECT_ROOT)}")
    except Exception as e:
        errors += 1
        print(f"  ERROR    {pine.name}: {e}")

print(f"\nDone: {stamped} stamped, {skipped} already versioned, {errors} errors.")
print("Rule: every Pine edit must increment // vN YYYY-MM-DD on line 1.")
