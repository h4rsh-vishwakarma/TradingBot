#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.daily_paper_report import calculate_paper_day, get_signal_timestamps, PAPER_START

PAPER_DIR = PROJECT_ROOT / 'storage' / 'reports' / 'paper_validation'
EC2_CI_DIR = PROJECT_ROOT / 'storage' / 'reports' / 'ec2_ci'
INVENTORY_PATH = PROJECT_ROOT / 'storage' / 'reports' / 'tv_inventory_report.csv'
MANIFEST_PATH = PROJECT_ROOT / 'config' / 'approved_strategies.json'


def load_manifest_candidates() -> list[str]:
    try:
        data = json.loads(MANIFEST_PATH.read_text(encoding='utf-8'))
    except Exception:
        return []
    lines = []
    for approval in data.get('approvals', []):
        if approval.get('approval_class') != 'candidate_for_tiny_capital':
            continue
        symbols = ','.join(approval.get('symbols', [])) or '*'
        timeframes = ','.join(approval.get('timeframes', [])) or '*'
        lines.append(f"{approval.get('strategy')} | {symbols} | {timeframes}")
    return lines


def copy_if_exists(src: Path, dest_dir: Path):
    if src.exists() and src.is_file():
        shutil.copy2(src, dest_dir / src.name)


def main() -> int:
    bundle_day = datetime.now(timezone.utc).strftime('%Y%m%d')
    output_dir = PAPER_DIR / f'evidence_bundle_{bundle_day}'
    output_dir.mkdir(parents=True, exist_ok=True)

    for pattern in ['day*.txt', 'recon_*.txt', 'execution_freeze*.json', 'execution_freeze.log', 'gate_snapshots.log']:
        for src in PAPER_DIR.glob(pattern):
            copy_if_exists(src, output_dir)

    for src in EC2_CI_DIR.glob('*.txt'):
        copy_if_exists(src, output_dir)

    copy_if_exists(INVENTORY_PATH, output_dir)

    signal_meta = get_signal_timestamps()
    paper_day = calculate_paper_day()
    verdict = 'UNKNOWN'
    gate_files = sorted(EC2_CI_DIR.glob('go_live_gate_*.txt'))
    if gate_files:
        try:
            gate_text = gate_files[-1].read_text(encoding='utf-8', errors='ignore')
            for line in gate_text.splitlines():
                if line.strip().startswith('VERDICT:'):
                    verdict = line.strip().replace('VERDICT:', '').strip()
                    break
        except Exception:
            pass

    summary = [
        f'Generated UTC: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}',
        f'Paper window start: {PAPER_START}',
        f'Paper day observed: {paper_day} of 7',
        f'Current gate verdict: {verdict}',
        '',
        'Current candidate scope:',
    ]
    summary.extend(load_manifest_candidates() or ['None found'])
    summary.extend([
        '',
        f"Last approved-signal: {signal_meta.get('last_approved')}",
        f"Last bot-visible signal: {signal_meta.get('last_bot_visible')}",
        '',
        'Note: if paper day is below 7, this bundle is an interim snapshot and not the final Apr 14 packet.',
    ])
    (output_dir / 'SUMMARY.txt').write_text('\n'.join(summary) + '\n', encoding='utf-8')
    print(output_dir)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
