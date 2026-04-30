#!/usr/bin/env python3
"""
Wallace — Automated governance checker for backtest results.

Runs after every backtest and flags violations of the project governance gates.
Never needs to be asked — it speaks only when something is wrong.

Gates enforced:
  ❌ OOS trades < 100          (sample too small)
  ❌ OOS PF < 1.3              (edge insufficient)
  ❌ OOS PF < 1.0              (net losing OOS)
  ❌ MaxDD > 10%               (position-sizing risk)
  ❌ IS PF < 1.0               (losing in training window)
  ⚠️  IS/OOS ratio > 10x       (overfitting)
  ⚠️  Commission < 0.15%       (optimistic — rerun required)
  ❌ TV PF > 50                (infinite compounding artifact)

Usage:
    python scripts/wallace_check.py --csv backtesting/A_Leaderboard/mega_all_results.csv
    python scripts/wallace_check.py --discovery /home/ubuntu/Garima/storage/auto_alpha_discoveries.json
    python scripts/wallace_check.py --result '{"strategy":"X","oos_pf":1.2,"oos_trades":20}'
    python scripts/wallace_check.py --csv results.csv --telegram --claude
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))

# ─── Governance gates ──────────────────────────────────────────────────────────
# Source: Garima's corrections (2026-04-30); matches auto_discovery.py hard gates.
GATES = {
    "min_oos_trades":    100,    # hard gate — Garima confirmed
    "min_oos_pf":        1.3,    # raised from 1.05 by Garima
    "max_dd_pct":        10.0,   # hard gate
    "max_is_oos_ratio":  10.0,   # IS PF / OOS PF — beyond this = overfitting
    "commission_pct":    0.15,   # 0.04% fee + 0.10% slippage + 0.01% spread
    "min_is_pf":         1.0,    # IS must be profitable
    "tv_pf_max":         50.0,   # above this → infinite compounding artifact
}

# Garima's auto_discovery.py uses fees=0.0006 (0.06% one-way) — below governance
GARIMA_DISCOVERY_COMMISSION = 0.06   # one-way; governance needs 0.15% total


# ─── Result normaliser ─────────────────────────────────────────────────────────

_FIELD_MAP = {
    # Our backtest CSV columns → canonical names
    "Strategy":  "strategy",
    "Asset":     "asset",
    "OOS PF":    "oos_pf",
    "IS PF":     "is_pf",
    "OOS WR%":   "oos_wr_pct",
    "OOS Trades":"oos_trades",
    "ROI/day%":  "roi_day_pct",
    "Max DD%":   "max_dd_pct",
    "Verdict":   "verdict",
    # Garima discovery format
    "sharpe":          "sharpe",
    "dsr_tca":         "dsr_tca",
    "win_rate_pct":    "oos_wr_pct",
    "total_return_pct":"total_return_pct",
    "trades":          "total_trades",
}


def normalize_result(raw: dict) -> dict:
    """Map both CSV and Garima-discovery formats to canonical field names."""
    out = {}
    for src, dst in _FIELD_MAP.items():
        if src in raw:
            out[dst] = raw[src]
    for k, v in raw.items():
        if k not in _FIELD_MAP and k not in out:
            out[k] = v

    # Coerce numerics
    for f in ("oos_pf", "is_pf", "max_dd_pct", "oos_wr_pct", "roi_day_pct",
              "oos_trades", "total_trades", "sharpe", "commission_pct"):
        if f in out:
            try:
                out[f] = float(out[f])
            except (TypeError, ValueError):
                pass

    if "oos_trades" not in out and "total_trades" in out:
        out["oos_trades"] = out["total_trades"]

    return out


# ─── Core gate checker ─────────────────────────────────────────────────────────

def wallace_check(result: dict) -> list[str]:
    """
    Apply all governance gates.  Returns list of flag strings — empty = clean.
    Accepts raw dict (CSV row or discovery entry); normalises internally.
    """
    r = normalize_result(result)
    flags: list[str] = []

    oos_pf    = r.get("oos_pf")
    is_pf     = r.get("is_pf")
    oos_t     = r.get("oos_trades")
    max_dd    = r.get("max_dd_pct")
    commission= r.get("commission_pct")
    tv_pf     = r.get("tv_pf")

    # G1 — OOS trade count
    if oos_t is not None:
        if int(float(oos_t)) < GATES["min_oos_trades"]:
            flags.append(
                f"❌ OOS trades = {int(float(oos_t))} — minimum {GATES['min_oos_trades']}. "
                f"Sample too small; result is noise not signal."
            )

    # G2 — OOS PF (losing)
    if oos_pf is not None and float(oos_pf) < 1.0:
        flags.append(
            f"❌ OOS PF = {float(oos_pf):.3f} — strategy is net losing out-of-sample."
        )

    # G3 — OOS PF (gate threshold)
    elif oos_pf is not None and 1.0 <= float(oos_pf) < GATES["min_oos_pf"]:
        flags.append(
            f"❌ OOS PF = {float(oos_pf):.3f} — below gate minimum {GATES['min_oos_pf']}. "
            f"Edge insufficient for nomination."
        )

    # G4 — IS/OOS collapse
    if is_pf is not None and oos_pf is not None:
        try:
            opf = float(oos_pf)
            if opf > 0:
                ratio = float(is_pf) / opf
                if ratio > GATES["max_is_oos_ratio"]:
                    flags.append(
                        f"⚠️  IS/OOS collapse = {ratio:.1f}x "
                        f"(IS PF {float(is_pf):.2f} → OOS PF {opf:.2f}). "
                        f"Overfitting — do not nominate."
                    )
        except (ValueError, ZeroDivisionError):
            pass

    # G5 — MaxDD
    if max_dd is not None and abs(float(max_dd)) > GATES["max_dd_pct"]:
        flags.append(
            f"❌ MaxDD = {abs(float(max_dd)):.1f}% — gate maximum {GATES['max_dd_pct']}%. "
            f"Too large for $500 notional; position sizing breaks."
        )

    # G6 — IS must be profitable
    if is_pf is not None and float(is_pf) < GATES["min_is_pf"]:
        flags.append(
            f"❌ IS PF = {float(is_pf):.3f} — in-sample period is losing. "
            f"No edge even in the training window."
        )

    # G7 — Commission vs governance standard
    if commission is not None:
        try:
            if float(commission) < GATES["commission_pct"] - 0.01:
                flags.append(
                    f"⚠️  Commission = {float(commission):.2f}% — governance standard is "
                    f"{GATES['commission_pct']}% (0.04% fee + 0.10% slip + 0.01%). "
                    f"Results are optimistic. Rerun at 0.15% before any nomination."
                )
        except (TypeError, ValueError):
            pass

    # G8 — TV PF artifact
    if tv_pf is not None:
        try:
            if float(tv_pf) > GATES["tv_pf_max"]:
                flags.append(
                    f"❌ TV PF = {float(tv_pf):.0f} — unrealistically high. "
                    f"Likely infinite compounding artifact (TV compound reinvestment without fees). "
                    f"Disqualify; require Python fixed-notional backtest."
                )
        except (TypeError, ValueError):
            pass

    return flags


# ─── Claude deep analysis ──────────────────────────────────────────────────────

def deep_analysis(result: dict, flags: list[str]) -> str:
    """Call Claude API for pattern analysis beyond rule gates."""
    try:
        import anthropic
    except ImportError:
        return "(anthropic package not installed — pip install anthropic)"

    api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")
    if not api_key:
        return "(ANTHROPIC_API_KEY not set — skipping deep analysis)"

    r = normalize_result(result)
    prompt = f"""You are a quantitative trading governance reviewer.

Backtest result:
{json.dumps(r, indent=2, default=str)}

Rule violations already flagged by automated gate check:
{chr(10).join(flags) if flags else "None"}

Your task: identify 2-3 additional risk signals NOT already in the flags above.
Focus on:
1. Regime dependency — all profit concentrated in one market phase?
2. Asset correlation — behaves identically to an already-approved strategy?
3. Signal frequency — sustainable in live 4H market conditions?
4. Survivorship / look-ahead bias indicators visible in the metrics pattern
5. Whether OOS period overlapped with an anomalous market event (e.g. crash, rally)

Be specific. Flag real concerns only. Skip anything already in the rule violations.
Output: 2-3 bullet points, max 60 words each. No preamble."""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()
    except Exception as exc:
        return f"(Claude API error: {exc})"


# ─── Telegram notification ─────────────────────────────────────────────────────

def notify_telegram(strategy: str, asset: str, flags: list[str], analysis: str = "") -> None:
    """Send Wallace flags via the existing TelegramAlert system."""
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "tradingview_webhook_bot"))
        from alerts.telegram_alerts import TelegramAlert, AlertSeverity
        tg = TelegramAlert()

        has_critical = any("❌" in f for f in flags)
        severity = AlertSeverity.WARNING if has_critical else AlertSeverity.INFO
        flag_lines = "\n".join(f"  {f}" for f in flags)
        body = (
            f"<b>Strategy:</b> {strategy}\n"
            f"<b>Asset:</b> {asset}\n\n"
            f"<b>Flags ({len(flags)}):</b>\n{flag_lines}"
        )
        if analysis:
            body += f"\n\n<b>Deep Analysis:</b>\n{analysis}"

        tg.send(
            severity=severity,
            title="🔍 Wallace" + (" — CRITICAL" if has_critical else " — Warning"),
            message=body,
        )
    except Exception as exc:
        print(f"  [Wallace] Telegram notify failed: {exc}", file=sys.stderr)


# ─── Top-level runner ──────────────────────────────────────────────────────────

def run_wallace(
    result: dict,
    *,
    send_telegram: bool = True,
    use_claude: bool = False,
    quiet: bool = False,
) -> dict:
    """
    Run all Wallace checks on a single result dict.
    Returns {"strategy", "asset", "flags", "analysis", "clean", "critical"}.
    """
    r = normalize_result(result)
    strategy = r.get("strategy", "?")
    asset    = r.get("asset", "?")

    flags = wallace_check(r)
    analysis = ""
    has_critical = any("❌" in f for f in flags)

    if not quiet:
        if flags:
            print(f"\n🔍 WALLACE — {strategy} / {asset}:")
            for f in flags:
                print(f"    {f}")
        else:
            print(f"  ✅ {strategy} / {asset} — all gates pass")

    if flags and use_claude and has_critical:
        if not quiet:
            print(f"  📡 Requesting deep analysis from Claude...")
        analysis = deep_analysis(r, flags)
        if analysis and not quiet:
            print(f"\n📋 Deep Analysis:\n{analysis}")

    if flags and send_telegram:
        notify_telegram(strategy, asset, flags, analysis)

    return {
        "strategy": strategy,
        "asset": asset,
        "flags": flags,
        "analysis": analysis,
        "clean": len(flags) == 0,
        "critical": has_critical,
    }


# ─── Batch: our backtest CSV ───────────────────────────────────────────────────

def run_from_csv(
    path: str,
    *,
    commission_pct: Optional[float] = None,
    send_telegram: bool = False,
    use_claude: bool = False,
) -> list[dict]:
    """
    Process every row in a mega_all_results.csv.
    commission_pct: inject if not in CSV (e.g. 0.06 for backtest_mega_all.py).
    """
    import csv
    results = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            d = dict(row)
            if commission_pct is not None:
                d["commission_pct"] = commission_pct
            out = run_wallace(d, send_telegram=send_telegram, use_claude=use_claude, quiet=True)
            if not out["clean"]:
                print(f"\n🔍 {out['strategy']} / {out['asset']}:")
                for f in out["flags"]:
                    print(f"    {f}")
            results.append(out)

    _print_summary(results)
    return results


# ─── Batch: Garima's discovery JSON ───────────────────────────────────────────

def run_from_discovery(
    path: str,
    *,
    send_telegram: bool = False,
    use_claude: bool = False,
) -> list[dict]:
    """
    Process Garima's auto_alpha_discoveries.json.
    Injects GARIMA_DISCOVERY_COMMISSION for the commission gate.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    discoveries = data.get("all_discoveries", data) if isinstance(data, dict) else {}

    results = []
    for d in (discoveries.values() if isinstance(discoveries, dict) else discoveries):
        d_ext = {**d, "commission_pct": GARIMA_DISCOVERY_COMMISSION}
        out = run_wallace(d_ext, send_telegram=send_telegram, use_claude=use_claude, quiet=True)
        if not out["clean"]:
            print(f"\n🔍 {out['strategy']} / {out['asset']}:")
            for f in out["flags"]:
                print(f"    {f}")
        results.append(out)

    _print_summary(results)
    return results


def _print_summary(results: list[dict]) -> None:
    n = len(results)
    n_clean    = sum(1 for r in results if r["clean"])
    n_flagged  = n - n_clean
    n_critical = sum(1 for r in results if r["critical"])
    print(f"\n{'─'*60}")
    print(f"Wallace scan: {n} checked | ✅ {n_clean} clean | ⚠️ {n_flagged} flagged | ❌ {n_critical} critical")
    if n_critical:
        print("  Critical failures:")
        for r in results:
            if r["critical"]:
                print(f"    • {r['strategy']} / {r['asset']}")


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Wallace — automated backtest governance checker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv",       metavar="FILE", help="backtest_mega_all_results.csv")
    src.add_argument("--discovery", metavar="FILE", help="Garima auto_alpha_discoveries.json")
    src.add_argument("--result",    metavar="JSON", help="Single result as JSON string")
    parser.add_argument("--commission", type=float, default=None,
                        metavar="PCT", help="Inject commission %% (e.g. 0.06)")
    parser.add_argument("--telegram", action="store_true", help="Send flags to Telegram")
    parser.add_argument("--claude",   action="store_true",
                        help="Use Claude API for deep analysis on critical flags (needs ANTHROPIC_API_KEY)")
    args = parser.parse_args()

    if args.csv:
        run_from_csv(args.csv, commission_pct=args.commission,
                     send_telegram=args.telegram, use_claude=args.claude)
    elif args.discovery:
        run_from_discovery(args.discovery, send_telegram=args.telegram, use_claude=args.claude)
    elif args.result:
        result = json.loads(args.result)
        if args.commission:
            result["commission_pct"] = args.commission
        run_wallace(result, send_telegram=args.telegram, use_claude=args.claude)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
