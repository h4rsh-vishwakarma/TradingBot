"""Dataset contracts shared by ingestion tests and the Glue job."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Mapping

KLINE_COLUMNS = (
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_asset_volume",
    "number_of_trades",
    "taker_buy_base_asset_volume",
    "taker_buy_quote_asset_volume",
    "ignore",
)


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    reason: str | None = None


def validate_kline(row: Mapping[str, str]) -> ValidationResult:
    """Perform lightweight row validation before distributed transformation."""
    try:
        open_time = int(row["open_time"])
        close_time = int(row["close_time"])
        prices = [Decimal(row[name]) for name in ("open", "high", "low", "close")]
        volume = Decimal(row["volume"])
        trades = int(row["number_of_trades"])
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return ValidationResult(False, "schema_or_type_error")

    open_price, high, low, close = prices
    if open_time < 0 or close_time < open_time:
        return ValidationResult(False, "invalid_timestamp_range")
    if min(prices) <= 0 or low > min(open_price, close) or high < max(open_price, close):
        return ValidationResult(False, "invalid_ohlc")
    if high < low or volume < 0 or trades < 0:
        return ValidationResult(False, "negative_or_inverted_metric")
    return ValidationResult(True)
