import json

from data_lake.manifest import ManifestEntry, append_once, make_run_id, sha256_file


def test_checksum_and_run_id_are_deterministic(tmp_path):
    source = tmp_path / "input.csv"
    source.write_bytes(b"same-data")
    checksum = sha256_file(source)
    assert checksum == sha256_file(source)
    assert make_run_id("raw/input.csv", checksum) == make_run_id("raw/input.csv", checksum)


def test_manifest_is_idempotent(tmp_path):
    source = tmp_path / "input.csv"
    source.write_text("row", encoding="utf-8")
    manifest = tmp_path / "manifest.jsonl"
    entry = ManifestEntry.create("raw/input.csv", source)
    assert append_once(manifest, entry)
    assert not append_once(manifest, entry)
    assert len([json.loads(line) for line in manifest.read_text().splitlines()]) == 1
