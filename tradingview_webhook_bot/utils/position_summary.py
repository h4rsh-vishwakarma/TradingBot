from datetime import datetime
from html import escape
from typing import Any, Callable, Mapping, Optional


def _read_field(record: Any, field: str, default: Any = None) -> Any:
    if isinstance(record, dict):
        return record.get(field, default)
    return getattr(record, field, default)


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _format_money(value: Optional[float], decimals: int = 2, na_value: str = "n/a") -> str:
    if value is None:
        return na_value
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.{decimals}f}"


def parse_position_key(position_key: str) -> dict[str, str]:
    raw_key = str(position_key or "").strip()
    parts = raw_key.split(":")

    if len(parts) >= 3:
        exchange = parts[0]
        asset = parts[1]
        strategy = ":".join(parts[2:]) or "Aggregate"
    elif len(parts) == 2:
        exchange = parts[0]
        asset = parts[1]
        strategy = "Aggregate"
    else:
        exchange = "ledger"
        asset = raw_key
        strategy = "Aggregate"

    return {
        "exchange": exchange or "ledger",
        "asset": asset or raw_key or "UNKNOWN",
        "strategy": strategy or "Aggregate",
    }


def build_position_snapshot(
    positions: Mapping[str, Any],
    price_lookup: Optional[Callable[..., Optional[float]]] = None,
    today: Optional[str] = None,
) -> dict[str, Any]:
    today_str = today or datetime.utcnow().strftime("%Y-%m-%d")
    rows: list[dict[str, Any]] = []

    for key, record in (positions or {}).items():
        qty = _safe_float(_read_field(record, "quantity", 0.0), 0.0) or 0.0
        avg_price = _safe_float(_read_field(record, "avg_price", 0.0), 0.0) or 0.0
        if abs(qty) <= 1e-10 or avg_price <= 0:
            continue

        meta = parse_position_key(str(key))
        mark_price = None
        if price_lookup:
            try:
                mark_price = _safe_float(price_lookup(meta["exchange"], meta["asset"]))
            except TypeError:
                mark_price = _safe_float(price_lookup(meta["asset"]))

        day_pnl = _safe_float(_read_field(record, "daily_realized_pnl", 0.0), 0.0) or 0.0
        if str(_read_field(record, "last_update_date", "")) != today_str:
            day_pnl = 0.0

        unrealized_pnl = None
        if mark_price and mark_price > 0:
            unrealized_pnl = (mark_price - avg_price) * qty

        rows.append({
            "position_key": str(key),
            "exchange": meta["exchange"],
            "asset": meta["asset"],
            "strategy": meta["strategy"],
            "side": "LONG" if qty > 0 else "SHORT",
            "quantity": qty,
            "avg_price": avg_price,
            "mark_price": mark_price,
            "unrealized_pnl": unrealized_pnl,
            "day_pnl": day_pnl,
        })

    rows.sort(key=lambda row: (row["exchange"], row["asset"], row["strategy"]))

    total_unrealized = sum((row["unrealized_pnl"] or 0.0) for row in rows)
    total_day_pnl = sum(row["day_pnl"] for row in rows)
    return {
        "positions_open": len(rows),
        "total_unrealized_pnl": total_unrealized,
        "total_day_pnl": total_day_pnl,
        "rows": rows,
    }


def format_positions_for_telegram(snapshot: Mapping[str, Any], limit: int = 3) -> str:
    open_count = int(snapshot.get("positions_open", 0) or 0)
    if open_count == 0:
        return (
            "📂 <b>Positions Open:</b> <code>0</code>\n"
            "💸 <b>Unrealized PnL:</b> <code>$0.00</code>\n"
            "📅 <b>Day's PnL:</b> <code>$0.00</code>"
        )

    rows = list(snapshot.get("rows", []))
    lines = [
        f"📂 <b>Positions Open:</b> <code>{open_count}</code>",
        f"💸 <b>Unrealized PnL:</b> <code>{_format_money(snapshot.get('total_unrealized_pnl', 0.0))}</code>",
        f"📅 <b>Day's PnL:</b> <code>{_format_money(snapshot.get('total_day_pnl', 0.0))}</code>",
    ]

    for row in rows[:limit]:
        lines.append(
            "• "
            f"<b>Asset:</b> <code>{escape(str(row['asset']))}</code> | "
            f"<b>Strategy:</b> <code>{escape(str(row['strategy']))}</code> | "
            f"<b>Unrealized PnL:</b> <code>{_format_money(row.get('unrealized_pnl'))}</code> | "
            f"<b>Day's PnL:</b> <code>{_format_money(row.get('day_pnl', 0.0))}</code>"
        )

    remaining = open_count - min(open_count, limit)
    if remaining > 0:
        lines.append(f"<i>+{remaining} more open position(s)</i>")

    return "\n".join(lines)


def format_positions_for_log(snapshot: Mapping[str, Any], limit: int = 5) -> str:
    open_count = int(snapshot.get("positions_open", 0) or 0)
    summary = (
        f"positions_open={open_count} | "
        f"unrealized_pnl={_format_money(snapshot.get('total_unrealized_pnl', 0.0))} | "
        f"day_pnl={_format_money(snapshot.get('total_day_pnl', 0.0))}"
    )
    if open_count == 0:
        return summary

    rows = list(snapshot.get("rows", []))
    details = "; ".join(
        (
            f"asset={row['asset']} "
            f"strategy={row['strategy']} "
            f"unrealized_pnl={_format_money(row.get('unrealized_pnl'))} "
            f"day_pnl={_format_money(row.get('day_pnl', 0.0))}"
        )
        for row in rows[:limit]
    )
    remaining = open_count - min(open_count, limit)
    if remaining > 0:
        details = f"{details}; +{remaining} more"
    return f"{summary} | {details}"
