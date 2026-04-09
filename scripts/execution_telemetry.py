#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXECUTION_METRICS_PATH = PROJECT_ROOT / 'storage' / 'reports' / 'paper_validation' / 'execution_metrics.jsonl'


def execution_metrics_path() -> Path:
    return Path(os.getenv('EXECUTION_METRICS_PATH', str(DEFAULT_EXECUTION_METRICS_PATH)))


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def estimate_fee_bps(exchange: str, execution_res: dict | None = None) -> float:
    execution_res = execution_res or {}
    explicit = execution_res.get('estimated_fee_bps')
    if explicit not in (None, ''):
        return _safe_float(explicit, 0.0)

    exchange = str(exchange or '').lower()
    if exchange == 'binance':
        order_mode = str(execution_res.get('order_type_used', '')).upper()
        if order_mode in {'LIMIT_GTX', 'LIMIT_MAKER'}:
            return _safe_float(os.getenv('BINANCE_MAKER_FEE_BPS', '2.0'), 2.0)
        return _safe_float(os.getenv('BINANCE_TAKER_FEE_BPS', '4.0'), 4.0)
    if exchange == 'lighter':
        return _safe_float(os.getenv('LIGHTER_TAKER_FEE_BPS', '4.0'), 4.0)
    if exchange == 'hyperliquid':
        return _safe_float(os.getenv('HYPERLIQUID_TAKER_FEE_BPS', '3.5'), 3.5)
    return _safe_float(os.getenv('DEFAULT_EXECUTION_FEE_BPS', '4.0'), 4.0)


def append_execution_metric(event: dict, path: str | Path | None = None) -> Path:
    output_path = Path(path) if path else execution_metrics_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(event)
    payload.setdefault('telemetry_version', 1)
    payload.setdefault('recorded_at', datetime.utcnow().isoformat() + 'Z')
    with output_path.open('a', encoding='utf-8') as handle:
        json.dump(payload, handle, separators=(',', ':'), ensure_ascii=True)
        handle.write('\n')
    return output_path


def summarize_execution_metrics(hours: int = 24, path: str | Path | None = None) -> dict:
    output_path = Path(path) if path else execution_metrics_path()
    cutoff = time.time() - max(hours, 1) * 3600
    summary = {
        'fill_count': 0,
        'entry_fills': 0,
        'exit_fills': 0,
        'round_trip_ratio': None,
        'gross_edge_total': 0.0,
        'impact_total': 0.0,
        'fee_total': 0.0,
        'slippage_total': 0.0,
        'impact_share_pct': None,
        'fee_share_pct': None,
        'slippage_share_pct': None,
        'impact_dominant': False,
        'telemetry_coverage_pct': None,
        'note': 'No execution telemetry captured in lookback window.',
        'path': str(output_path),
    }
    if not output_path.exists():
        return summary

    entries = []
    with output_path.open('r', encoding='utf-8', errors='ignore') as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = _safe_float(item.get('timestamp_epoch'), 0.0)
            if ts and ts >= cutoff:
                entries.append(item)

    if not entries:
        return summary

    summary['fill_count'] = len(entries)
    summary['entry_fills'] = sum(1 for item in entries if not bool(item.get('is_exit')))
    summary['exit_fills'] = sum(1 for item in entries if bool(item.get('is_exit')))
    if summary['entry_fills'] > 0:
        summary['round_trip_ratio'] = summary['exit_fills'] / summary['entry_fills']

    closed = [item for item in entries if bool(item.get('is_exit'))]
    covered = [item for item in closed if _safe_float(item.get('gross_edge_usd'), 0.0) > 0]
    if closed:
        summary['telemetry_coverage_pct'] = (len(covered) / len(closed)) * 100.0

    if not closed:
        summary['note'] = 'No closed fills yet; cost shares will populate after the first exit fill.'
        return summary
    if not covered:
        summary['note'] = 'Closed fills have non-positive gross edge; cost shares suppressed.'
        return summary

    summary['gross_edge_total'] = sum(_safe_float(item.get('gross_edge_usd')) for item in covered)
    summary['impact_total'] = sum(_safe_float(item.get('latency_impact_usd')) for item in covered)
    summary['fee_total'] = sum(_safe_float(item.get('estimated_fee_usd')) for item in covered)
    summary['slippage_total'] = sum(_safe_float(item.get('execution_slippage_usd')) for item in covered)

    gross_edge = summary['gross_edge_total']
    if gross_edge > 0:
        summary['impact_share_pct'] = summary['impact_total'] / gross_edge * 100.0
        summary['fee_share_pct'] = summary['fee_total'] / gross_edge * 100.0
        summary['slippage_share_pct'] = summary['slippage_total'] / gross_edge * 100.0
        summary['impact_dominant'] = (
            summary['impact_share_pct'] >= 50.0
            or summary['impact_total'] > (summary['fee_total'] + summary['slippage_total'])
        )
        summary['note'] = 'RED: impact dominates gross edge.' if summary['impact_dominant'] else 'Execution quality within expected bounds.'
    return summary
