import zipfile

import pytest

from data_lake.ingestion import archive_name, source_url, validate_zip


def test_source_url_is_reproducible():
    assert archive_name("btcusdt", "1m", "2024-01") == "BTCUSDT-1m-2024-01.zip"
    assert source_url("btcusdt", "1m", "2024-01").endswith("/BTCUSDT/1m/BTCUSDT-1m-2024-01.zip")


def test_validate_zip_accepts_one_csv(tmp_path):
    path = tmp_path / "sample.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("sample.csv", "1,2,3\n")
    assert validate_zip(path) == "sample.csv"


def test_validate_zip_rejects_ambiguous_archive(tmp_path):
    path = tmp_path / "sample.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("one.csv", "1\n")
        archive.writestr("two.csv", "2\n")
    with pytest.raises(ValueError, match="exactly one CSV"):
        validate_zip(path)
