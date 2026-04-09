import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_CLASS_REASON = "Defaulted to paper_only until explicitly promoted after paper validation."


def load_manifest(path: Path) -> dict:
    if path.exists():
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
            if isinstance(data, dict):
                data.setdefault("approvals", [])
                return data
    return {"version": 1, "updated_at": "", "approvals": []}


def normalize_list(value: str) -> list[str]:
    if not value:
        return ["*"]
    return [item.strip() for item in value.split(",") if item.strip()]


def upsert_approval(manifest: dict, approval: dict):
    approvals = manifest.setdefault("approvals", [])
    match_key = (
        approval["strategy"].strip().lower(),
        approval["exchange"].strip().lower(),
        tuple(sorted(symbol.upper() for symbol in approval["symbols"])),
        tuple(sorted(timeframe.lower() for timeframe in approval["timeframes"])),
    )

    for index, existing in enumerate(approvals):
        existing_key = (
            str(existing.get("strategy", "")).strip().lower(),
            str(existing.get("exchange", "")).strip().lower(),
            tuple(sorted(str(symbol).upper() for symbol in existing.get("symbols", ["*"]))),
            tuple(sorted(str(timeframe).lower() for timeframe in existing.get("timeframes", ["*"]))),
        )
        if existing_key == match_key:
            approvals[index] = approval
            return "updated"

    approvals.append(approval)
    return "created"


def main():
    parser = argparse.ArgumentParser(description="Approve a strategy for live execution.")
    parser.add_argument("--manifest", default="config/approved_strategies.json")
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--exchange", default="binance")
    parser.add_argument("--symbols", default="*")
    parser.add_argument("--timeframes", default="*")
    parser.add_argument("--operator", required=True)
    parser.add_argument("--backtest-hash", required=True)
    parser.add_argument("--label", default="APPROVED_MANIFEST")
    parser.add_argument("--notes", default="")
    parser.add_argument(
        "--approval-class",
        default="paper_only",
        choices=["paper_only", "candidate_for_tiny_capital"],
    )
    parser.add_argument("--class-reason", default=DEFAULT_CLASS_REASON)
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    manifest = load_manifest(manifest_path)

    approval = {
        "strategy": args.strategy,
        "exchange": args.exchange.lower(),
        "symbols": [symbol.upper() for symbol in normalize_list(args.symbols)],
        "timeframes": [timeframe.lower() for timeframe in normalize_list(args.timeframes)],
        "operator": args.operator,
        "approved_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "backtest_hash": args.backtest_hash,
        "label": args.label,
        "notes": args.notes,
        "approval_class": args.approval_class,
        "class_reason": args.class_reason,
    }

    result = upsert_approval(manifest, approval)
    manifest["updated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
        handle.write("\n")

    print(f"{result}: {approval['strategy']} [{approval['approval_class']}] -> {manifest_path}")


if __name__ == "__main__":
    main()
