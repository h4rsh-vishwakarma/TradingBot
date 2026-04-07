from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd
import requests

from tradingview_webhook_bot.alerts.telegram_alerts import AlertSeverity, TelegramAlert


COLUMN_MAP = {
    "Net P&L USD": "pnl",
    "Net P&L USDT": "pnl",
    "Profit USD": "pnl",
    "Profit": "pnl",
    "Date and time": "time",
    "Time": "time",
    "Type": "type",
    "Net P&L %": "pnl_pct",
    "Profit %": "pnl_pct",
    "Avg Trade %": "avg_t_pct",
}

TIMEFRAME_PATTERN = re.compile(r"(?P<timeframe>\d+[mhdwHDW])")
BACKTEST_FILENAME_PATTERN = re.compile(
    r"^(?P<strategy>.+)_(?P<timeframe>\d+[mhdwHDW])_BINANCE_(?P<symbol>[A-Z0-9]+)_(?P<stamp>\d{4}-\d{2}-\d{2})$"
)

SIGNAL_VARIABLE_PAIRS = [
    ("longCond", "shortCond"),
    ("long_cond", "short_cond"),
    ("buySignal", "sellSignal"),
    ("buy_signal", "sell_signal"),
    ("longSignal", "shortSignal"),
    ("long_signal", "short_signal"),
]


@dataclass(frozen=True)
class AlphaCriteria:
    min_roi_per_day_pct: float = 1.0
    max_gross_drawdown_pct: float = 20.0
    max_net_drawdown_pct: float = 20.0


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        if isinstance(value, str):
            return float(value.strip().replace("%", ""))
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_name(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text).lower())


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", str(text).strip())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or "strategy"


def _extract_metadata(file_name: str) -> tuple[str, str, str]:
    clean_name = Path(file_name).stem
    match = BACKTEST_FILENAME_PATTERN.match(clean_name)
    if match:
        strategy = match.group("strategy").replace("_", " ")
        return strategy, match.group("symbol").upper(), match.group("timeframe").lower()

    name_parts = clean_name.split("_")
    symbol = "UNKNOWN"
    timeframe = next((part.lower() for part in name_parts if TIMEFRAME_PATTERN.fullmatch(part)), "1h")

    for part in reversed(name_parts):
        part_up = part.upper()
        if part_up.endswith("USDT") or part_up.endswith("USD"):
            symbol = part_up
            break

    strategy_parts = [part for part in name_parts if part.upper() != symbol and part.lower() != timeframe]
    strategy = " ".join(strategy_parts).strip() or clean_name
    return strategy, symbol, timeframe


def _normalize_trade_frame(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.rename(columns=lambda col: COLUMN_MAP.get(str(col).strip(), str(col).strip())).copy()
    if "pnl" not in normalized.columns:
        raise ValueError("no pnl column found")
    if "time" not in normalized.columns:
        raise ValueError("no time column found")

    normalized["pnl"] = pd.to_numeric(normalized["pnl"], errors="coerce").fillna(0.0)
    normalized["time"] = pd.to_datetime(normalized["time"], errors="coerce")
    normalized = normalized.dropna(subset=["time"])

    if "type" in normalized.columns:
        normalized["type"] = normalized["type"].astype(str)
    else:
        normalized["type"] = ""

    if "pnl_pct" in normalized.columns:
        normalized["pnl_pct"] = pd.to_numeric(normalized["pnl_pct"], errors="coerce")

    return normalized


def _calculate_sharpe_ratio(df: pd.DataFrame, trades: pd.DataFrame, initial_capital: float, days_diff: int) -> float:
    trades_sorted = trades.sort_values("time")
    daily_pnl = trades_sorted.groupby(trades_sorted["time"].dt.date)["pnl"].sum()

    if len(daily_pnl) == 0 or days_diff <= 30:
        return 0.0

    all_dates = pd.date_range(start=df["time"].min(), end=df["time"].max(), freq="D")
    daily_returns = pd.Series(0.0, index=all_dates.date, dtype=float)
    for date, pnl_value in daily_pnl.items():
        if date in daily_returns.index:
            daily_returns.at[date] = pnl_value / initial_capital

    std_dev = daily_returns.std()
    if std_dev <= 0:
        return 0.0
    return float((daily_returns.mean() / std_dev) * np.sqrt(252))


def _calculate_drawdowns(trades: pd.DataFrame, initial_capital: float, gross_loss: float) -> dict[str, float]:
    trades_sorted = trades.sort_values("time")
    cumulative_pnl = trades_sorted["pnl"].cumsum()
    equity_curve = initial_capital + cumulative_pnl
    running_max = equity_curve.cummax()
    drawdown = equity_curve - running_max

    max_drawdown_usd = float(drawdown.min()) if len(drawdown) > 0 else 0.0
    if len(drawdown) > 0 and max_drawdown_usd < 0:
        peak_at_worst = float(running_max.loc[drawdown.idxmin()])
        max_drawdown_pct = (max_drawdown_usd / peak_at_worst) * 100 if peak_at_worst > 0 else 0.0
    else:
        max_drawdown_pct = 0.0

    if len(drawdown) > 0:
        current_drawdown_usd = float(drawdown.iloc[-1])
        current_peak = float(running_max.iloc[-1])
        current_drawdown_pct = (current_drawdown_usd / current_peak) * 100 if current_peak > 0 else 0.0
    else:
        current_drawdown_usd = 0.0
        current_drawdown_pct = 0.0

    gross_drawdown_usd = -float(gross_loss)
    peak_equity = float(running_max.max()) if len(running_max) > 0 else initial_capital
    gross_drawdown_pct = (gross_drawdown_usd / max(peak_equity, initial_capital)) * 100 if peak_equity > 0 else 0.0

    min_equity = float(equity_curve.min()) if len(equity_curve) > 0 else initial_capital
    if min_equity < initial_capital:
        net_drawdown_usd = min_equity - initial_capital
        net_drawdown_pct = (net_drawdown_usd / initial_capital) * 100
    else:
        net_drawdown_usd = 0.0
        net_drawdown_pct = 0.0

    return {
        "Max_Drawdown_USD": round(max_drawdown_usd, 2),
        "Max_Drawdown_Percent": round(max_drawdown_pct, 2),
        "Gross_Drawdown_USD": round(gross_drawdown_usd, 2),
        "Gross_Drawdown_Percent": round(gross_drawdown_pct, 2),
        "Net_Drawdown_USD": round(net_drawdown_usd, 2),
        "Net_Drawdown_Percent": round(net_drawdown_pct, 2),
        "Current_Drawdown_USD": round(current_drawdown_usd, 2),
        "Current_Drawdown_Percent": round(current_drawdown_pct, 2),
    }


def _classify_alpha(
    roi_per_day_pct: float,
    gross_drawdown_pct: float,
    net_drawdown_pct: float,
    criteria: AlphaCriteria,
) -> tuple[bool, str]:
    reasons = []
    if roi_per_day_pct <= criteria.min_roi_per_day_pct:
        reasons.append(f"ROI/day {roi_per_day_pct:.4f}% <= {criteria.min_roi_per_day_pct:.2f}%")
    if abs(gross_drawdown_pct) >= criteria.max_gross_drawdown_pct:
        reasons.append(f"|Gross DD| {abs(gross_drawdown_pct):.2f}% >= {criteria.max_gross_drawdown_pct:.2f}%")
    if abs(net_drawdown_pct) >= criteria.max_net_drawdown_pct:
        reasons.append(f"|Net DD| {abs(net_drawdown_pct):.2f}% >= {criteria.max_net_drawdown_pct:.2f}%")
    if reasons:
        return False, "; ".join(reasons)
    return True, "Meets alpha rule: ROI/day > 1% and |Gross DD|, |Net DD| < 20%"


def merge_summary_metrics(all_results: pd.DataFrame, summary_csv: Optional[Path]) -> pd.DataFrame:
    if all_results.empty or not summary_csv:
        return all_results
    summary_csv = Path(summary_csv)
    if not summary_csv.exists():
        return all_results

    try:
        summary = pd.read_csv(summary_csv)
    except Exception:
        return all_results
    if summary.empty:
        return all_results

    left = all_results.copy()
    right = summary.copy()

    left["_strategy_key"] = left["Strategy"].map(_normalize_name)
    left["_symbol_key"] = left["Symbol"].astype(str).str.upper()
    left["_timeframe_key"] = left["Timeframe"].astype(str).str.lower()
    right["_strategy_key"] = right["Strategy"].map(_normalize_name)
    right["_symbol_key"] = right["Symbol"].astype(str).str.upper()
    right["_timeframe_key"] = right["Timeframe"].astype(str).str.lower()

    summary_cols = [
        "Profit Factor",
        "OOS ROI %",
        "OOS Max DD %",
        "WF Avg ROI %",
        "WF Pass Rate %",
        "WF Windows",
        "Reality Score",
        "Credibility Flags",
        "Shortlist Eligible",
        "Sizing Mode",
        "Fixed Notional",
        "Sizing Max Fraction",
        "Slippage Bps",
        "CSV File",
    ]
    summary_cols = [col for col in summary_cols if col in right.columns]

    merged = left.merge(
        right[["_strategy_key", "_symbol_key", "_timeframe_key", *summary_cols]],
        on=["_strategy_key", "_symbol_key", "_timeframe_key"],
        how="left",
    )
    return merged.drop(columns=["_strategy_key", "_symbol_key", "_timeframe_key"], errors="ignore")


def build_alpha_shortlist(alpha_candidates: pd.DataFrame, limit: int = 5) -> pd.DataFrame:
    if alpha_candidates.empty:
        return alpha_candidates.copy()

    shortlist = alpha_candidates.copy()
    if "Shortlist Eligible" in shortlist.columns:
        shortlist = shortlist[shortlist["Shortlist Eligible"].fillna("NO").astype(str).str.upper() == "YES"].copy()
    if shortlist.empty:
        shortlist = alpha_candidates.copy()

    sort_cols = [col for col in ["Reality Score", "OOS ROI %", "ROI_Per_Day_Pct", "Sharpe_Ratio", "Net_Profit_USD"] if col in shortlist.columns]
    ascending = [False] * len(sort_cols)
    if sort_cols:
        shortlist = shortlist.sort_values(by=sort_cols, ascending=ascending)
    shortlist = shortlist.head(max(int(limit), 1)).copy()
    shortlist["Shortlist Rank"] = range(1, len(shortlist) + 1)
    shortlist["Shortlist Status"] = "PAPER_CANDIDATE"
    return shortlist


def evaluate_trade_csv(
    csv_path: Path,
    initial_capital: float = 10_000.0,
    fees_exchange: str = "0.06%",
    data_source: str = "tv_backtester_jan_2024",
    criteria: AlphaCriteria = AlphaCriteria(),
) -> Optional[dict[str, object]]:
    frame = _normalize_trade_frame(pd.read_csv(csv_path))
    trades = frame[frame["type"].str.contains("Close|Exit", case=False, na=False)].copy()
    if trades.empty:
        return None

    net_profit = float(trades["pnl"].sum())
    final_capital = initial_capital + net_profit
    roi = net_profit / initial_capital if initial_capital else 0.0

    days_diff = max(int((frame["time"].max() - frame["time"].min()).days), 1)
    years_diff = max(days_diff / 365.25, 1e-6)
    ratio = float(np.clip(final_capital / initial_capital, 1e-6, None))
    roi_annum = (ratio ** (1 / years_diff)) - 1
    roi_per_day_pct = (roi_annum / 365) * 100

    total_trades = int(len(trades))
    wins = trades[trades["pnl"] > 0]
    losses = trades[trades["pnl"] < 0]
    win_rate = (len(wins) / total_trades) * 100 if total_trades else 0.0

    gross_profit = float(wins["pnl"].sum())
    gross_loss = abs(float(losses["pnl"].sum()))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

    avg_trade_pct = float(trades["pnl_pct"].mean()) if "pnl_pct" in trades.columns else (float(trades["pnl"].mean()) / initial_capital) * 100
    sharpe_ratio = _calculate_sharpe_ratio(frame, trades, initial_capital, days_diff)
    drawdowns = _calculate_drawdowns(trades, initial_capital, gross_loss)

    strategy, asset, timeframe = _extract_metadata(csv_path.name)
    is_alpha, alpha_reason = _classify_alpha(
        roi_per_day_pct=roi_per_day_pct,
        gross_drawdown_pct=_safe_float(drawdowns["Gross_Drawdown_Percent"]),
        net_drawdown_pct=_safe_float(drawdowns["Net_Drawdown_Percent"]),
        criteria=criteria,
    )

    return {
        "Strategy": strategy,
        "Asset": asset.replace("USDT", "").replace("USD", ""),
        "Symbol": asset,
        "Timeframe": timeframe,
        "BB_Length": "",
        "BB_Mult": "",
        "KC_Mult": "",
        "SL_Pct": "",
        "TP_Pct": "",
        "Trail_Pct": "",
        "Net_Profit_USD": round(net_profit, 2),
        "ROI_Percent": round(roi * 100, 2),
        "ROI": round(roi, 4),
        "ROI_Annual_Percent": round(roi_annum * 100, 2),
        "ROI_Per_Day_Pct": round(roi_per_day_pct, 4),
        "Win_Rate_Percent": round(win_rate, 2),
        "Profit_Factor": round(profit_factor, 2),
        "Sharpe_Ratio": round(sharpe_ratio, 2),
        "Avg_Trade_Percent": round(avg_trade_pct, 4),
        **drawdowns,
        "Performance_Grade": "ALPHA" if is_alpha else "NON_ALPHA",
        "Deployment_Status": "ALPHA_READY" if is_alpha else "REJECT",
        "Alpha_Qualified": "YES" if is_alpha else "NO",
        "Alpha_Reason": alpha_reason,
        "Rank": 0,
        "Initial_Capital_USD": initial_capital,
        "Final_Capital_USD": round(final_capital, 2),
        "Time_period_checked": f"{days_diff}_days",
        "Time_start": frame["time"].min().strftime("%d-%m-%Y"),
        "time_end": frame["time"].max().strftime("%d-%m-%Y"),
        "fees_exchnage": fees_exchange,
        "Total_Trades": total_trades,
        "Data_Source": data_source,
        "Source_CSV": str(csv_path),
    }


def build_alpha_reports(
    input_folder: Path,
    report_dir: Path,
    initial_capital: float = 10_000.0,
    fees_exchange: str = "0.06%",
    data_source: str = "tv_backtester_jan_2024",
    criteria: AlphaCriteria = AlphaCriteria(),
    summary_csv: Optional[Path] = None,
) -> dict[str, pd.DataFrame]:
    input_folder = Path(input_folder)
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    summaries: list[dict[str, object]] = []
    for csv_path in sorted(input_folder.glob("*.csv")):
        if csv_path.name.upper() == "SUMMARY.CSV":
            continue
        try:
            summary = evaluate_trade_csv(
                csv_path=csv_path,
                initial_capital=initial_capital,
                fees_exchange=fees_exchange,
                data_source=data_source,
                criteria=criteria,
            )
            if summary:
                summaries.append(summary)
        except Exception:
            continue

    all_results = pd.DataFrame(summaries)
    if all_results.empty:
        return {"all": all_results, "alpha": all_results.copy(), "best": all_results.copy()}

    all_results = all_results.sort_values(
        by=["Alpha_Qualified", "ROI_Per_Day_Pct", "Net_Profit_USD"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    all_results = merge_summary_metrics(all_results, summary_csv)
    all_results["Rank"] = range(1, len(all_results) + 1)

    alpha_candidates = all_results[all_results["Alpha_Qualified"] == "YES"].copy()
    best_per_symbol = all_results.head(0).copy()
    if not alpha_candidates.empty:
        best_per_symbol = (
            alpha_candidates.sort_values(
                by=["ROI_Per_Day_Pct", "Sharpe_Ratio", "Net_Profit_USD"],
                ascending=[False, False, False],
            )
            .groupby("Symbol", as_index=False)
            .first()
        )

    all_results.to_csv(report_dir / "alpha_backtest_results.csv", index=False)
    alpha_candidates.to_csv(report_dir / "alpha_candidates.csv", index=False)
    best_per_symbol.to_csv(report_dir / "alpha_best_per_symbol.csv", index=False)

    return {"all": all_results, "alpha": alpha_candidates, "best": best_per_symbol}


def _signal_variable_pair(pine_text: str) -> Optional[tuple[str, str]]:
    for long_var, short_var in SIGNAL_VARIABLE_PAIRS:
        if long_var in pine_text and short_var in pine_text:
            return long_var, short_var
    return None


def _strip_existing_alertconditions(pine_text: str) -> str:
    return re.sub(r"(?m)^\s*alertcondition\(.*\)\s*$\n?", "", pine_text)


def _build_alertcondition_message(row: pd.Series, action: str, webhook_secret: str) -> str:
    payload = {
        "secret": webhook_secret,
        "strategy": str(row.get("Strategy", "")),
        "action": action,
        "is_exit": False,
        "symbol": str(row.get("Symbol", "")),
        "timeframe": str(row.get("Timeframe", "")),
        "price": "{{close}}",
        "quantity": 0.003,
        "exchange": "binance",
        "indicator": str(row.get("Strategy", "")),
        "sl_pct": _safe_float(row.get("SL_Pct", 0.0)),
        "tp_pct": _safe_float(row.get("TP_Pct", 0.0)),
        "ts_pct": _safe_float(row.get("Trail_Pct", 0.0)),
    }
    message = json.dumps(payload, separators=(",", ":"))
    return message.replace("\\", "\\\\").replace("'", "\\'")


def _find_matching_pine_file(strategies_dir: Path, symbol: str, strategy: str, timeframe: str) -> Optional[Path]:
    if not strategies_dir.exists():
        return None

    files = list(strategies_dir.glob("*.pine"))
    if not files:
        return None

    norm_symbol = _normalize_name(symbol)
    norm_strategy = _normalize_name(strategy)
    norm_tf = _normalize_name(timeframe)

    scored: list[tuple[int, Path]] = []
    for path in files:
        norm_name = _normalize_name(path.stem)
        score = 0
        if norm_symbol and norm_symbol in norm_name:
            score += 5
        if norm_tf and norm_tf in norm_name:
            score += 3
        if norm_strategy and norm_strategy in norm_name:
            score += 10

        strategy_tokens = [token for token in re.split(r"[^a-z0-9]+", norm_strategy) if token]
        for token in strategy_tokens:
            if token in norm_name:
                score += 1

        if score > 0:
            scored.append((score, path))

    if not scored:
        return None
    scored.sort(key=lambda item: (-item[0], len(item[1].name)))
    return scored[0][1]


def generate_alpha_pine_scripts(
    alpha_candidates: pd.DataFrame,
    strategies_dir: Path,
    output_dir: Path,
    webhook_secret: str,
) -> pd.DataFrame:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    updated_rows: list[pd.Series] = []
    for _, row in alpha_candidates.iterrows():
        row = row.copy()
        source_path = _find_matching_pine_file(
            strategies_dir=Path(strategies_dir),
            symbol=str(row.get("Symbol", "")),
            strategy=str(row.get("Strategy", "")),
            timeframe=str(row.get("Timeframe", "")),
        )
        row["Pine_Script_Source"] = str(source_path) if source_path else ""
        row["Generated_Pine_Script"] = ""
        row["Webhook_Ready"] = "NO"
        row["Webhook_Reason"] = "No matching Pine file found"

        if not source_path:
            updated_rows.append(row)
            continue

        pine_text = source_path.read_text(encoding="utf-8", errors="ignore")
        signal_vars = _signal_variable_pair(pine_text)
        if not signal_vars:
            row["Webhook_Reason"] = "No supported signal variables found (expected longCond/shortCond style)"
            updated_rows.append(row)
            continue

        pine_text = _strip_existing_alertconditions(pine_text).rstrip()
        long_var, short_var = signal_vars
        long_message = _build_alertcondition_message(row, "BUY", webhook_secret)
        short_message = _build_alertcondition_message(row, "SELL", webhook_secret)
        header = (
            f"// Alpha Engine Webhook Copy\n"
            f"// Source: {source_path.name}\n"
            f"// Alpha Rule: ROI/day > 1% and |Gross DD|, |Net DD| < 20%\n"
            f"// ROI/day: {row.get('ROI_Per_Day_Pct', 0):.4f}% | Gross DD: {row.get('Gross_Drawdown_Percent', 0):.2f}% | Net DD: {row.get('Net_Drawdown_Percent', 0):.2f}%\n"
        )
        webhook_block = (
            "\n\n// Alpha Engine Webhook Alerts\n"
            f"alertcondition({long_var}, \"Webhook BUY\", '{long_message}')\n"
            f"alertcondition({short_var}, \"Webhook SELL\", '{short_message}')\n"
        )

        generated_name = f"{row.get('Symbol', 'UNKNOWN')}_{_slugify(row.get('Strategy', 'strategy'))}_{row.get('Timeframe', '1h')}_alpha_webhook.pine"
        generated_path = output_dir / generated_name
        generated_path.write_text(header + "\n" + pine_text + webhook_block, encoding="utf-8")

        row["Generated_Pine_Script"] = str(generated_path)
        row["Webhook_Ready"] = "YES"
        row["Webhook_Reason"] = "Generated webhook-ready Pine copy"
        updated_rows.append(row)

    return pd.DataFrame(updated_rows)


def write_pipeline_status(
    report_dir: Path,
    all_results: pd.DataFrame,
    alpha_candidates: pd.DataFrame,
    best_per_symbol: pd.DataFrame,
    shortlist: pd.DataFrame,
    input_dir: Path,
    scripts_dir: Path,
) -> Path:
    report_dir = Path(report_dir)
    status_path = report_dir / "alpha_pipeline_status.json"
    payload = {
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "input_dir": str(input_dir),
        "alpha_scripts_dir": str(scripts_dir),
        "all_results_count": int(len(all_results)),
        "alpha_candidates_count": int(len(alpha_candidates)),
        "best_symbol_count": int(len(best_per_symbol)),
        "shortlist_count": int(len(shortlist)),
        "best_alpha_symbol": best_per_symbol.iloc[0]["Symbol"] if not best_per_symbol.empty else "",
        "best_alpha_strategy": best_per_symbol.iloc[0]["Strategy"] if not best_per_symbol.empty else "",
        "best_alpha_roi_per_day_pct": _safe_float(best_per_symbol.iloc[0]["ROI_Per_Day_Pct"]) if not best_per_symbol.empty else 0.0,
    }
    status_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return status_path


def _send_document(bot_token: str, chat_id: str, file_path: Path, caption: str) -> bool:
    try:
        with Path(file_path).open("rb") as handle:
            response = requests.post(
                f"https://api.telegram.org/bot{bot_token}/sendDocument",
                data={"chat_id": chat_id, "caption": caption[:1024]},
                files={"document": (Path(file_path).name, handle, "text/plain")},
                timeout=30,
            )
        return response.status_code == 200
    except Exception:
        return False


def notify_alpha_candidates(
    alpha_candidates: pd.DataFrame,
    status_path: Path,
    telegram: Optional[TelegramAlert] = None,
    send_scripts: bool = True,
) -> None:
    if telegram is None:
        telegram = TelegramAlert()

    if alpha_candidates.empty:
        telegram.send(
            severity=AlertSeverity.WARNING,
            title="Alpha Engine Report",
            message="No alpha strategies qualified.\n\nRule: ROI/day &gt; 1% and |Gross DD|, |Net DD| &lt; 20%",
            force=True,
        )
        return

    summary_lines = [
        f"Qualified alpha strategies: <b>{len(alpha_candidates)}</b>",
        "Rule: ROI/day &gt; 1% | |Gross DD| &lt; 20% | |Net DD| &lt; 20%",
    ]
    top_rows = alpha_candidates.sort_values("ROI_Per_Day_Pct", ascending=False).head(10)
    for idx, (_, row) in enumerate(top_rows.iterrows(), start=1):
        summary_lines.append(
            f"{idx}. <b>{row['Symbol']}</b> | {row['Strategy']} | ROI/day <code>{row['ROI_Per_Day_Pct']:.4f}%</code> | "
            f"GDD <code>{row['Gross_Drawdown_Percent']:.2f}%</code> | NDD <code>{row['Net_Drawdown_Percent']:.2f}%</code>"
        )

    telegram.send(
        severity=AlertSeverity.INFO,
        title="Alpha Engine Report",
        message="\n".join(summary_lines),
        force=True,
    )

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    for _, row in alpha_candidates.sort_values("ROI_Per_Day_Pct", ascending=False).iterrows():
        detail_message = (
            f"<b>Strategy:</b> {row['Strategy']}\n"
            f"<b>Symbol:</b> {row['Symbol']} | <b>TF:</b> {row['Timeframe']}\n"
            f"<b>ROI/day:</b> <code>{row['ROI_Per_Day_Pct']:.4f}%</code>\n"
            f"<b>ROI/year:</b> <code>{row['ROI_Annual_Percent']:.2f}%</code>\n"
            f"<b>Gross DD:</b> <code>{row['Gross_Drawdown_Percent']:.2f}%</code>\n"
            f"<b>Net DD:</b> <code>{row['Net_Drawdown_Percent']:.2f}%</code>\n"
            f"<b>Win Rate:</b> <code>{row['Win_Rate_Percent']:.2f}%</code>\n"
            f"<b>Profit Factor:</b> <code>{row['Profit_Factor']:.2f}</code>\n"
            f"<b>Sharpe:</b> <code>{row['Sharpe_Ratio']:.2f}</code>\n"
            f"<b>Total Trades:</b> <code>{row['Total_Trades']}</code>\n"
            f"<b>Source:</b> <code>{Path(row['Source_CSV']).name}</code>\n"
            f"<b>Pine Ready:</b> <code>{row.get('Webhook_Ready', 'NO')}</code>"
        )
        telegram.send(
            severity=AlertSeverity.INFO,
            title=f"Alpha Strategy: {row['Symbol']}",
            message=detail_message,
            alert_key=None,
            force=True,
        )

        generated_script = str(row.get("Generated_Pine_Script", "")).strip()
        if send_scripts and generated_script and bot_token and chat_id and Path(generated_script).exists():
            caption = (
                f"{row['Symbol']} | {row['Strategy']} | {row['Timeframe']} | "
                f"ROI/day {row['ROI_Per_Day_Pct']:.4f}%"
            )
            _send_document(bot_token, chat_id, Path(generated_script), caption)

    if Path(status_path).exists() and bot_token and chat_id:
        _send_document(bot_token, chat_id, Path(status_path), "Alpha pipeline status")
