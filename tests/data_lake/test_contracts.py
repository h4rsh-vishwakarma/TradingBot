from data_lake.contracts import validate_kline


def row(**overrides):
    base = {
        "open_time": "1704067200000",
        "open": "42000.0",
        "high": "42100.0",
        "low": "41900.0",
        "close": "42050.0",
        "volume": "12.4",
        "close_time": "1704067259999",
        "number_of_trades": "100",
    }
    return {**base, **overrides}


def test_valid_kline():
    assert validate_kline(row()).valid


def test_invalid_ohlc():
    result = validate_kline(row(high="42001"))
    assert not result.valid
    assert result.reason == "invalid_ohlc"


def test_invalid_types():
    assert validate_kline(row(volume="not-a-number")).reason == "schema_or_type_error"
