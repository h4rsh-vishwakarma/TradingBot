from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd


AUTO_TRADE_MIN_DAILY_ROI = 0.5
AUTO_TRADE_MAX_NET_DD = 30.0


@dataclass(frozen=True)
class TournamentClassification:
    tier: str
    auto_trade_eligible: bool
    auto_trade_reason: str


def _to_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        if isinstance(value, str):
            cleaned = value.strip().replace("%", "")
            if not cleaned:
                return default
            return float(cleaned)
        return float(value)
    except (TypeError, ValueError):
        return default


def _format_pct(value: float) -> str:
    return f"{value:.3f}%"


def classify_tournament_entry(
    daily_roi: float,
    gross_dd: float,
    net_dd: float,
    win_rate: float = 0.0,
    sharpe: float = 0.0,
) -> TournamentClassification:
    abs_net_dd = abs(net_dd)
    abs_gross_dd = abs(gross_dd)
    auto_trade_eligible = daily_roi >= AUTO_TRADE_MIN_DAILY_ROI and abs_net_dd <= AUTO_TRADE_MAX_NET_DD

    reasons = []
    if daily_roi < AUTO_TRADE_MIN_DAILY_ROI:
        reasons.append(
            f"ROI {_format_pct(daily_roi)} below minimum {_format_pct(AUTO_TRADE_MIN_DAILY_ROI)}"
        )
    if abs_net_dd > AUTO_TRADE_MAX_NET_DD:
        reasons.append(f"Net DD {abs_net_dd:.2f}% above limit {AUTO_TRADE_MAX_NET_DD:.0f}%")

    if auto_trade_eligible:
        if daily_roi >= 1.0 and sharpe >= 3.0 and win_rate >= 40 and abs_gross_dd <= 25:
            tier = "🚀 ALPHA++"
        else:
            tier = "🎯 ALPHA"
        reason = (
            f"Auto-trade eligible: ROI {_format_pct(daily_roi)} and Net DD {abs_net_dd:.2f}% "
            f"within {AUTO_TRADE_MAX_NET_DD:.0f}%"
        )
        return TournamentClassification(tier=tier, auto_trade_eligible=True, auto_trade_reason=reason)

    if daily_roi <= 0:
        tier = "💀 REJECT"
    elif daily_roi >= 0.1 or abs_net_dd <= 45:
        tier = "⚖️ AVERAGE"
    else:
        tier = "💀 REJECT"

    reason = "; ".join(reasons) if reasons else "Not eligible for auto-trade"
    return TournamentClassification(tier=tier, auto_trade_eligible=False, auto_trade_reason=reason)


def apply_tournament_rules(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        result = df.copy()
        if "Tier" not in result.columns:
            result["Tier"] = pd.Series(dtype="object")
        if "Auto_Trade_Eligible" not in result.columns:
            result["Auto_Trade_Eligible"] = pd.Series(dtype="object")
        if "Auto_Trade_Reason" not in result.columns:
            result["Auto_Trade_Reason"] = pd.Series(dtype="object")
        return result

    result = df.copy()
    tiers = []
    eligibility = []
    reasons = []

    for _, row in result.iterrows():
        daily_roi = _to_float(row.get("Daily_ROI_%", row.get("Daily_ROI", 0.0)))
        gross_dd = _to_float(row.get("Gross_DD_%", row.get("Max_DD_%", 0.0)))
        net_dd = _to_float(row.get("Net_DD_%", gross_dd))
        win_rate = _to_float(row.get("Win_Rate_%", 0.0))
        sharpe = _to_float(row.get("Sharpe_Ratio", 0.0))

        classification = classify_tournament_entry(
            daily_roi=daily_roi,
            gross_dd=gross_dd,
            net_dd=net_dd,
            win_rate=win_rate,
            sharpe=sharpe,
        )
        tiers.append(classification.tier)
        eligibility.append("YES" if classification.auto_trade_eligible else "NO")
        reasons.append(classification.auto_trade_reason)

    result["Tier"] = tiers
    result["Auto_Trade_Eligible"] = eligibility
    result["Auto_Trade_Reason"] = reasons
    return result


def parse_auto_trade_flag(value, default: Optional[bool] = None) -> Optional[bool]:
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"yes", "true", "1", "y"}:
        return True
    if text in {"no", "false", "0", "n"}:
        return False
    return default


def filter_auto_trade_eligible(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    if "Auto_Trade_Eligible" in df.columns:
        mask = df["Auto_Trade_Eligible"].apply(lambda v: parse_auto_trade_flag(v, False) is True)
        return df[mask].copy()
    return df[df["Tier"].astype(str).str.contains("ALPHA", na=False)].copy()


def _strategy_key(row: pd.Series) -> str:
    return f"{str(row.get('Symbol', '')).upper()}::{str(row.get('Strategy', '')).strip()}"


def build_tournament_change_message(
    previous_df: Optional[pd.DataFrame],
    current_df: pd.DataFrame,
    source_label: str,
    max_lines: int = 20,
) -> Optional[str]:
    current_df = apply_tournament_rules(current_df)
    previous_df = apply_tournament_rules(previous_df) if previous_df is not None else pd.DataFrame()

    if previous_df.empty and current_df.empty:
        return None

    prev_map = {_strategy_key(row): row for _, row in previous_df.iterrows()}
    curr_map = {_strategy_key(row): row for _, row in current_df.iterrows()}
    changes = []

    for key in sorted(set(prev_map) | set(curr_map)):
        old = prev_map.get(key)
        new = curr_map.get(key)

        if old is None and new is not None:
            if parse_auto_trade_flag(new.get("Auto_Trade_Eligible"), False):
                changes.append(
                    "🆕 ENABLED | "
                    f"{new['Symbol']} | {new['Strategy']} | ROI {_format_pct(_to_float(new.get('Daily_ROI_%')))} "
                    f"| NDD {abs(_to_float(new.get('Net_DD_%'))):.2f}% | {new.get('Tier', 'N/A')}"
                )
            continue

        if new is None and old is not None:
            if parse_auto_trade_flag(old.get("Auto_Trade_Eligible"), False):
                changes.append(
                    "🗑️ REMOVED | "
                    f"{old['Symbol']} | {old['Strategy']} | was {old.get('Tier', 'N/A')}"
                )
            continue

        old_tier = str(old.get("Tier", ""))
        new_tier = str(new.get("Tier", ""))
        old_flag = parse_auto_trade_flag(old.get("Auto_Trade_Eligible"), False)
        new_flag = parse_auto_trade_flag(new.get("Auto_Trade_Eligible"), False)

        if old_tier == new_tier and old_flag == new_flag:
            continue

        changes.append(
            "🔁 UPDATE | "
            f"{new['Symbol']} | {new['Strategy']} | "
            f"{old_tier or 'N/A'} -> {new_tier or 'N/A'} | "
            f"auto {('YES' if old_flag else 'NO')} -> {('YES' if new_flag else 'NO')} | "
            f"ROI {_format_pct(_to_float(old.get('Daily_ROI_%')))} -> {_format_pct(_to_float(new.get('Daily_ROI_%')))} | "
            f"NDD {abs(_to_float(old.get('Net_DD_%'))):.2f}% -> {abs(_to_float(new.get('Net_DD_%'))):.2f}%"
        )

    if not changes:
        return None

    eligible_now = len(filter_auto_trade_eligible(current_df))
    hidden = max(0, len(changes) - max_lines)
    visible_changes = changes[:max_lines]
    lines = [
        f"<b>{source_label}</b>",
        (
            f"Rules: ROI &gt;= {_format_pct(AUTO_TRADE_MIN_DAILY_ROI)} "
            f"| Net DD &lt;= {AUTO_TRADE_MAX_NET_DD:.0f}%"
        ),
        f"Auto-trade eligible now: <b>{eligible_now}</b>",
        "",
        *visible_changes,
    ]
    if hidden:
        lines.extend(["", f"...and {hidden} more change(s)."])

    return "\n".join(lines)
