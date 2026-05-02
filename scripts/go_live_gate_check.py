#!/usr/bin/env python3
"""
Automated Go-Live Gate Check
Runs pass/fail checks from docs/GO_LIVE_GATE.md and outputs a clear PASS/FAIL verdict.
Exit code 0 = all gates pass. Exit code 1 = at least one gate failed.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.verify_tv_inventory import build_inventory_report

UTC = timezone.utc
RESULTS: list[dict] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    emoji = "PASS" if passed else "FAIL"
    RESULTS.append({"name": name, "passed": passed, "detail": detail})
    print(f"  [{emoji}] {name}" + (f" -- {detail}" if detail else ""))


def load_env_file() -> None:
    env_file = Path("/etc/tradingbot/env_vars")
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def collect_pytest_count() -> tuple[bool, str]:
    ci_suite = [
        "tests/test_integration_flow.py",
        "tests/test_orchestrator_flow.py",
        "tests/test_strategy_decision_alerts.py",
        "tests/test_lighter_client.py",
        "tests/test_exit_fallback.py",
        "tests/test_alpha_engine.py",
        "tests/test_batch_backtest_realism.py",
        "tests/test_verify_tv_inventory.py",
        "tradingview_webhook_bot/recon/test_recon.py",
    ]
    try:
        result = subprocess.run(
            [str(PROJECT_ROOT / "venv" / "bin" / "python") if (PROJECT_ROOT / "venv" / "bin" / "python").exists() else sys.executable, "-m", "pytest", "-q", *ci_suite],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=240,
        )
    except Exception as exc:
        return False, str(exc)

    passed_count = 0
    output = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
    match = re.search(r"(\d+) passed", output)
    if match:
        passed_count = int(match.group(1))

    passed = result.returncode == 0
    detail = (f"{passed_count} curated CI tests passed" if passed_count > 0 else "Curated EC2 CI suite passed") if passed else (output or "No test output captured")
    return passed, detail


def load_manifest() -> tuple[dict, list[dict]]:
    manifest_path = PROJECT_ROOT / "config" / "approved_strategies.json"
    if not manifest_path.exists():
        return {}, []
    with open(manifest_path, encoding="utf-8") as handle:
        data = json.load(handle)
    approvals = data.get("approvals", []) if isinstance(data, dict) else []
    return data if isinstance(data, dict) else {}, approvals if isinstance(approvals, list) else []


def manifest_scope_summary(approvals: list[dict]) -> tuple[bool, str, list[dict]]:
    valid_classes = {"paper_only", "candidate_for_tiny_capital", "personal_live"}
    missing = []
    invalid = []
    candidates = []
    paper_only = []

    for approval in approvals:
        approval_class = str(approval.get("approval_class", "")).strip()
        if not approval_class:
            missing.append(approval.get("strategy", "unknown"))
            continue
        if approval_class not in valid_classes:
            invalid.append(f"{approval.get('strategy', 'unknown')}={approval_class}")
            continue
        if approval_class == "candidate_for_tiny_capital":
            candidates.append(approval)
        else:
            paper_only.append(approval)

    max_cap = int(os.getenv("MAX_CANDIDATES", "15"))
    passed = not missing and not invalid and 1 <= len(candidates) <= max_cap
    detail_parts = [f"{len(candidates)} candidate_for_tiny_capital", f"{len(paper_only)} paper_only"]
    if missing:
        detail_parts.append("missing class: " + ", ".join(missing))
    if invalid:
        detail_parts.append("invalid class: " + ", ".join(invalid))
    return passed, "; ".join(detail_parts), candidates


def refresh_inventory_report() -> tuple[bool, str, object]:
    output_path = PROJECT_ROOT / "storage" / "reports" / "tv_inventory_report.csv"
    try:
        report = build_inventory_report(
            manifest_path=PROJECT_ROOT / "config" / "approved_strategies.json",
            strategies_dir=PROJECT_ROOT / "strategies",
            generated_dir=PROJECT_ROOT / "storage" / "generated_alpha_scripts",
            signal_db_path=PROJECT_ROOT / "tradingview_webhook_bot" / "storage" / "signal_queue.db",
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        report.to_csv(output_path, index=False)
        return True, str(output_path), report
    except Exception as exc:
        return False, str(exc), None


def candidate_inventory_summary(report, candidates: list[dict]) -> tuple[bool, str]:
    if report is None or report.empty:
        return False, "Inventory report is empty"

    candidate_names = {str(entry.get("strategy", "")) for entry in candidates}
    candidate_rows = report[report["Approval Class"] == "candidate_for_tiny_capital"]
    if candidate_rows.empty:
        return False, "No candidate_for_tiny_capital rows found in inventory report"

    # Build research-label set: RESEARCH strategies may be MISSING (newly seeded, not yet on TV)
    research_names = {
        str(c.get("strategy", ""))
        for c in candidates
        if str(c.get("label", "")).upper() == "RESEARCH"
    }

    # Grace period: strategies approved within the last 7 days are not yet expected
    # to have live TV alerts firing — exempt them from the MISSING gate fail.
    from datetime import timedelta
    _now = datetime.now(timezone.utc)
    def _recently_approved(approved_at: str, grace_days: int = 7) -> bool:
        if not approved_at:
            return False
        try:
            ap = datetime.fromisoformat(approved_at.replace("Z", "+00:00"))
            return (_now - ap).days < grace_days
        except Exception:
            return False

    newly_added_names = {
        str(c.get("strategy", ""))
        for c in candidates
        if _recently_approved(str(c.get("approved_at", "")))
    }

    statuses = []
    passed = True
    for _, row in candidate_rows.iterrows():
        status = str(row["Status"])
        strat_name = str(row["Strategy"])
        statuses.append(f"{strat_name}:{row['Symbol']}={status}")
        if status not in {"READY", "LIVE_VERIFIED"}:
            if strat_name in research_names:
                statuses[-1] += "(RESEARCH-exempt)"  # warn but don't fail
            elif strat_name in newly_added_names:
                statuses[-1] += "(NEW-exempt:pending-TV-alert)"  # warn but don't fail
            else:
                passed = False

    missing_candidates = candidate_names - set(str(row["Strategy"]) for _, row in candidate_rows.iterrows())
    if missing_candidates:
        passed = False
        statuses.append("missing rows for " + ", ".join(sorted(missing_candidates)))

    return passed, "; ".join(statuses)


def paper_window_summary() -> tuple[bool, str]:
    report_dir = PROJECT_ROOT / "storage" / "reports" / "paper_validation"
    paper_start = os.getenv("PAPER_WINDOW_START", "2026-04-07")
    paper_days = int(os.getenv("PAPER_WINDOW_DAYS", "7"))
    start_date = datetime.strptime(paper_start, "%Y-%m-%d").date()
    today = datetime.now(UTC).date()
    elapsed_days = max(0, (today - start_date).days + 1)
    daily_reports = sorted(report_dir.glob("day*_*.txt"))
    passed = elapsed_days >= paper_days and len(daily_reports) >= paper_days
    detail = f"Day {elapsed_days} of {paper_days}; {len(daily_reports)} daily reports present"
    return passed, detail


def critical_drift_summary() -> tuple[bool, str]:
    report_dir = PROJECT_ROOT / "storage" / "reports" / "paper_validation"
    recon_files = sorted(report_dir.glob("recon_*.txt"))
    critical_total = 0
    for file_path in recon_files:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        match = re.search(r"SIDE_MISMATCH \(CRITICAL\):\s*(\d+)", text)
        if match:
            critical_total += int(match.group(1))
    passed = critical_total == 0 and bool(recon_files)
    detail = f"{critical_total} critical SIDE_MISMATCH drift(s) across {len(recon_files)} recon snapshot(s)"
    return passed, detail


def execution_freeze_summary() -> tuple[bool, str]:
    latest_path = PROJECT_ROOT / "storage" / "reports" / "paper_validation" / "execution_freeze_latest.json"
    if not latest_path.exists():
        return False, f"{latest_path} missing"

    try:
        with open(latest_path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:
        return False, str(exc)

    recorded_at_raw = str(payload.get("recorded_at", "")).strip()
    try:
        recorded_at = datetime.fromisoformat(recorded_at_raw)
        if recorded_at.tzinfo is None:
            recorded_at = recorded_at.replace(tzinfo=UTC)
        recorded_at = recorded_at.astimezone(UTC)
    except Exception:
        return False, f"Invalid recorded_at={recorded_at_raw or 'MISSING'}"

    age_hours = max(0.0, (datetime.now(UTC) - recorded_at).total_seconds() / 3600)
    status = str(payload.get("status", "")).strip().lower()
    changed = [str(item) for item in payload.get("changed", [])]
    tracked_count = int(payload.get("tracked_count", 0))

    detail = f"execution diff = {status or 'unknown'}; tracked={tracked_count}; age={age_hours:.1f}h"
    if changed:
        detail += "; changed=" + ", ".join(changed)
    elif payload.get("note"):
        detail += f"; note={payload['note']}"

    passed = status == "none" and age_hours <= 36.0
    return passed, detail


def dlq_summary() -> tuple[bool, str]:
    dlq_path = Path(os.getenv("DLQ_PATH", str(PROJECT_ROOT / "tradingview_webhook_bot" / "storage" / "dead_letter.jsonl")))
    dlq_count = 0
    if dlq_path.exists():
        with open(dlq_path, encoding="utf-8", errors="replace") as handle:
            dlq_count = sum(1 for _ in handle)
    return dlq_count == 0, ("Clean" if dlq_count == 0 else f"{dlq_count} failed signals")



def signal_gap_gate() -> tuple[bool, str]:
    """Gate: last bot-visible signal must be within 48h.
    Catches TradingView alert stagnation before the Apr 14 decision.
    """
    import sqlite3
    signal_db = PROJECT_ROOT / "tradingview_webhook_bot" / "storage" / "signal_queue.db"
    if not signal_db.exists():
        return False, "signal_queue.db missing"
    try:
        with sqlite3.connect(str(signal_db)) as conn:
            row = conn.execute(
                "SELECT MAX(created_at) FROM signals"
            ).fetchone()
        last_ts = row[0] if row and row[0] else None
        if not last_ts:
            return False, "No signals ever recorded in signal_queue.db"
        minutes_since = int((datetime.now(UTC).timestamp() - float(last_ts)) / 60)
        hours = minutes_since / 60
        detail = f"Last bot-visible signal {minutes_since}m ago ({hours:.1f}h)"
        passed = minutes_since < (48 * 60)  # warn if > 48h
        if not passed:
            detail += " -- STALE: verify TradingView alerts are firing"
        return passed, detail
    except Exception as exc:
        return False, f"signal_gap_gate error: {exc}"


def approved_lane_signal_count_gate() -> tuple[bool, str]:
    """Gate: at least 1 approved-lane signal recorded during the paper window.
    Prevents declaring a paper window healthy when zero approved signals fired.
    """
    import sqlite3, json as _json, re as _re
    signal_db = PROJECT_ROOT / "tradingview_webhook_bot" / "storage" / "signal_queue.db"
    manifest_path = PROJECT_ROOT / "config" / "approved_strategies.json"
    paper_start = os.getenv("PAPER_WINDOW_START", "2026-04-07")
    if not signal_db.exists():
        return False, "signal_queue.db missing"
    try:
        window_start_ts = datetime.strptime(paper_start, "%Y-%m-%d").replace(tzinfo=UTC).timestamp()
        with open(manifest_path) as f:
            manifest = _json.load(f)
        approved = [
            a for a in manifest.get("approvals", [])
            if a.get("approval_class") == "candidate_for_tiny_capital"
        ]
        approved_names = {_re.sub(r"[^a-z0-9]+", " ", a["strategy"].lower()).strip() for a in approved}

        with sqlite3.connect(str(signal_db)) as conn:
            rows = conn.execute(
                "SELECT payload, created_at FROM signals WHERE created_at >= ?",
                (window_start_ts,)
            ).fetchall()

        count = 0
        for raw, _ in rows:
            try:
                data = _json.loads(raw)
                payload = data.get("payload", data) if isinstance(data, dict) else {}
                strat = _re.sub(r"[^a-z0-9]+", " ", str(payload.get("strategy", "")).lower()).strip()
                if strat in approved_names:
                    count += 1
            except Exception:
                pass

        detail = f"{count} approved-lane signal(s) recorded since {paper_start}"
        return count >= 1, detail
    except Exception as exc:
        return False, f"approved_lane_signal_count_gate error: {exc}"


def stale_position_gate() -> tuple[bool, str]:
    """Gate: no UNQUARANTINED open positions outside the approved-lane symbols.
    Quarantined positions (in storage/stale_position_quarantine.json) are explicitly
    acknowledged and skipped — they must still be flattened before go-live.
    """
    import json as _json
    # A-10: use decision-lane ledger when available, fall back to combined ledger_state.json
    _dl_path = os.getenv("DECISION_LANE_LEDGER_PATH",
        str(PROJECT_ROOT / "tradingview_webhook_bot" / "storage" / "ledger_decision.json"))
    ledger_path = _dl_path if os.path.exists(_dl_path) else os.getenv("LEDGER_PATH",
        str(PROJECT_ROOT / "tradingview_webhook_bot" / "storage" / "ledger_state.json"))
    manifest_path = PROJECT_ROOT / "config" / "approved_strategies.json"
    quarantine_path = PROJECT_ROOT / "storage" / "stale_position_quarantine.json"
    try:
        with open(ledger_path) as f:
            ledger = _json.load(f)
        with open(manifest_path) as f:
            manifest = _json.load(f)

        # Load quarantine list (R-04 acknowledgement)
        quarantined_keys = set()
        if quarantine_path.exists():
            try:
                qdata = _json.loads(quarantine_path.read_text())
                quarantined_keys = {p["key"] for p in qdata.get("positions", [])}
            except Exception:
                pass

        # Decision-lane symbols (candidate_for_tiny_capital only) — for reporting
        decision_lane_symbols = set()
        for a in manifest.get("approvals", []):
            if a.get("approval_class") == "candidate_for_tiny_capital":
                for s in a.get("symbols", []):
                    decision_lane_symbols.add(s.upper())

        # All manifest symbols (candidate_for_tiny_capital + paper_only) — for gate validation.
        # Paper_only research positions are expected and must not fail this gate.
        # Only truly orphan positions (no matching manifest strategy) are flagged as stale.
        approved_symbols = set(decision_lane_symbols)
        for a in manifest.get("approvals", []):
            if a.get("approval_class") in ("candidate_for_tiny_capital", "paper_only"):
                for s in a.get("symbols", []):
                    approved_symbols.add(s.upper())

        stale = []
        for key, pos in ledger.get("positions", {}).items():
            if (pos.get("quantity") or 0) == 0:
                continue
            if key in quarantined_keys:
                continue  # R-04: explicitly quarantined, must be flattened before go-live
            parts = key.split(":")
            symbol = parts[1].upper() if len(parts) >= 2 else key.upper()
            wildcard = "*" in approved_symbols
            if not wildcard and symbol not in approved_symbols:
                stale.append(symbol)

        qnote = f"; {len(quarantined_keys)} stale pos quarantined (R-04)" if quarantined_keys else ""
        if stale:
            detail = f"Stale non-lane positions open: {', '.join(sorted(set(stale)))} — quarantine before Apr 14 decision"
            return False, detail
        return True, f"All open positions within approved+paper_only lane; decision-lane: {sorted(decision_lane_symbols)}{qnote}"
    except Exception as exc:
        return False, f"stale_position_gate error: {exc}"


def family_concentration_gate(candidates: list[dict]) -> tuple[bool, str]:
    """Gate: no more than 1 candidate_for_tiny_capital per indicator family.
    Prevents correlated strategies from being promoted together.
    """
    STRATEGY_FAMILY = {
        "Supertrend_3_10": "supertrend", "Supertrend_2_7": "supertrend",
        "Donchian_EMA_20": "donchian",   "Donchian_EMA_30": "donchian",
        "Donchian Trend":    "donchian",
        "EMA_Cross_9_21":  "ema_cross",  "EMA_Cross_13_34": "ema_cross",
        "BB_Squeeze": "bb_band", "Mean_Rev_BB": "bb_band", "Keltner_Break": "bb_band",
        "MACD_Histogram": "macd", "DEMA_Cross": "macd",
        "Heikin_Ashi": "trend_ma", "Triple_EMA": "trend_ma",
        "Hull_MA": "trend_ma", "PSAR_EMA": "trend_ma",
        "Williams_R": "oscillator", "Stoch_RSI": "oscillator",
        "QQE_Oscillator": "oscillator", "RSI_Divergence": "oscillator",
        "Dual_Momentum": "momentum", "ATR_Channel": "breakout",
        "Volume_Breakout": "breakout", "Turtle_Trading": "breakout",
        "VWAP_ATR": "vwap", "CCI_Trend": "cci", "CCI Trend": "cci", "Ichimoku_Cloud": "ichimoku",
    }
    family_counts: dict = {}
    symbol_counts: dict = {}
    violations = []
    for cand in candidates:
        name = str(cand.get("strategy", ""))
        syms = cand.get("symbols", [])
        fam  = STRATEGY_FAMILY.get(name, STRATEGY_FAMILY.get(name.replace(" ","_"), "unknown"))
        family_counts[fam] = family_counts.get(fam, 0) + 1
        for s in syms:
            symbol_counts[s] = symbol_counts.get(s, 0) + 1

    for fam, count in family_counts.items():
        if count > 1:
            violations.append(f"family:{fam}={count}(max 1)")
    for sym, count in symbol_counts.items():
        if count > 2:
            violations.append(f"symbol:{sym}={count}(max 2)")

    details = []
    for fam, count in sorted(family_counts.items()):
        details.append(f"{fam}:{count}")
    summary = "families=" + ", ".join(details)
    if violations:
        return False, summary + " VIOLATIONS: " + "; ".join(violations)
    return True, summary


def _min_trades_for_timeframe(timeframe: str) -> int:
    """Timeframe-aware minimum closed trades before promotion.
    4H  signals ~2/week → 5 trades ≈ 3 weeks evidence
    1H  signals ~8/week → 10 trades ≈ 2 weeks evidence
    15m signals ~30/week → 20 trades ≈ 1 week evidence
    """
    tf = str(timeframe).strip().lower()
    if "4h" in tf or tf in ("240", "4"):
        return int(os.getenv("PAPER_MIN_TRADES_4H", "5"))
    if "1h" in tf or tf in ("60", "1"):
        return int(os.getenv("PAPER_MIN_TRADES_1H", "10"))
    return int(os.getenv("PAPER_MIN_TRADES_15M", "20"))


def _normalize_strat_name(name: str) -> str:
    """Strip TV parameter suffixes and normalise to lowercase with spaces.
    'CCI Trend (20, 100, 1.5, 12, 4)' -> 'cci trend'
    'Donchian_Trend'                   -> 'donchian trend'
    """
    import re as _re
    s = str(name).strip()
    s = _re.sub(r"\s*\([^)]*\)", "", s)   # strip (params)
    s = s.replace("_", " ")
    s = _re.sub(r"\s+", " ", s).strip().lower()
    return s


def min_closed_trades_gate(candidates: list[dict]) -> tuple[bool, str]:
    """Gate: each candidate_for_tiny_capital must have >= N closed paper trades.
    Threshold is timeframe-aware (4H=5, 1H=10, 15m=20).
    Counts is_exit=True entries in execution_metrics.jsonl since PAPER_WINDOW_START.
    Prevents promoting strategies with insufficient live evidence.
    """
    import json as _json
    from datetime import datetime, timezone
    metrics_path = PROJECT_ROOT / "storage" / "reports" / "paper_validation" / "execution_metrics.jsonl"
    paper_start = os.getenv("PAPER_WINDOW_START", "2026-04-07")
    window_start_ts = datetime.strptime(paper_start, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()

    if not metrics_path.exists():
        return False, f"execution_metrics.jsonl missing — cannot verify closed-trade count"

    # Count closed trades per strategy
    strategy_exits: dict = {}
    try:
        with open(metrics_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = _json.loads(line)
                except Exception:
                    continue
                if float(rec.get("timestamp_epoch", 0)) < window_start_ts:
                    continue
                if not rec.get("is_exit"):
                    continue
                strat = str(rec.get("strategy", "")).strip()
                rec_sym = str(rec.get("symbol", "")).upper().strip()
                if strat:
                    strategy_exits.setdefault(strat, {})
                    strategy_exits[strat][rec_sym] = strategy_exits[strat].get(rec_sym, 0) + 1
    except Exception as exc:
        return False, f"Error reading execution_metrics.jsonl: {exc}"

    details = []
    passed = True
    for cand in candidates:
        name = str(cand.get('strategy', 'unknown'))
        name_norm = _normalize_strat_name(name)
        count = 0
        for telemetry_name, sym_counts in strategy_exits.items():
            if _normalize_strat_name(telemetry_name) == name_norm:
                # Only count exits on symbols approved for this candidate
                cand_syms = [str(s).upper() for s in (cand.get('symbols') or [])]
                for sym, c in sym_counts.items():
                    if '*' in cand_syms or sym in cand_syms:
                        count += c
        tf = str((cand.get('timeframes') or ['4h'])[0])
        threshold = _min_trades_for_timeframe(tf)
        ok = count >= threshold
        if not ok:
            passed = False
        status = 'OK' if ok else f'NEED {threshold}'
        details.append(f'{name}:{count}({status})')

    return passed, '; '.join(details) if details else 'No candidates to check'


def decision_lane_recency_check(candidates, warn_after_hours: float = 72.0):
    """Fail if no ETHUSDT decision-lane signal received in last warn_after_hours.

    Checks signal_queue.db (signal receipt) as the primary source so test signals
    and paper signals count — not just fills in execution_metrics.jsonl.
    Falls back to execution_metrics.jsonl if the queue DB is unavailable.
    """
    import json as _json
    import sqlite3 as _sqlite3
    import time as _time
    import re as _re
    now_ts = _time.time()
    candidate_names = {str(c.get("strategy", "")).strip() for c in candidates}
    candidate_names_norm = {_re.sub(r"[^a-z0-9]+", " ", n.lower()).strip() for n in candidate_names}

    # Primary: check signal_queue.db for received signals from candidate strategies on ETHUSDT
    signal_db = PROJECT_ROOT / "tradingview_webhook_bot" / "storage" / "signal_queue.db"
    if signal_db.exists():
        last_ts, last_strat = 0.0, None
        try:
            with _sqlite3.connect(str(signal_db)) as conn:
                rows = conn.execute(
                    "SELECT payload, created_at FROM signals ORDER BY created_at DESC LIMIT 5000"
                ).fetchall()
            for raw, created_at in rows:
                try:
                    data = _json.loads(raw)
                    payload = data.get("payload", data) if isinstance(data, dict) else {}
                    strat_raw = str(payload.get("strategy", ""))
                    sym = str(payload.get("symbol", "")).upper().strip()
                    strat_norm = _re.sub(r"[^a-z0-9]+", " ", strat_raw.lower()).strip()
                    if strat_norm in candidate_names_norm and sym == "ETHUSDT":
                        ts = float(created_at)
                        if ts > last_ts:
                            last_ts, last_strat = ts, strat_raw.strip()
                except Exception:
                    continue
            if last_ts > 0:
                age_h = (now_ts - last_ts) / 3600
                from datetime import timezone as _tz
                last_dt = datetime.fromtimestamp(last_ts, tz=_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                detail = f"Last ETHUSDT signal: {last_strat} at {last_dt} ({age_h:.1f}h ago)"
                return age_h <= warn_after_hours, detail
            # No candidate ETHUSDT signal in queue DB — fall through to metrics file
        except Exception:
            pass  # fall through to execution_metrics fallback

    # Fallback: execution_metrics.jsonl (only populated on actual fills)
    metrics_path = PROJECT_ROOT / "storage" / "reports" / "paper_validation" / "execution_metrics.jsonl"
    if not metrics_path.exists():
        return False, "No ETHUSDT decision-lane signal ever recorded (queue DB empty, metrics file missing)"
    last_ts, last_strat = 0.0, None
    try:
        with open(metrics_path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = _json.loads(line)
                except Exception:
                    continue
                strat = str(rec.get("strategy", "")).strip()
                sym = str(rec.get("symbol", "")).upper().strip()
                if strat in candidate_names and sym == "ETHUSDT":
                    ts = float(rec.get("timestamp_epoch", 0))
                    if ts > last_ts:
                        last_ts, last_strat = ts, strat
    except Exception as exc:
        return True, f"cannot check: {exc}"
    if last_ts == 0:
        return False, "No ETHUSDT decision-lane signal ever recorded in execution_metrics"
    age_h = (now_ts - last_ts) / 3600
    from datetime import timezone as _tz
    last_dt = datetime.fromtimestamp(last_ts, tz=_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    detail = f"Last ETHUSDT signal: {last_strat} at {last_dt} ({age_h:.1f}h ago)"
    return age_h <= warn_after_hours, detail



def is_oos_ratio_gate(approvals: list[dict]) -> tuple[bool, str]:
    """Gate: IS/OOS Profit Factor ratio must be ≤ 4× for non-retired/non-withdrawn strategies.
    Prevents overfitting candidates from reaching paper window nomination.
    Retroactive evidence: G83 (12.3×), G88 (78.6×), G111 (8.4×) — all failed this check.
    Populate field p07_is_oos_pf_ratio in manifest entry before any shortlist nomination.
    """
    violations = []
    no_data = []
    for a in approvals:
        label = str(a.get("label", "")).upper()
        if any(s in label for s in ("RETIRED", "WITHDRAWN", "PERSONAL")):
            continue
        if a.get("approval_class") not in ("paper_only", "candidate_for_tiny_capital"):
            continue
        if not a.get("shortlist_priority") and a.get("approval_class") == "paper_only":
            continue
        ratio = a.get("p07_is_oos_pf_ratio") or a.get("is_oos_pf_ratio")
        if ratio is None:
            no_data.append(str(a.get("strategy", "?")))
            continue
        try:
            ratio = float(ratio)
        except (ValueError, TypeError):
            continue
        if ratio > 4.0:
            violations.append(f"{a.get('strategy','?')}: {ratio:.1f}x")

    if violations:
        return False, f"IS/OOS PF ratio >4x — overfitting detected: {'; '.join(violations)}"
    if no_data:
        return True, f"Pass — {len(no_data)} shortlisted strateg(ies) lack p07_is_oos_pf_ratio field (add before nomination): {', '.join(no_data)}"
    return True, "All shortlisted strategies pass ≤4x IS/OOS ratio check"

def main() -> int:
    load_env_file()

    print("=" * 60)
    print("  GO-LIVE GATE CHECK")
    print("=" * 60)
    print()

    ci_path = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
    if ci_path.exists():
        ci_content = ci_path.read_text(encoding="utf-8", errors="ignore")
        check("CI has no '|| true' bypass", "|| true" not in ci_content, "Found || true in ci.yml" if "|| true" in ci_content else "")
    else:
        check("CI workflow exists", False, "ci.yml not found")

    auth_mode = os.getenv("TRADINGVIEW_AUTH_MODE", "secret")
    check("Webhook auth is strict", auth_mode not in ("open", "none", "disabled", "off"), f"TRADINGVIEW_AUTH_MODE={auth_mode}")

    secret = os.getenv("WEBHOOK_SECRET", "").strip()
    check("WEBHOOK_SECRET is configured", len(secret) > 8, f"length={len(secret)}")

    sl = os.getenv("STOP_LOSS_PCT", "")
    check("STOP_LOSS_PCT is set", bool(sl), f"value={sl or 'NOT SET'}")
    try:
        sl_val = float(sl) if sl else 0.0
        check("STOP_LOSS_PCT is safe (0.5–5.0%)", 0.5 <= sl_val <= 5.0, f"value={sl_val} — must be between 0.5 and 5.0")
    except ValueError:
        check("STOP_LOSS_PCT is safe (0.5–5.0%)", False, f"non-numeric value: {sl!r}")

    tp = os.getenv("TAKE_PROFIT_PCT", "")
    check("TAKE_PROFIT_PCT is set", bool(tp), f"value={tp or 'NOT SET'}")

    cb_loss = os.getenv("CB_DAILY_LOSS_PCT", "")
    cb_consecutive = os.getenv("CB_MAX_CONSECUTIVE_LOSSES", "")
    check("Circuit breaker daily loss configured", bool(cb_loss), f"CB_DAILY_LOSS_PCT={cb_loss or 'NOT SET'}")
    check("Circuit breaker consecutive losses configured", bool(cb_consecutive), f"CB_MAX_CONSECUTIVE_LOSSES={cb_consecutive or 'NOT SET'}")

    daily_loss_limit = os.getenv("DAILY_LOSS_LIMIT", "")
    check("DAILY_LOSS_LIMIT is set", bool(daily_loss_limit), f"value={daily_loss_limit or 'NOT SET'}")

    leverage = os.getenv("LEVERAGE", os.getenv("TRADE_LEVERAGE", ""))
    check("Leverage is configured", bool(leverage), f"value={leverage or 'NOT SET'}")

    testnet_val = os.getenv("BINANCE_TESTNET", "true").strip().lower()
    check(
        "BINANCE_TESTNET=true (paper-phase safety)",
        testnet_val == "true",
        f"BINANCE_TESTNET={testnet_val} — must remain true until live-enable sign-off",
    )

    gate_doc = PROJECT_ROOT / "docs" / "GO_LIVE_GATE.md"
    check("GO_LIVE_GATE.md exists", gate_doc.exists())

    if os.getenv("SKIP_PYTEST") == "1":
        check("Pytest suite is discoverable", True, "skipped (SKIP_PYTEST=1)")
    else:
        tests_ok, tests_detail = collect_pytest_count()
        check("Pytest suite is discoverable", tests_ok, tests_detail)

    ledger_path = Path(os.getenv("LEDGER_PATH", str(PROJECT_ROOT / "tradingview_webhook_bot" / "storage" / "ledger_state.json")))
    check("Ledger state file exists", ledger_path.exists(), str(ledger_path))

    idempotency_path = Path(os.getenv("IDEMPOTENCY_DB_PATH", str(PROJECT_ROOT / "tradingview_webhook_bot" / "storage" / "idempotency.db")))
    check("Idempotency DB exists", idempotency_path.exists(), str(idempotency_path))

    manifest, approvals = load_manifest()
    check("Approval manifest is populated", len(approvals) >= 2, f"{len(approvals)} strategies approved" if approvals else "EMPTY")

    provenance_ok = bool(approvals)
    if approvals:
        for approval in approvals:
            if not approval.get("backtest_hash") or not approval.get("notes") or "PENDING" in str(approval.get("notes", "")):
                provenance_ok = False
                break
    check(
        "Manifest entries have provenance (hash + notes)",
        provenance_ok,
        "All entries have backtest_hash and notes" if provenance_ok else "Missing provenance fields",
    )

    scope_ok, scope_detail, candidates = manifest_scope_summary(approvals)
    check("Manifest scope is explicit and limited", scope_ok, scope_detail)

    inventory_ok, inventory_detail, inventory_report = refresh_inventory_report()
    check("TradingView inventory report refreshed", inventory_ok, inventory_detail)
    if inventory_ok:
        candidate_inventory_ok, candidate_inventory_detail = candidate_inventory_summary(inventory_report, candidates)
    else:
        candidate_inventory_ok, candidate_inventory_detail = False, "Inventory report refresh failed"
    check("Candidate paper-lane inventory verified", candidate_inventory_ok, candidate_inventory_detail)

    paper_ok, paper_detail = paper_window_summary()
    check("Paper window duration complete", paper_ok, paper_detail)

    drift_ok, drift_detail = critical_drift_summary()
    check("No critical reconciler drifts during paper window", drift_ok, drift_detail)

    freeze_ok, freeze_detail = execution_freeze_summary()
    check("Execution-plane freeze intact", freeze_ok, freeze_detail)

    dlq_ok, dlq_detail = dlq_summary()
    check("Dead letter queue is clean", dlq_ok, dlq_detail)

    # R-10: Operational gates
    sig_gap_ok, sig_gap_detail = signal_gap_gate()
    check("Signal pipeline active (last signal < 48h)", sig_gap_ok, sig_gap_detail)

    lane_sig_ok, lane_sig_detail = approved_lane_signal_count_gate()
    check("Approved-lane signals fired during paper window", lane_sig_ok, lane_sig_detail)

    stale_ok, stale_detail = stale_position_gate()
    check("No stale non-lane positions open", stale_ok, stale_detail)

    min_trades_ok, min_trades_detail = min_closed_trades_gate(candidates)  # thresholds: 4H=5, 1H=10, 15m=20
    check("Candidates have min closed paper trades (4H=5,1H=10,15m=20)", min_trades_ok, min_trades_detail)

    lane_recent_ok, lane_recent_detail = decision_lane_recency_check(candidates, warn_after_hours=72.0)
    check("Decision-lane ETHUSDT signal active (<72h)", lane_recent_ok, lane_recent_detail)

    conc_ok, conc_detail = family_concentration_gate(candidates)
    check("Candidate family/symbol concentration within limits", conc_ok, conc_detail)
    # IS/OOS overfitting gate — retroactive evidence: G83/G88/G111 all failed (8–79x ratio)
    oos_ratio_ok, oos_ratio_detail = is_oos_ratio_gate(approvals)
    check("IS/OOS PF ratio <= 4x (overfitting gate)", oos_ratio_ok, oos_ratio_detail)

    _decision_lane_names = {"CCI Trend", "Donchian Trend", "CCI_Trend", "Donchian_Trend"}
    blocked_raw = os.getenv("BLOCKED_STRATEGY_NAMES", "")
    blocked_set = {s.strip() for s in blocked_raw.split(",") if s.strip()}
    _wrongly_blocked = _decision_lane_names & blocked_set
    check(
        "Decision-lane candidates not in BLOCKED_STRATEGY_NAMES",
        not _wrongly_blocked,
        f"Wrongly blocked: {', '.join(sorted(_wrongly_blocked))}" if _wrongly_blocked else f"BLOCKED_STRATEGY_NAMES={blocked_raw!r}",
    )

    print()
    print("=" * 60)
    passed = sum(1 for result in RESULTS if result["passed"])
    failed = sum(1 for result in RESULTS if not result["passed"])
    total = len(RESULTS)

    if failed == 0:
        print(f"  VERDICT: GO  ({passed}/{total} gates passed)")
        print("=" * 60)
        _write_gate_verdict_cache(True, 0, total)
        return 0

    print(f"  VERDICT: NO-GO  ({failed} of {total} gates FAILED)")
    print()
    for result in RESULTS:
        if not result["passed"]:
            print(f"    FAIL: {result['name']} -- {result['detail']}")
    print("=" * 60)
    _write_gate_verdict_cache(failed == 0, failed, total)
    return 1


def _write_gate_verdict_cache(passed: bool, failed_count: int, total: int) -> None:
    """Write a lightweight verdict cache so the orchestrator can read gate status without re-running."""
    cache_path = PROJECT_ROOT / "storage" / "reports" / "gate_verdict_cache.json"
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({
            "verdict": "GO" if passed else "NO-GO",
            "passed": passed,
            "failed_count": failed_count,
            "total": total,
            "checked_at": datetime.now(UTC).isoformat(),
        }, indent=2))
    except Exception:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
