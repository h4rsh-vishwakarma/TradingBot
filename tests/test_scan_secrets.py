from scripts.scan_secrets import is_placeholder, scan_file


def test_detects_private_key_without_echoing_value(tmp_path):
    candidate = tmp_path / "exposed.pem"
    candidate.write_text(
        "-----BEGIN " + "PRIVATE KEY-----\nredacted-test-material\n-----END PRIVATE KEY-----\n",
        encoding="utf-8",
    )
    assert scan_file(candidate) == [(1, "private key")]


def test_detects_hardcoded_secret_assignment(tmp_path):
    candidate = tmp_path / "settings.env"
    candidate.write_text("BINANCE_API_SECRET=realisticSecretValue123\n", encoding="utf-8")
    assert scan_file(candidate) == [(1, "hardcoded secret")]


def test_allows_documented_placeholders(tmp_path):
    candidate = tmp_path / ".env.example"
    candidate.write_text("BINANCE_API_SECRET=your_secret_here\n", encoding="utf-8")
    assert scan_file(candidate) == []
    assert is_placeholder("ci_test_secret_placeholder")
