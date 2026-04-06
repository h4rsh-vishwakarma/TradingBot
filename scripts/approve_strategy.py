import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def load_manifest(path: Path) -> dict:
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
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
        tuple(sorted(s.upper() for s in approval["symbols"])),
        tuple(sorted(tf.lower() for tf in approval["timeframes"])),
    )

    for idx, existing in enumerate(approvals):
        existing_key = (
            str(existing.get("strategy", "")).strip().lower(),
            str(existing.get("exchange", "")).strip().lower(),
            tuple(sorted(str(s).upper() for s in existing.get("symbols", ["*"]))),
            tuple(sorted(str(tf).lower() for tf in existing.get("timeframes", ["*"]))),
        )
        if existing_key == match_key:
            approvals[idx] = approval
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
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    manifest = load_manifest(manifest_path)

    approval = {
        "strategy": args.strategy,
        "exchange": args.exchange.lower(),
        "symbols": [s.upper() for s in normalize_list(args.symbols)],
        "timeframes": [tf.lower() for tf in normalize_list(args.timeframes)],
        "operator": args.operator,
        "approved_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "backtest_hash": args.backtest_hash,
        "label": args.label,
        "notes": args.notes,
    }

    result = upsert_approval(manifest, approval)
    manifest["updated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")

    print(f"{result}: {approval['strategy']} -> {manifest_path}")


if __name__ == "__main__":
    main()
