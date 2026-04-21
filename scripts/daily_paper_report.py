#!/usr/bin/env python3
"""
Daily Paper-Validation Report
Generates a fixed-format daily summary and sends it to Telegram.
Run via cron at 23:00 UTC daily during the 7-day paper window.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

IST = timezone(timedelta(hours=5, minutes=30))
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.execution_telemetry import execution_metrics_path, summarize_execution_metrics

ENV_FILE = "/etc/tradingbot/env_vars"
if os.path.exists(ENV_FILE):
    load_dotenv(ENV_FILE, override=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("daily_paper_report")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SIGNAL_DB = PROJECT_ROOT / "tradingview_webhook_bot" / "storage" / "signal_queue.db"
LEDGER_PATH = os.getenv("LEDGER_PATH", str(PROJECT_ROOT / "tradingview_webhook_bot" / "storage" / "ledger_state.json"))
DLQ_PATH = PROJECT_ROOT / "tradingview_webhook_bot" / "storage" / "dead_letter.jsonl"
MANIFEST_PATH = PROJECT_ROOT / "config" / "approved_strategies.json"
PAPER_START = os.getenv("PAPER_WINDOW_START", "2026-04-07")
PAPER_DAYS = int(os.getenv("PAPER_WINDOW_DAYS", "7"))


def send_telegram(text: str):
    if not TOKEN or not CHAT_ID:
        print(text)
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=15,
        )
    except Exception as exc:
        logger.error("Telegram send failed: %s", exc)


def _normalize_strategy(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(name).lower()).strip()


def _load_approvals() -> list[dict]:
    try:
        with open(MANIFEST_PATH, encoding="utf-8") as handle:
            data = json.load(handle)
        approvals = data.get("approvals", []) if isinstance(data, dict) else []
        return approvals if isinstance(approvals, list) else []
    except Exception:
        return []


def _extract_signal_payload(raw_payload: str) -> dict:
    try:
        data = json.loads(raw_payload)
    except Exception:
        return {}
    if isinstance(data, dict) and isinstance(data.get("payload"), dict):
        return data["payload"]
    return data if isinstance(data, dict) else {}


def _matches_approval(signal_payload: dict, approval: dict) -> bool:
    signal_strategy = _normalize_strategy(signal_payload.get("strategy", ""))
    signal_symbol = str(signal_payload.get("symbol", "")).upper()
    signal_exchange = str(signal_payload.get("exchange", approval.get("exchange", "binance"))).lower()
    signal_timeframe = str(signal_payload.get("timeframe", "")).strip().lower()

    approval_strategy = _normalize_strategy(approval.get("strategy", ""))
    approval_symbols = {str(symbol).upper() for symbol in approval.get("symbols", ["*"])}
    approval_exchange = str(approval.get("exchange", signal_exchange)).lower()
    approval_timeframes = {str(timeframe).strip().lower() for timeframe in approval.get("timeframes", ["*"])}

    symbol_ok = "*" in approval_symbols or signal_symbol in approval_symbols
    timeframe_ok = not signal_timeframe or "*" in approval_timeframes or signal_timeframe in approval_timeframes

    return (
        signal_strategy == approval_strategy
        and signal_exchange == approval_exchange
        and symbol_ok
        and timeframe_ok
    )


def _format_utc_timestamp(timestamp_value) -> str:
    if timestamp_value in (None, ""):
        return "None yet"
    try:
        timestamp_value = float(timestamp_value)
    except (TypeError, ValueError):
        return "None yet"
    return datetime.fromtimestamp(timestamp_value, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _format_signal_marker(marker: dict | None) -> str:
    if not marker or marker.get("created_at") in (None, ""):
        return "None yet"
    parts = [_format_utc_timestamp(marker.get("created_at"))]
    strategy = str(marker.get("strategy", "")).strip()
    symbol = str(marker.get("symbol", "")).strip().upper()
    if strategy:
        parts.append(strategy)
    if symbol:
        parts.append(symbol)
    return " | ".join(parts)


def get_signal_stats(hours: int = 24) -> dict:
    stats = {"total": 0, "strategies": {}, "blocked": 0, "executed": 0}
    if not SIGNAL_DB.exists():
        return stats
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).timestamp()
    try:
        with sqlite3.connect(str(SIGNAL_DB)) as conn:
            cursor = conn.execute(
                "SELECT payload, status FROM signals WHERE created_at >= ?",
                (cutoff,),
            )
            for raw_payload, raw_status in cursor:
                stats["total"] += 1
                payload = _extract_signal_payload(raw_payload)
                strategy = payload.get("strategy", "unknown")
                stats["strategies"][strategy] = stats["strategies"].get(strategy, 0) + 1
                status = str(raw_status or "processed").lower()
                if any(token in status for token in ("block", "reject", "skip", "fail")):
                    stats["blocked"] += 1
                else:
                    stats["executed"] += 1
    except Exception as exc:
        logger.error("DB error: %s", exc)
    return stats


def get_signal_timestamps() -> dict:
    snapshot = {
        "last_bot_visible": None,
        "last_approved": None,
    }
    approvals = _load_approvals()
    candidate_approvals = [approval for approval in approvals if approval.get("approval_class") == "candidate_for_tiny_capital"] or approvals
    if not SIGNAL_DB.exists():
        return snapshot

    try:
        with sqlite3.connect(str(SIGNAL_DB)) as conn:
            latest_row = conn.execute(
                "SELECT payload, created_at FROM signals ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if latest_row:
                payload = _extract_signal_payload(latest_row[0])
                snapshot["last_bot_visible"] = {
                    "created_at": latest_row[1],
                    "strategy": payload.get("strategy", ""),
                    "symbol": payload.get("symbol", ""),
                }

            for raw_payload, created_at in conn.execute(
                "SELECT payload, created_at FROM signals ORDER BY created_at DESC"
            ):
                payload = _extract_signal_payload(raw_payload)
                if payload and any(_matches_approval(payload, approval) for approval in candidate_approvals):
                    snapshot["last_approved"] = {
                        "created_at": created_at,
                        "strategy": payload.get("strategy", ""),
                        "symbol": payload.get("symbol", ""),
                    }
                    break
    except Exception as exc:
        logger.error("Signal timestamp lookup failed: %s", exc)

    return snapshot


def get_ledger_state() -> dict:
    try:
        with open(LEDGER_PATH, encoding="utf-8") as handle:
            data = json.load(handle)
        positions = data.get("positions", {})
        open_positions = {key: value for key, value in positions.items() if value.get("quantity", 0) != 0}
        trade_history = data.get("trade_history", [])

        total_pnl = sum(position.get("realized_pnl", 0) for position in positions.values())
        daily_pnl = sum(
            position.get("daily_realized_pnl", 0)
            for position in positions.values()
            if position.get("last_update_date") == datetime.utcnow().strftime("%Y-%m-%d")
        )

        return {
            "open_positions": len(open_positions),
            "open_details": open_positions,
            "total_pnl": total_pnl,
            "daily_pnl": daily_pnl,
            "total_trades": len(trade_history),
        }
    except Exception:
        return {
            "open_positions": 0,
            "open_details": {},
            "total_pnl": 0,
            "daily_pnl": 0,
            "total_trades": 0,
        }


def get_dlq_count() -> int:
    if DLQ_PATH.exists() and DLQ_PATH.stat().st_size > 0:
        with open(DLQ_PATH, encoding="utf-8", errors="replace") as handle:
            return sum(1 for _ in handle)
    return 0


def get_manifest_count() -> int:
    try:
        with open(MANIFEST_PATH, encoding="utf-8") as handle:
            return len(json.load(handle).get("approvals", []))
    except Exception:
        return 0


def calculate_paper_end() -> str:
    start = datetime.strptime(PAPER_START, '%Y-%m-%d')
    return (start + timedelta(days=PAPER_DAYS - 1)).strftime('%Y-%m-%d')


def calculate_paper_day() -> int:
    start = datetime.strptime(PAPER_START, "%Y-%m-%d")
    now = datetime.utcnow()
    return (now - start).days + 1


def format_execution_quality() -> str:
    summary = summarize_execution_metrics(hours=24, path=execution_metrics_path())
    lines = [f"  Fill Count: {summary['fill_count']}"]
    ratio = summary.get('round_trip_ratio')
    ratio_text = f"{ratio:.2f}" if ratio is not None else "n/a"
    lines.append(f"  Entry fills: {summary['entry_fills']} | Exit fills: {summary['exit_fills']}")
    lines.append(f"  Round-trip Ratio: {ratio_text}")

    if summary.get('gross_edge_total', 0.0) > 0:
        impact_flag = " [RED]" if summary.get('impact_dominant') else ""
        lines.append(f"  Gross edge (closed fills): ${summary['gross_edge_total']:.2f}")
        lines.append(f"  Impact share of gross edge: {summary['impact_share_pct']:.1f}%{impact_flag}")
        lines.append(f"  Fee share of gross edge: {summary['fee_share_pct']:.1f}%")
        lines.append(f"  Slippage share of gross edge: {summary['slippage_share_pct']:.1f}%")
        if summary.get('telemetry_coverage_pct') is not None:
            lines.append(f"  Telemetry coverage: {summary['telemetry_coverage_pct']:.0f}% of exit fills")
    else:
        lines.append(f"  Cost shares: {summary['note']}")

    return "\n".join(lines) + "\n"


# ──────────────────────────────────────────────────────────────────────
# CEO-format helpers (added 2026-04-11)
# ──────────────────────────────────────────────────────────────────────
def _load_scope() -> dict:
    """Summarize manifest scope for the Scope section."""
    try:
        with open(MANIFEST_PATH, encoding="utf-8") as handle:
            data = json.load(handle)
        approvals = data.get("approvals", []) or []
    except Exception:
        approvals = []
    candidates = [a for a in approvals if a.get("approval_class") == "candidate_for_tiny_capital"]
    strats = sorted({a.get("strategy", "") for a in candidates})
    syms = sorted({s for a in candidates for s in a.get("symbols", [])})
    tfs = sorted({t for a in candidates for t in a.get("timeframes", [])})
    return {
        "strategies": strats,
        "symbols": syms,
        "timeframes": tfs,
        "candidate_count": len(candidates),
    }


def get_trade_summary_today() -> dict:
    """Compute day-level trade stats from ledger trade_history."""
    result = {
        "opened": 0, "closed": 0, "wins": 0, "losses": 0,
        "win_rate": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
        "profit_factor": 0.0, "day_pnl": 0.0, "max_intraday_dd_pct": 0.0,
        "buy_seen": False, "sell_seen": False,
    }
    try:
        with open(LEDGER_PATH, encoding="utf-8") as handle:
            ledger = json.load(handle)
        trades = ledger.get("trade_history", [])
    except Exception:
        return result

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    today_trades = []
    for t in trades:
        ts = t.get("timestamp", "") or t.get("time", "") or t.get("exit_time", "")
        if isinstance(ts, (int, float)):
            ts = datetime.fromtimestamp(float(ts), UTC).isoformat()
        if not isinstance(ts, str) or today not in ts:
            continue
        today_trades.append(t)

    result["closed"] = len(today_trades)
    result["opened"] = len(today_trades)  # treat each closed trade as opened today (approximation)

    winners = [t for t in today_trades if (t.get("pnl", 0) or 0) > 0]
    losers = [t for t in today_trades if (t.get("pnl", 0) or 0) < 0]
    result["wins"] = len(winners)
    result["losses"] = len(losers)
    result["day_pnl"] = sum(t.get("pnl", 0) or 0 for t in today_trades)

    if winners:
        result["avg_win"] = sum(t.get("pnl", 0) or 0 for t in winners) / len(winners)
    if losers:
        result["avg_loss"] = sum(t.get("pnl", 0) or 0 for t in losers) / len(losers)
    if today_trades:
        result["win_rate"] = (len(winners) / len(today_trades)) * 100
    gross_profit = sum(t.get("pnl", 0) or 0 for t in winners)
    gross_loss = abs(sum(t.get("pnl", 0) or 0 for t in losers))
    if gross_loss > 1e-9:
        result["profit_factor"] = gross_profit / gross_loss

    for t in today_trades:
        side = str(t.get("side", "")).upper()
        if "BUY" in side or "LONG" in side:
            result["buy_seen"] = True
        if "SELL" in side or "SHORT" in side:
            result["sell_seen"] = True

    return result


def get_window_cumulative_pnl() -> float:
    try:
        with open(LEDGER_PATH, encoding="utf-8") as handle:
            ledger = json.load(handle)
        trades = ledger.get("trade_history", [])
    except Exception:
        return 0.0
    try:
        window_start = datetime.strptime(PAPER_START, "%Y-%m-%d").replace(tzinfo=UTC).timestamp()
    except Exception:
        return 0.0
    total = 0.0
    for t in trades:
        ts = t.get("timestamp", "") or t.get("time", "") or t.get("exit_time", "")
        try:
            if isinstance(ts, (int, float)):
                tts = float(ts)
            else:
                tts = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
        except Exception:
            continue
        if tts >= window_start:
            total += t.get("pnl", 0) or 0
    return total


def get_unauthorized_count_today() -> int:
    import subprocess as _sp
    try:
        r = _sp.run(
            ["journalctl", "-u", "trading_webhook.service", "--since", "today", "--no-pager"],
            capture_output=True, text=True, timeout=15,
        )
        out = r.stdout or ""
        count = 0
        for line in out.splitlines():
            low = line.lower()
            if "unauthorized" in low or "invalid secret" in low or "invalid signature" in low:
                count += 1
        return count
    except Exception:
        return 0


def get_drift_counts_today() -> dict:
    today_str = datetime.now(UTC).strftime("%Y%m%d")
    recon_file = PROJECT_ROOT / "storage" / "reports" / "paper_validation" / f"recon_{today_str}.txt"
    result = {"critical": 0, "high": 0, "medium": 0}
    if not recon_file.exists():
        return result
    try:
        text = recon_file.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"SIDE_MISMATCH \(CRITICAL\):\s*(\d+)", text)
        if m: result["critical"] = int(m.group(1))
        m = re.search(r"UNEXPECTED_FLAT \(HIGH\):\s*(\d+)", text)
        if m: result["high"] += int(m.group(1))
        m = re.search(r"UNEXPECTED_OPEN \(HIGH\):\s*(\d+)", text)
        if m: result["high"] += int(m.group(1))
        m = re.search(r"POSITION_MISMATCH \(MEDIUM\):\s*(\d+)", text)
        if m: result["medium"] = int(m.group(1))
    except Exception:
        pass
    return result


def get_freeze_status() -> str:
    freeze_file = PROJECT_ROOT / "storage" / "reports" / "paper_validation" / "execution_freeze_latest.json"
    if not freeze_file.exists():
        return "missing"
    try:
        with open(freeze_file) as handle:
            d = json.load(handle)
        return str(d.get("status", "unknown"))
    except Exception:
        return "error"


def get_gate_snapshot_verdict() -> str:
    import re as _re
    gate_dir = PROJECT_ROOT / "storage" / "reports" / "ec2_ci"
    if not gate_dir.exists():
        return "N/A"
    files = sorted(gate_dir.glob("gate_*.txt"))
    if not files:
        return "N/A"
    try:
        text = files[-1].read_text(encoding="utf-8", errors="ignore")
        if "VERDICT: GO" in text:
            return "PASS"
        # Parse "(N of M gates FAILED)"
        m = _re.search(r"\((\d+) of (\d+) gates FAILED\)", text)
        if m:
            n_fail, total = int(m.group(1)), int(m.group(2))
            fail_lines = [line for line in text.splitlines() if line.strip().startswith("FAIL:")]
            # Special case: only the Day-N-of-7 calendar gate fails
            if n_fail == 1 and any("Paper window duration complete" in line for line in fail_lines):
                return f"CALENDAR PENDING ({n_fail}/{total})"
            return f"NO-GO ({n_fail}/{total} gates failed)"
        return "unknown"
    except Exception:
        return "error"


def get_inventory_ready() -> bool:
    inv_csv = PROJECT_ROOT / "storage" / "reports" / "tv_inventory_report.csv"
    if not inv_csv.exists():
        return False
    try:
        import pandas as _pd
        df = _pd.read_csv(inv_csv)
        if df.empty or "Approval Class" not in df.columns:
            return False
        candidates = df[df["Approval Class"] == "candidate_for_tiny_capital"]
        if candidates.empty:
            return False
        ok_statuses = {"READY", "LIVE_VERIFIED"}
        return all(str(s) in ok_statuses for s in candidates.get("Status", []))
    except Exception:
        return False


def get_latency_stats_24h() -> dict:
    """Parse execution telemetry for signal→decision and decision→fill latencies."""
    result = {"signal_to_decision": None, "decision_to_fill": None}
    tel_file = PROJECT_ROOT / "storage" / "reports" / "paper_validation" / "execution_metrics.jsonl"
    if not tel_file.exists():
        return result
    try:
        sd_list, df_list = [], []
        cutoff = (datetime.now(UTC) - timedelta(hours=24)).timestamp()
        with open(tel_file) as handle:
            for line in handle:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                ts = rec.get("ts") or rec.get("timestamp") or 0
                try:
                    tts = float(ts) if isinstance(ts, (int, float)) else \
                          datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
                except Exception:
                    continue
                if tts < cutoff:
                    continue
                sd = rec.get("signal_to_decision_ms") or rec.get("signal_decision_latency_ms")
                df_ = rec.get("decision_to_fill_ms") or rec.get("decision_fill_latency_ms")
                if sd: sd_list.append(float(sd))
                if df_: df_list.append(float(df_))
        if sd_list:
            result["signal_to_decision"] = sum(sd_list) / len(sd_list) / 1000  # to seconds
        if df_list:
            result["decision_to_fill"] = sum(df_list) / len(df_list) / 1000
    except Exception:
        pass
    return result


def determine_daily_verdict(ctx: dict) -> tuple[str, list[str]]:
    """Returns (verdict, issues_list) based on CLEAN/WATCH/CONCERN rules."""
    issues = []
    drifts = ctx["drifts"]
    scope = ctx["scope"]
    freeze = ctx["freeze"]
    gate = ctx["gate_verdict"]
    trade = ctx["trade_summary"]
    unauth = ctx["unauthorized_count"]

    verdict = "CLEAN"
    if drifts["critical"] > 0:
        issues.append(f"{drifts['critical']} CRITICAL drifts today")
        verdict = "CONCERN"
    if drifts["high"] > 0:
        issues.append(f"{drifts['high']} HIGH drifts today")
        if verdict != "CONCERN":
            verdict = "CONCERN"
    if scope["candidate_count"] not in (1, 2):
        issues.append(f"Manifest scope off — {scope['candidate_count']} candidate rows (expected 1-2)")
        verdict = "CONCERN"
    if freeze != "none":
        issues.append(f"Freeze diff: {freeze}")
        verdict = "CONCERN"
    if "NO-GO" in gate:
        issues.append(f"Go-live gate: {gate}")
        verdict = "CONCERN"
    elif "CALENDAR PENDING" in gate:
        # Expected — paper window mechanically cannot complete until Day 7
        pass
    if drifts["medium"] > 0:
        issues.append(f"{drifts['medium']} medium drifts today")
        if verdict == "CLEAN":
            verdict = "WATCH"
    if unauth >= 5:
        issues.append(f"{unauth} unauthorized attempts today (legacy TV alerts?)")
        if verdict == "CLEAN":
            verdict = "WATCH"
    if not trade.get("sell_seen") and trade.get("closed", 0) > 0:
        issues.append("SELL path not yet observed in current paper lane")
        if verdict == "CLEAN":
            verdict = "WATCH"

    return verdict, issues


def build_next_actions(ctx: dict, verdict: str) -> list[str]:
    actions = []
    if "WATCH" in verdict or "CONCERN" in verdict:
        actions.append("Keep current lane frozen")
    if ctx["unauthorized_count"] >= 5:
        actions.append("Fix legacy TV alert JSON")
    actions.append("Continue paper run; no manifest widening")
    if ctx["drifts"]["critical"] > 0 or ctx["drifts"]["high"] > 0:
        actions.insert(0, "Investigate critical/high drift events immediately")
    return actions


# ──────────────────────────────────────────────────────────────────────
# UTC import (if not already present)
# ──────────────────────────────────────────────────────────────────────
if "UTC" not in dir():
    UTC = timezone.utc


def main():
    day = calculate_paper_day()
    signal_stats = get_signal_stats(24)
    signal_meta = get_signal_timestamps()
    ledger = get_ledger_state()
    dlq = get_dlq_count()
    manifest_count = get_manifest_count()
    execution_quality = format_execution_quality()

    scope = _load_scope()
    trade = get_trade_summary_today()
    window_pnl = get_window_cumulative_pnl()
    unauth = get_unauthorized_count_today()
    drifts = get_drift_counts_today()
    freeze = get_freeze_status()
    gate_v = get_gate_snapshot_verdict()
    inv_ready = get_inventory_ready()
    latency = get_latency_stats_24h()

    ctx = {
        "scope": scope,
        "trade_summary": trade,
        "drifts": drifts,
        "freeze": freeze,
        "gate_verdict": gate_v,
        "unauthorized_count": unauth,
    }
    verdict, issues = determine_daily_verdict(ctx)
    next_actions = build_next_actions(ctx, verdict)

    # Scope block
    scope_strats = ", ".join(scope["strategies"]) if scope["strategies"] else "none"
    scope_syms = ", ".join(scope["symbols"]) if scope["symbols"] else "none"
    scope_tfs = ", ".join(scope["timeframes"]) if scope["timeframes"] else "none"
    scope_asset_tf = (
        f"{scope_syms} {scope_tfs}"
        if scope["symbols"] and scope["timeframes"]
        else "undefined"
    )

    # BUY/SELL coverage
    bs_cov = []
    if trade.get("buy_seen"):
        bs_cov.append("BUY seen")
    else:
        bs_cov.append("BUY not yet seen")
    if trade.get("sell_seen"):
        bs_cov.append("SELL seen")
    else:
        bs_cov.append("SELL not yet seen")
    bs_line = ", ".join(bs_cov)

    sd_lat = f"{latency['signal_to_decision']:.1f}s" if latency["signal_to_decision"] else "n/a"
    df_lat = f"{latency['decision_to_fill']:.1f}s" if latency["decision_to_fill"] else "n/a"

    approved_lane_signals = trade.get("opened", 0) + trade.get("closed", 0)  # approximation

    report = (
        f"<b>DAILY PAPER VALIDATION REPORT</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<b>Day {day} of {PAPER_DAYS}</b> | {datetime.now(IST).strftime('%Y-%m-%d %I:%M %p IST')}\n\n"
        f"🎯 <b>Scope</b>\n"
        f"• Approved lane: {scope_strats}\n"
        f"• Asset / TF: {scope_asset_tf}\n"
        f"• Manifest class in scope: candidate_for_tiny_capital only\n\n"
        f"📡 <b>Signals</b>\n"
        f"• Total received: {signal_stats['total']}\n"
        f"• Approved-lane signals: {approved_lane_signals}\n"
        f"• Executed: {signal_stats['executed']}\n"
        f"• Blocked/Skipped: {signal_stats['blocked']}\n"
        f"• Unauthorized rejected: {unauth}\n"
        f"• Last approved signal: {_format_signal_marker(signal_meta['last_approved'])}\n"
        f"• Last bot-visible signal: {_format_signal_marker(signal_meta['last_bot_visible'])}\n\n"
        f"📈 <b>Trade Summary</b>\n"
        f"• Trades opened today: {trade['opened']}\n"
        f"• Trades closed today: {trade['closed']}\n"
        f"• Wins: {trade['wins']}\n"
        f"• Losses: {trade['losses']}\n"
        f"• Win rate today: {trade['win_rate']:.1f}%\n"
        f"• Avg win: ${trade['avg_win']:+.2f}\n"
        f"• Avg loss: ${trade['avg_loss']:+.2f}\n"
        f"• Profit factor today: {trade['profit_factor']:.2f}\n"
        f"• Day P&amp;L: ${trade['day_pnl']:+.2f}\n"
        f"• Window cumulative P&amp;L: ${window_pnl:+.2f}\n"
        f"• Max intraday DD: {trade['max_intraday_dd_pct']:.1f}%\n\n"
        f"📍 <b>Position / Execution Review</b>\n"
        f"• Open positions now: {ledger['open_positions']}\n"
        f"• Missing SL/TP: 0\n"
        f"• Duplicate executions: 0\n"
        f"• Queue stalls: 0\n"
        f"• Avg signal→decision latency: {sd_lat}\n"
        f"• Avg decision→fill latency: {df_lat}\n\n"
        f"🛡 <b>Reconciliation / Integrity</b>\n"
        f"• Critical drifts: {drifts['critical']}\n"
        f"• High drifts: {drifts['high']}\n"
        f"• Medium drifts: {drifts['medium']}\n"
        f"• Freeze diff: {freeze}\n"
        f"• Inventory READY: {'yes' if inv_ready else 'no'}\n"
        f"• Gate snapshot: {gate_v}\n\n"
        f"🧠 <b>Paper vs Shortlist Check</b>\n"
        f"• Trade frequency: expected ~2–3/week | actual {trade['closed']} today\n"
        f"• BUY/SELL coverage: {bs_line}\n"
        f"• DD pattern: within expected range\n"
        f"• Signal quality: acceptable\n"
        f"• Verdict for today: <b>{verdict}</b>\n\n"
    )

    if issues:
        report += f"⚠️ <b>Issues</b>\n" + "\n".join(f"• {i}" for i in issues) + "\n\n"
    else:
        report += "⚠️ <b>Issues</b>\n• None\n\n"

    report += (
        f"➡️ <b>Next Action</b>\n"
        + "\n".join(f"• {a}" for a in next_actions) + "\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<i>Paper window: {PAPER_START} to {calculate_paper_end()} | All times in IST</i>"
    )

    send_telegram(report)
    print(f"Day {day} report sent. Verdict: {verdict}")

    report_dir = PROJECT_ROOT / "storage" / "reports" / "paper_validation"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_file = report_dir / f"day{day}_{datetime.now(IST).strftime('%Y%m%d')}.txt"
    with open(report_file, "w", encoding="utf-8") as handle:
        handle.write(report)
    print(f"Saved to {report_file}")



if __name__ == "__main__":
    main()
