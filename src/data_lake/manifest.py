"""Append-only run manifest with deterministic idempotency keys."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_run_id(source_key: str, checksum: str) -> str:
    return hashlib.sha256(f"{source_key}\0{checksum}".encode()).hexdigest()[:20]


@dataclass(frozen=True)
class ManifestEntry:
    run_id: str
    source_key: str
    checksum_sha256: str
    size_bytes: int
    status: str
    recorded_at: str

    @classmethod
    def create(cls, source_key: str, path: Path, status: str = "INGESTED") -> "ManifestEntry":
        checksum = sha256_file(path)
        return cls(
            run_id=make_run_id(source_key, checksum),
            source_key=source_key,
            checksum_sha256=checksum,
            size_bytes=path.stat().st_size,
            status=status,
            recorded_at=datetime.now(timezone.utc).isoformat(),
        )


def read_manifest(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def append_once(path: Path, entry: ManifestEntry, existing: Iterable[dict] | None = None) -> bool:
    records = list(existing) if existing is not None else read_manifest(path)
    if any(record.get("run_id") == entry.run_id for record in records):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(asdict(entry), sort_keys=True) + "\n")
    return True
