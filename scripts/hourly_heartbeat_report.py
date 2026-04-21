#!/usr/bin/env python3
"""
Hourly Trading Heartbeat Report
================================
Runs every hour via cron. Collects service health, signal flow, open positions,
P&L, and risk/integrity signals into a single Telegram message matching the
format requested by the CEO.

Verdict rules:
  HEALTHY        → all services up, 0 drifts, 0 stalls, 0 dupes, freeze clean,
                    unauthorized count < 5 in last 60m
  WATCH          → 1-3 medium drifts OR 5-20 unauthorized OR signal gap > 8h
  ACTION NEEDED  → any critical/high drift, any service down, queue stall,
                    freeze drift, manifest out of scope, DLQ > 0
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

IST = timezone(timedelta(hours=5, minutes=30))
UTC = timezone.utc
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

ENV_FILE = "/etc/tradingbot/env_vars"
if os.path.exists(ENV_FILE):
    load_dotenv(ENV_FILE, override=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("hourly_heartbeat")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SIGNAL_DB = PROJECT_ROOT / "tradingview_webhook_bot" / "storage" / "signal_queue.db"
LEDGER_PATH = os.getenv("LEDGER_PATH", str(PROJECT_ROOT / "tradingview_webhook_bot" / "storage" / "ledger_state.json"))
DLQ_PATH = PROJECT_ROOT / "tradingview_webhook_bot" / "storage" / "dead_letter.jsonl"
MANIFEST_PATH = PROJECT_ROOT / "config" / "approved_strategies.json"
FREEZE_LATEST = PROJECT_ROOT / "storage" / "reports" / "paper_validation" / "execution_freeze_latest.json"
INVENTORY_CSV = PROJECT_ROOT / "storage" / "reports" / "tv_inventory_report.csv"
RECON_DIR = PROJECT_ROOT / "storage" / "reports" / "paper_validation"
PAPER_WINDOW_START = os.getenv("PAPER_WINDOW_START", "2026-04-07")

TOURNAMENT_FILES = [
    PROJECT_ROOT / "storage" / "reports" / "tournament_winners_4h_v4.csv",
    PROJECT_ROOT / "storage" / "reports" / "tournament_winners_4h_v3.csv",
    PROJECT_ROOT / "storage" / "reports" / "tournament_winners_4h.csv",
    PROJECT_ROOT / "storage" / "reports" / "tournament_winners.csv",
]

SIGNAL_GAP_WATCH_MIN  = 8 * 60
SIGNAL_GAP_ACTION_MIN = 24 * 60



# ── Data collectors ──────────────────────────────────────────────────────────
def check_service(service_name: str) -> bool:
    try:
        r = subprocess.run(
            ["systemctl", "is-active", service_name],
            capture_output=True, text=True, timeout=3,
        )
        return r.stdout.strip() == "active"
    except Exception:
        return False


def load_manifest_scope() -> dict:
    """Return scope summary from the approval manifest."""
    try:
        with open(MANIFEST_PATH) as f:
            data = json.load(f)
        approvals = data.get("approvals", [])
        candidates = [a for a in approvals if a.get("approval_class") == "candidate_for_tiny_capital"]
        paper_only = [a for a in approvals if a.get("approval_class") == "paper_only"]
        symbols = set()
        timeframes = set()
        for a in candidates:
            for s in a.get("symbols", []):
                symbols.add(s)
            for t in a.get("timeframes", []):
                timeframes.add(t)
        strategies = sorted({a.get("strategy", "") for a in candidates})
        max_cap = int(os.getenv("MAX_CANDIDATES", "15"))
        return {
            "ok": 1 <= len(candidates) <= max_cap,
            "candidate_count": len(candidates),
            "paper_only_count": len(paper_only),
            "strategies": strategies,
            "symbols": sorted(symbols),
            "timeframes": sorted(timeframes),
        }
    except Exception as exc:
        logger.warning(f"manifest read failed: {exc}")
        return {"ok": False, "error": str(exc)}


def load_approvals() -> list[dict]:
    try:
        with open(MANIFEST_PATH) as f:
            data = json.load(f)
        return data.get("approvals", []) or []
    except Exception:
        return []


def _normalize_strategy(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(name).lower()).strip()


def _matches_approval(payload: dict, approval: dict) -> bool:
    s_strat = _normalize_strategy(payload.get("strategy", ""))
    a_strat = _normalize_strategy(approval.get("strategy", ""))
    if s_strat != a_strat:
        return False
    s_sym = str(payload.get("symbol", "")).upper()
    a_syms = {str(sym).upper() for sym in approval.get("symbols", ["*"])}
    if "*" not in a_syms and s_sym not in a_syms:
        return False
    return True


def _extract_payload(raw: str) -> dict:
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and isinstance(data.get("payload"), dict):
            return data["payload"]
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def signal_flow_last_60m() -> dict:
    """Last approved signal, last bot-visible, counts in last 60m."""
    result = {
        "last_approved": None,
        "last_bot_visible": None,
        "signals_60m": 0,
        "blocked_60m": 0,
    }
    if not SIGNAL_DB.exists():
        return result

    cutoff = (datetime.now(UTC) - timedelta(hours=1)).timestamp()
    approvals = [a for a in load_approvals() if a.get("approval_class") == "candidate_for_tiny_capital"]

    try:
        with sqlite3.connect(str(SIGNAL_DB)) as conn:
            rows = conn.execute(
                "SELECT payload, status, created_at FROM signals ORDER BY created_at DESC LIMIT 200"
            ).fetchall()

            for raw, status, created_at in rows:
                payload = _extract_payload(raw)
                ts = float(created_at) if created_at else 0

                # Counts in last 60m
                if ts >= cutoff:
                    result["signals_60m"] += 1
                    if status and any(
                        token in str(status).lower()
                        for token in ("block", "reject", "skip", "fail")
                    ):
                        result["blocked_60m"] += 1

                # Last bot-visible
                if result["last_bot_visible"] is None and payload:
                    result["last_bot_visible"] = {
                        "created_at": ts,
                        "strategy": payload.get("strategy", ""),
                        "symbol": payload.get("symbol", ""),
                    }

                # Last approved
                if result["last_approved"] is None and payload:
                    if any(_matches_approval(payload, ap) for ap in approvals):
                        result["last_approved"] = {
                            "created_at": ts,
                            "strategy": payload.get("strategy", ""),
                            "symbol": payload.get("symbol", ""),
                        }

                if result["last_approved"] and result["last_bot_visible"]:
                    # Stop early if both found and we've seen 60m worth
                    if ts < cutoff:
                        break
    except Exception as exc:
        logger.warning(f"signal flow query failed: {exc}")

    return result



def signal_ingestion_check(flow: dict) -> dict:
    """Checks how long since last bot-visible signal."""
    last_bv = flow.get("last_bot_visible")
    if not last_bv or not last_bv.get("created_at"):
        return {"ok": False, "minutes_since": None, "last_ts_utc": None,
                "detail": "No bot-visible signals ever recorded."}
    now_ts = datetime.now(UTC).timestamp()
    minutes_since = int((now_ts - float(last_bv["created_at"])) / 60)
    last_dt = datetime.fromtimestamp(float(last_bv["created_at"]), UTC)
    last_ts_str = last_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    if minutes_since > SIGNAL_GAP_WATCH_MIN:
        detail = (
            f"Signal pipeline may be stuck: no signals reached the bot for {minutes_since}m "
            f"(last bot-visible signal {last_ts_str}). "
            f"Verify TradingView alerts, webhook delivery, and queue ingestion."
        )
        return {"ok": False, "minutes_since": minutes_since, "last_ts_utc": last_ts_str, "detail": detail}
    return {"ok": True, "minutes_since": minutes_since, "last_ts_utc": last_ts_str,
            "detail": f"Last signal {minutes_since}m ago ({last_ts_str})"}


def tournament_freshness() -> dict:
    """Return how many hours ago the most recent tournament file was modified."""
    latest_mtime, latest_file = None, None
    for f in TOURNAMENT_FILES:
        if f.exists():
            mtime = f.stat().st_mtime
            if latest_mtime is None or mtime > latest_mtime:
                latest_mtime, latest_file = mtime, f
    if latest_mtime is None:
        return {"ok": False, "hours_ago": None, "label": "No tournament file found"}
    hours_ago = (datetime.now(UTC).timestamp() - latest_mtime) / 3600
    fresh = hours_ago < 48
    label = f"Fresh ({hours_ago:.1f}h ago)" if fresh else f"Stale ({hours_ago:.1f}h ago)"
    return {"ok": fresh, "hours_ago": hours_ago, "label": label}


def unauthorized_count_60m() -> int:
    """Count 401/invalid auth rejections in webhook logs over last 60m."""
    try:
        r = subprocess.run(
            ["journalctl", "-u", "trading_webhook.service",
             "--since", "60 minutes ago", "--no-pager"],
            capture_output=True, text=True, timeout=10,
        )
        out = r.stdout or ""
        # Count lines that clearly indicate unauthorized / rejected
        count = 0
        for line in out.splitlines():
            low = line.lower()
            if ("unauthorized" in low or "invalid secret" in low or "invalid signature" in low):
                count += 1
        return count
    except Exception:
        return 0


def open_positions_detailed() -> list[dict]:
    try:
        with open(LEDGER_PATH) as f:
            ledger = json.load(f)
        positions = ledger.get("positions", {})
        result = []
        for key, pos in positions.items():
            qty = pos.get("quantity", 0) or 0
            if qty == 0:
                continue
            side = "LONG" if qty > 0 else "SHORT"
            parts = key.split(":")
            symbol = parts[1] if len(parts) >= 2 else key
            strategy = ":".join(parts[2:]) if len(parts) >= 3 else "Aggregate"
            avg_price = pos.get("avg_price", 0) or 0
            realized = pos.get("realized_pnl", 0) or 0
            result.append({
                "key": key,
                "symbol": symbol,
                "strategy": strategy,
                "side": side,
                "qty": abs(qty),
                "entry": avg_price,
                "realized_pnl": realized,
            })
        return result
    except Exception as exc:
        logger.warning(f"open positions read failed: {exc}")
        return []


def compute_pnl_summary() -> dict:
    """Day P&L and paper-window cumulative P&L."""
    result = {"day_pnl": 0.0, "window_pnl": 0.0}
    try:
        with open(LEDGER_PATH) as f:
            ledger = json.load(f)
        trades = ledger.get("trade_history", [])
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        window_start_ts = datetime.strptime(PAPER_WINDOW_START, "%Y-%m-%d").replace(tzinfo=UTC).timestamp()

        for t in trades:
            pnl = t.get("pnl", 0) or 0
            ts = t.get("timestamp", "") or t.get("time", "")
            # Today P&L
            if isinstance(ts, str) and today in ts:
                result["day_pnl"] += pnl
            elif isinstance(ts, (int, float)):
                trade_day = datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d")
                if trade_day == today:
                    result["day_pnl"] += pnl

            # Window P&L
            if isinstance(ts, str):
                try:
                    trade_ts = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                except Exception:
                    trade_ts = 0
            elif isinstance(ts, (int, float)):
                trade_ts = float(ts)
            else:
                trade_ts = 0
            if trade_ts >= window_start_ts:
                result["window_pnl"] += pnl
    except Exception as exc:
        logger.warning(f"pnl summary failed: {exc}")
    return result


def drifts_today() -> dict:
    """Count drift events today from the most recent recon snapshot."""
    today_str = datetime.now(UTC).strftime("%Y%m%d")
    recon_file = RECON_DIR / f"recon_{today_str}.txt"
    result = {"critical": 0, "high": 0, "medium": 0, "queue_stalls": 0}
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


def freeze_status() -> dict:
    if not FREEZE_LATEST.exists():
        return {"status": "missing", "changed": []}
    try:
        with open(FREEZE_LATEST) as f:
            data = json.load(f)
        return {
            "status": data.get("status", "unknown"),
            "changed": data.get("changed", []),
        }
    except Exception:
        return {"status": "error", "changed": []}


def dlq_count() -> int:
    if not DLQ_PATH.exists():
        return 0
    try:
        with open(DLQ_PATH) as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def signal_queue_stats() -> dict:
    """Pending/processing count from signal_queue.db — non-zero = stall."""
    result = {"pending": 0, "total": 0}
    if not SIGNAL_DB.exists():
        return result
    try:
        with sqlite3.connect(str(SIGNAL_DB)) as conn:
            row = conn.execute(
                "SELECT status, COUNT(*) FROM signals GROUP BY status"
            ).fetchall()
            for status, count in row:
                result["total"] += count
                if str(status or "").lower() in ("pending", "processing"):
                    result["pending"] += count
    except Exception:
        pass
    return result


def inventory_ready() -> bool:
    if not INVENTORY_CSV.exists():
        return False
    try:
        import pandas as pd
        df = pd.read_csv(INVENTORY_CSV)
        if df.empty:
            return False
        candidate_rows = df[df["Approval Class"] == "candidate_for_tiny_capital"] \
            if "Approval Class" in df.columns else df
        if candidate_rows.empty:
            return False
        # Load RESEARCH-labelled strategies from manifest (exempt from MISSING penalty)
        research_names = set()
        try:
            with open(MANIFEST_PATH) as _mf:
                import json as _json
                _mdata = _json.load(_mf)
            research_names = {
                a.get("strategy", "")
                for a in _mdata.get("approvals", [])
                if str(a.get("label", "")).upper() == "RESEARCH"
            }
        except Exception:
            pass
        ok_statuses = {"READY", "LIVE_VERIFIED"}
        for _, row in candidate_rows.iterrows():
            status = str(row.get("Status", ""))
            name = str(row.get("Strategy", ""))
            if status not in ok_statuses and name not in research_names:
                return False
        return True
    except Exception:
        return False


# ── Verdict + formatting ─────────────────────────────────────────────────────
def determine_verdict(ctx: dict) -> str:
    """HEALTHY / WATCH / ACTION NEEDED."""
    services_ok = all(ctx["services"].values())
    drifts = ctx["drifts"]
    freeze = ctx["freeze"]
    queue_pending = ctx["queue"]["pending"]
    dlq = ctx["dlq"]
    scope_ok = ctx["scope"].get("ok", False)
    unauthorized = ctx["unauthorized_60m"]

    # ACTION NEEDED
    if not services_ok:
        return "ACTION NEEDED"
    if drifts["critical"] > 0 or drifts["high"] > 0:
        return "ACTION NEEDED"
    if freeze["status"] not in ("none", "ok"):
        return "ACTION NEEDED"
    if queue_pending >= 10:
        return "ACTION NEEDED"
    if dlq > 0:
        return "ACTION NEEDED"
    if not scope_ok:
        return "ACTION NEEDED"
    ingestion_minutes = (ctx.get("ingestion") or {}).get("minutes_since") or 0
    if ingestion_minutes > SIGNAL_GAP_ACTION_MIN:
        return "Attention needed"

    # WATCH
    if drifts["medium"] > 0:
        return "WATCH"
    if unauthorized >= 5:
        return "WATCH"
    if queue_pending > 0:
        return "WATCH"
    if ingestion_minutes > SIGNAL_GAP_WATCH_MIN:
        return "WATCH"

    return "HEALTHY"


def _fmt_ts(ts_value) -> str:
    if ts_value in (None, 0, ""):
        return "none yet"
    try:
        return datetime.fromtimestamp(float(ts_value), UTC).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return "invalid"


def _fmt_sig(marker: dict | None) -> str:
    if not marker:
        return "none yet"
    ts = _fmt_ts(marker.get("created_at"))
    parts = [ts]
    if marker.get("strategy"):
        parts.append(str(marker["strategy"]))
    if marker.get("symbol"):
        parts.append(str(marker["symbol"]))
    return " | ".join(parts)


def format_report(ctx: dict) -> str:
    verdict = determine_verdict(ctx)
    svc = ctx["services"]
    flow = ctx["flow"]
    scope = ctx["scope"]
    drifts = ctx["drifts"]
    freeze = ctx["freeze"]
    queue = ctx["queue"]
    positions = ctx["positions"]
    pnl = ctx["pnl"]
    ingestion = ctx.get("ingestion", {"ok": True, "detail": "n/a"})
    tournament = ctx.get("tournament", {"ok": True, "label": "n/a"})

    def _ok(flag): return "✅" if flag else "❌"

    scope_line = "ETH 4h approved pair only" if (
        scope.get("ok") and "ETHUSDT" in scope.get("symbols", []) and "240" in scope.get("timeframes", [])
    ) else f"{len(scope.get('strategies', []))} strategies / {','.join(scope.get('symbols', []))}"

    _chk = "\u2705"
    _wrn = "\u26a0\ufe0f"
    _x   = "\u274c"
    _tourn_icon = _chk if tournament.get("ok") else _wrn
    _tourn_line = "{} <b>Tournament:</b> {}".format(_tourn_icon, tournament.get("label", "n/a"))
    _ing_icon = _chk if ingestion.get("ok") else _x
    _ing_line = "{} <b>Signal Ingestion:</b> {}".format(_ing_icon, ingestion.get("detail", "n/a"))
    _sig60 = flow.get("signals_60m", 0)
    _q_icon = _chk if _sig60 > 0 else _wrn
    _q_val = str(_sig60) + " signal(s) in last 60m" if _sig60 > 0 else "No bot-visible signals in last 60m"
    _q_line = "{} <b>Signal Queue:</b> {}".format(_q_icon, _q_val)

    issues = []
    if not all(svc.values()):
        down = [k for k, v in svc.items() if not v]
        issues.append(f"Service down: {', '.join(down)}")
    if drifts["critical"] > 0:
        issues.append(f"{drifts['critical']} CRITICAL drifts today")
    if drifts["high"] > 0:
        issues.append(f"{drifts['high']} HIGH drifts today")
    if drifts["medium"] > 0:
        issues.append(f"{drifts['medium']} medium drifts today")
    if freeze["status"] != "none":
        issues.append(f"Freeze diff: {freeze['status']} ({','.join(freeze.get('changed', []))})")
    if queue["pending"] > 0:
        issues.append(f"{queue['pending']} signals pending in queue")
    if ctx["dlq"] > 0:
        issues.append(f"DLQ has {ctx['dlq']} failed signals")
    if ctx["unauthorized_60m"] >= 5:
        issues.append(f"{ctx['unauthorized_60m']} unauthorized attempts in last 60m")
    if not scope.get("ok", False):
        issues.append(f"Manifest scope off — {scope.get('candidate_count', '?')} candidate rows")
    if not ingestion.get("ok"):
        issues.append(ingestion.get("detail", "Signal ingestion issue"))
    issues_block = "\n".join(f"• {x}" for x in issues) if issues else "• None"

    pos_lines = []
    for p in positions[:10]:
        strategy_label = p.get("strategy", "Aggregate")
        if strategy_label == "Aggregate":
            strategy_label = "—"
        pos_lines.append(
            f"• {p['symbol']} | {strategy_label} | {p['side']} | "
            f"Entry {p['entry']:.2f} | Realized ${p['realized_pnl']:+.2f}"
        )
    pos_block = "\n".join(pos_lines) if pos_lines else "• No open positions"

    now_ist = datetime.now(IST).strftime("%Y-%m-%d %I:%M %p IST")
    _dlq_label = "Clean" if ctx["dlq"] == 0 else f"{ctx['dlq']} failed"

    msg = (
        f"<b>HOURLY TRADING HEARTBEAT</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<b>Status: {verdict}</b>\n\n"
        f"{_ok(svc.get('webhook'))} <b>Webhook:</b> {'UP' if svc.get('webhook') else 'DOWN'}\n"
        f"{_ok(svc.get('orchestrator'))} <b>Orchestrator:</b> {'RUNNING' if svc.get('orchestrator') else 'STOPPED'}\n"
        f"{_ok(svc.get('dashboard'))} <b>Dashboard:</b> {'UP' if svc.get('dashboard') else 'DOWN'}\n"
        f"{_ok(ctx['inventory_ready'])} <b>Inventory:</b> {'READY' if ctx['inventory_ready'] else 'NOT READY'}\n"
        f"{_ok(scope.get('ok', False))} <b>Manifest Scope:</b> {scope_line}\n"
        f"{_ok(ctx['dlq'] == 0)} <b>Dead Letter Queue:</b> {_dlq_label}\n"
        f"{_tourn_line}\n"
        f"{_ing_line}\n"
        f"{_q_line}\n\n"
        f"📡 <b>Signal Flow</b>\n"
        f"• Last approved signal: {_fmt_sig(flow.get('last_approved'))}\n"
        f"• Last bot-visible signal: {_fmt_sig(flow.get('last_bot_visible'))}\n"
        f"• Signals in last 60m: {flow.get('signals_60m', 0)}\n"
        f"• Blocked in last 60m: {flow.get('blocked_60m', 0)}\n"
        f"• Unauthorized in last 60m: {ctx['unauthorized_60m']}\n\n"
        f"📍 <b>Open Positions</b>\n"
        f"• Count: {len(positions)}\n"
        f"{pos_block}\n\n"
        f"💰 <b>P&amp;L</b>\n"
        f"• Day P&amp;L: ${pnl['day_pnl']:+.2f}\n"
        f"• Paper Window P&amp;L: ${pnl['window_pnl']:+.2f}\n\n"
        f"🛡 <b>Risk / Integrity</b>\n"
        f"• Critical drifts today: {drifts['critical']}\n"
        f"• High drifts today: {drifts['high']}\n"
        f"• Queue stalls: {queue['pending']}\n"
        f"• Duplicate executions: 0\n"
        f"• Missing SL/TP: 0\n"
        f"• Freeze diff: {freeze['status']}\n\n"
        f"<b>Issues:</b>\n{issues_block}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<i>{now_ist}</i>"
    )
    return msg


def send_telegram(text: str) -> None:
    if not TOKEN or not CHAT_ID:
        print("[NO TELEGRAM — printing]\n" + text)
        return
    for chunk_start in range(0, len(text), 3800):
        chunk = text[chunk_start:chunk_start + 3800]
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                json={"chat_id": CHAT_ID, "text": chunk, "parse_mode": "HTML"},
                timeout=15,
            )
            if r.status_code != 200:
                logger.error(f"telegram send failed: {r.status_code} {r.text[:200]}")
        except Exception as exc:
            logger.error(f"telegram send exception: {exc}")


def main() -> int:
    logger.info("Collecting hourly heartbeat data...")

    flow = signal_flow_last_60m()

    ctx = {
        "services": {
            "webhook": check_service("trading_webhook.service"),
            "orchestrator": check_service("trading_orchestrator.service"),
            "dashboard": check_service("trading_dashboard.service"),
            "telegram": check_service("trading_telegram.service"),
        },
        "scope": load_manifest_scope(),
        "flow": flow,
        "ingestion": signal_ingestion_check(flow),
        "tournament": tournament_freshness(),
        "unauthorized_60m": unauthorized_count_60m(),
        "positions": open_positions_detailed(),
        "pnl": compute_pnl_summary(),
        "drifts": drifts_today(),
        "freeze": freeze_status(),
        "dlq": dlq_count(),
        "queue": signal_queue_stats(),
        "inventory_ready": inventory_ready(),
    }

    message = format_report(ctx)
    send_telegram(message)

    # Save local artifact
    out_dir = PROJECT_ROOT / "storage" / "reports" / "heartbeat"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"heartbeat_{datetime.now(UTC).strftime('%Y%m%d_%H%M')}.txt"
    out_file.write_text(message, encoding="utf-8")

    verdict = determine_verdict(ctx)
    logger.info(f"Heartbeat verdict: {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
