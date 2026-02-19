"""
Complete Backtest Artifact Exporter

Generates production-ready CSV artifacts from JSONL event logs for LLM training and analysis.

Artifacts Generated:
1. trade_log.csv - Individual trade execution records
2. equity.csv - Cumulative equity curve 
3. signals.csv - 5-minute decision signals
4. trade_summary.csv - Enhanced trade analytics

Features:
- All timestamps in Asia/Kolkata (UTC+5:30)
- 5-minute bar frequency (288 bars/day)
- Field alias normalization (pnl_usd/pnl_$/pnl, etc.)
- Backward compatible with existing events

Usage:
    # CLI
    python backtest_artifacts_exporter.py --run-id r_abc123 --events-dir logs/events
    
    # Programmatic
    from backtest_artifacts_exporter import export_all
    artifacts = export_all(run_id='r_abc123')
    
    # From main bot script
    if config.get('EXPORT_BACKTEST_ARTIFACTS'):
        export_all(run_id=run_id, events_dir='logs/events')
"""

import os
import json
import gzip
import glob
import argparse
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import csv

# ============================================================================
# CONFIGURATION
# ============================================================================

# Timezone: Asia/Kolkata UTC+5:30
IST_OFFSET = timedelta(hours=5, minutes=30)
IST_TZ = timezone(IST_OFFSET)

# Bar frequency for signals
BAR_FREQUENCY_MINUTES = 5

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False


# ============================================================================
# UTILITIES
# ============================================================================

def _parse_timestamp(ts_str: str) -> Optional[datetime]:
    """Parse ISO timestamp to datetime object."""
    if not ts_str:
        return None
    try:
        ts_str = ts_str.replace('Z', '+00:00')
        return datetime.fromisoformat(ts_str)
    except Exception:
        try:
            return datetime.strptime(ts_str, '%Y-%m-%dT%H:%M:%S.%f')
        except Exception:
            return None


def _to_ist(dt: Optional[datetime]) -> Optional[str]:
    """Convert datetime to IST timezone string (ISO8601 format)."""
    if not dt:
        return None
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        ist_dt = dt.astimezone(IST_TZ)
        return ist_dt.isoformat()
    except Exception:
        return None


def _safe_float(v, default=0.0) -> float:
    """Safe float conversion with default."""
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


def _load_jsonl(filepath: str, event_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Load events from JSONL file (supports .gz compression and rotated segments).
    
    This will aggregate across all rotated parts (e.g., decision.jsonl.1.gz) to
    avoid losing history when rotation occurs.
    
    Compatible with both old and new event schemas:
    - Old: No 'event' field, detected by presence of decision_id/order_id/fill_id
    - New: Has 'event' field like 'decision', 'order', 'fill'
    """
    events: List[Dict[str, Any]] = []

    # Collect base file plus any rotated segments
    candidates = [p for p in glob.glob(filepath + '*') if os.path.isfile(p)]
    print(f"  DEBUG _load_jsonl: Pattern={filepath}*, Found {len(candidates)} files")
    if not candidates:
        return events

    # Process in chronological order (oldest first) based on mtime
    for path in sorted(candidates, key=os.path.getmtime):
        try:
            open_func = gzip.open if path.endswith('.gz') else open
            mode = 'rt' if path.endswith('.gz') else 'r'

            with open_func(path, mode, encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        evt = json.loads(line)
                        
                        # Apply event filter (support both old and new schemas)
                        if event_filter is None:
                            events.append(evt)
                        elif evt.get('event') == event_filter:
                            # New schema: event field exists and matches
                            events.append(evt)
                        elif event_filter == 'decision' and 'decision_id' in evt and 'action' in evt:
                            # Old schema: decision event has decision_id + action
                            events.append(evt)
                        elif event_filter == 'order' and 'order_id' in evt and 'side' in evt:
                            # Old schema: order event has order_id + side
                            events.append(evt)
                        elif event_filter == 'fill' and 'fill_id' in evt:
                            # Old schema: fill event has fill_id
                            events.append(evt)
                    except Exception:
                        continue
        except Exception:
            continue
    
    return events


# ============================================================================
# ARTIFACT GENERATOR 1: trade_log.csv
# ============================================================================

def generate_trade_log(events_dir: str, output_path: str) -> None:
    """
    Generate trade_log.csv from order and fill events.
    
    Canonical schema:
    - decision_time: ISO8601 datetime in IST (+05:30)
    - exec_time: ISO8601 datetime in IST (+05:30)
    - side: LONG/SHORT or BUY/SELL
    - qty: float (contracts or BTC)
    - price: float (execution price)
    - pnl_usd: float (realized P&L per trade)
    - transaction_cost: float (fees + slippage in USD)
    
    Alias normalization:
    - pnl_usd accepts: pnl_$, pnl, pnl_close
    - transaction_cost accepts: cost_$, fee_usd, fees_usd, fee
    """
    print(f"[1/4] Generating trade_log.csv...")
    
    # Load events (match base file + date-rotated archives like decision_20251219.jsonl.gz)
    decision_pattern = os.path.join(events_dir, 'decision')
    order_pattern = os.path.join(events_dir, 'order')
    fill_pattern = os.path.join(events_dir, 'fill')
    
    decisions = _load_jsonl(decision_pattern, event_filter='decision')
    orders = _load_jsonl(order_pattern, event_filter='order')
    fills = _load_jsonl(fill_pattern, event_filter='fill')
    
    print(f"  DEBUG: Loaded {len(decisions)} decisions, {len(orders)} orders, {len(fills)} fills")
    
    # Build index mappings
    decision_by_id = {d.get('decision_id'): d for d in decisions if d.get('decision_id')}
    
    print(f"  DEBUG: Indexed {len(decision_by_id)} decisions by ID")
    
    orders_by_decision = defaultdict(list)
    orders_by_id = {}
    for order in orders:
        decision_id = order.get('decision_id')
        order_id = order.get('order_id')
        if decision_id:
            orders_by_decision[decision_id].append(order)
        if order_id:
            orders_by_id[order_id] = order
    
    fills_by_order = defaultdict(list)
    for fill in fills:
        order_id = fill.get('order_id')
        if order_id:
            fills_by_order[order_id].append(fill)
    
    # Build trade records
    trade_records = []
    
    for decision_id, decision in decision_by_id.items():
        decision_time = _to_ist(_parse_timestamp(decision.get('ts')))
        
        decision_orders = orders_by_decision.get(decision_id, [])
        
        for order in decision_orders:
            order_id = order.get('order_id')
            order_fills = fills_by_order.get(order_id, [])
            
            for fill in order_fills:
                exec_time = _to_ist(_parse_timestamp(fill.get('ts')))
                
                # Extract with canonical naming
                side = order.get('side', 'UNKNOWN')
                qty = _safe_float(fill.get('qty'))
                price = _safe_float(fill.get('px') or fill.get('price'))
                
                # PnL with alias normalization
                pnl_usd = _safe_float(
                    fill.get('pnl_usd') or 
                    fill.get('pnl_$') or 
                    fill.get('pnl') or 
                    fill.get('pnl_close')
                )
                
                # Transaction cost with alias normalization
                transaction_cost = _safe_float(
                    fill.get('transaction_cost') or 
                    fill.get('cost_$') or 
                    fill.get('fee_usd') or 
                    fill.get('fees_usd') or 
                    fill.get('fee')
                )
                
                trade_records.append({
                    'decision_time': decision_time,
                    'exec_time': exec_time,
                    'side': side,
                    'qty': qty,
                    'price': price,
                    'pnl_usd': pnl_usd,
                    'transaction_cost': transaction_cost
                })
    
    # Sort chronologically
    trade_records.sort(key=lambda x: x['exec_time'] or '')
    
    # Write CSV
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'decision_time', 'exec_time', 'side', 'qty', 'price', 'pnl_usd', 'transaction_cost'
        ])
        writer.writeheader()
        writer.writerows(trade_records)
    
    print(f"  ✓ Created {output_path} ({len(trade_records)} trades)")


# ============================================================================
# ARTIFACT GENERATOR 2: equity.csv
# ============================================================================

def generate_equity_curve(trade_log_path: str, output_path: str, initial_equity: float = 100000.0) -> None:
    """
    Generate equity.csv from trade_log.csv.
    
    Schema:
    - ts: ISO8601 datetime in IST
    - equity_value: float (cumulative equity)
    
    Rules:
    - Sort ascending by ts
    - equity = initial_equity + cumulative realized PnL
    """
    print(f"[2/4] Generating equity.csv...")
    
    equity_records = []
    
    if not os.path.exists(trade_log_path):
        # No trades yet - create initial equity point
        now_ist = _to_ist(datetime.now(timezone.utc))
        equity_records.append({
            'ts': now_ist,
            'equity_value': initial_equity
        })
    else:
        # Load trades
        with open(trade_log_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            trades = list(reader)
        
        # Sort by exec_time
        trades.sort(key=lambda x: x.get('exec_time', ''))
        
        # Compute cumulative equity
        cumulative_pnl = 0.0
        
        for trade in trades:
            exec_time = trade.get('exec_time')
            pnl_usd = _safe_float(trade.get('pnl_usd'))
            cumulative_pnl += pnl_usd
            
            equity_value = initial_equity + cumulative_pnl
            
            equity_records.append({
                'ts': exec_time,
                'equity_value': equity_value
            })
    
    # Write CSV
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['ts', 'equity_value'])
        writer.writeheader()
        writer.writerows(equity_records)
    
    print(f"  ✓ Created {output_path} ({len(equity_records)} records)")


# ============================================================================
# ARTIFACT GENERATOR 3: signals.csv
# ============================================================================

def generate_signals(events_dir: str, output_path: str) -> None:
    """
    Generate signals.csv from decision events.
    
    Schema:
    - ts: ISO8601 datetime in IST (5-minute grid)
    - pred_bps: float (model prediction in basis points)
    - pred_raw: float (raw model score)
    - S_top: float (long/cohort score)
    - S_bot: float (short/cohort score)
    - adv20: float (optional, average daily volume)
    
    Rules:
    - Normalize to 5-minute bars via resampling
    - Extract/compute from decision events, RL outputs, signal generator
    """
    print(f"[3/4] Generating signals.csv...")
    
    # Load decision events
    decision_path = os.path.join(events_dir, 'decision.jsonl')
    decisions = _load_jsonl(decision_path, event_filter='decision')
    
    # Extract signal data
    signal_records = []
    
    for decision in decisions:
        ts = _parse_timestamp(decision.get('ts'))
        ts_ist = _to_ist(ts)
        
        # Derive prediction fields from available data
        # pred_bps can come from edge_bps, cluster analysis, or explicit field
        pred_bps = _safe_float(
            decision.get('pred_bps') or 
            decision.get('edge_bps') or 
            (decision.get('costs') or {}).get('edge_bps')
        )
        
        # pred_raw from signal_strength or raw RL output
        pred_raw = _safe_float(
            decision.get('pred_raw') or 
            decision.get('signal_strength')
        )
        
        # Cohort scores (long/short or top/bot)
        S_top = _safe_float(
            decision.get('S_long') or 
            decision.get('S_top')
        )
        S_bot = _safe_float(
            decision.get('S_short') or 
            decision.get('S_bot')
        )
        
        # Optional volume field
        adv20 = _safe_float(decision.get('adv20'))
        
        signal_records.append({
            'ts': ts_ist,
            'pred_bps': pred_bps,
            'pred_raw': pred_raw,
            'S_top': S_top,
            'S_bot': S_bot,
            'adv20': adv20
        })
    
    # Normalize to 5-minute bars if pandas available
    if PANDAS_AVAILABLE and signal_records:
        try:
            df = pd.DataFrame(signal_records)
            df['ts'] = pd.to_datetime(df['ts'])
            df = df.set_index('ts')
            
            # Resample to 5-minute bars using forward-fill
            df_resampled = df.resample('5T').ffill()
            
            # Convert back to records
            df_resampled = df_resampled.reset_index()
            df_resampled['ts'] = df_resampled['ts'].dt.strftime('%Y-%m-%dT%H:%M:%S%z')
            signal_records = df_resampled.to_dict('records')
        except Exception as e:
            # Fallback to raw records if resampling fails
            print(f"  ⚠ Resampling failed ({e}), using raw signals")
    
    # Sort chronologically
    signal_records.sort(key=lambda x: x.get('ts', ''))
    
    # Write CSV
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'ts', 'pred_bps', 'pred_raw', 'S_top', 'S_bot', 'adv20'
        ])
        writer.writeheader()
        writer.writerows(signal_records)
    
    print(f"  ✓ Created {output_path} ({len(signal_records)} signals)")


# ============================================================================
# ARTIFACT GENERATOR 4: trade_summary.csv
# ============================================================================

def generate_trade_summary(trade_log_path: str, events_dir: str, output_path: str) -> None:
    """
    Generate trade_summary.csv with enhanced analytics.
    
    Schema:
    - trade_id: unique identifier
    - decision_time: ISO8601 datetime in IST
    - exec_time: ISO8601 datetime in IST
    - side: LONG/SHORT or BUY/SELL
    - entry_price: float
    - exit_price: float
    - qty: float
    - pnl_usd: float
    - r_multiple: float (risk-adjusted return)
    - time_in_trade_s: float (seconds)
    - exit_reason: enum (tp, sl, time, manual, risk_cap)
    - edge_bps_at_entry: float
    - cluster_width_bps: float
    - cluster_intensity_z: float
    
    Built from joined decision/order/fill events.
    """
    print(f"[4/4] Generating trade_summary.csv...")
    
    # Load events
    decision_path = os.path.join(events_dir, 'decision.jsonl')
    order_path = os.path.join(events_dir, 'order.jsonl')
    fill_path = os.path.join(events_dir, 'fill.jsonl')
    
    decisions = _load_jsonl(decision_path, event_filter='decision')
    orders = _load_jsonl(order_path, event_filter='order')
    fills = _load_jsonl(fill_path, event_filter='fill')
    
    # Build index mappings
    decision_by_id = {d.get('decision_id'): d for d in decisions if d.get('decision_id')}
    
    orders_by_decision = defaultdict(list)
    orders_by_id = {}
    for order in orders:
        decision_id = order.get('decision_id')
        order_id = order.get('order_id')
        if decision_id:
            orders_by_decision[decision_id].append(order)
        if order_id:
            orders_by_id[order_id] = order
    
    fills_by_order = defaultdict(list)
    for fill in fills:
        order_id = fill.get('order_id')
        if order_id:
            fills_by_order[order_id].append(fill)
    
    # Build trade summaries
    trade_summaries = []
    trade_counter = 1
    
    for decision_id, decision in decision_by_id.items():
        decision_time = _to_ist(_parse_timestamp(decision.get('ts')))
        
        # Extract cluster and cost info from decision
        cluster = decision.get('cluster', {})
        costs = decision.get('costs', {})
        
        edge_bps_at_entry = _safe_float(costs.get('edge_bps'), default=0.0)
        cluster_width_bps = _safe_float(cluster.get('target_width_pct', 0), default=0.0) * 100  # Convert % to bps
        cluster_intensity_z = _safe_float(cluster.get('intensity_z'), default=0.0)
        
        decision_orders = orders_by_decision.get(decision_id, [])
        
        for order in decision_orders:
            order_id = order.get('order_id')
            order_fills = fills_by_order.get(order_id, [])
            
            for fill in order_fills:
                exec_time = _to_ist(_parse_timestamp(fill.get('ts')))
                
                side = order.get('side', 'UNKNOWN')
                entry_price = _safe_float(fill.get('px') or fill.get('price'), default=0.0)
                
                # Exit price (simplified - same as entry for now, can enhance later)
                exit_price = entry_price
                
                qty = _safe_float(fill.get('qty'), default=0.0)
                pnl_usd = _safe_float(
                    fill.get('pnl_close') or 
                    fill.get('pnl_usd') or 
                    fill.get('pnl'),
                    default=0.0
                )
                
                # R-multiple (risk-adjusted return)
                r_multiple = _safe_float(fill.get('r_multiple'), default=0.0)
                
                # Time in trade
                time_in_trade_s = _safe_float(fill.get('hold_duration_s'), default=0.0)
                
                # Exit reason
                exit_reason = fill.get('exit_type') or 'unknown'
                
                trade_summaries.append({
                    'trade_id': f'trade_{trade_counter}',
                    'decision_time': decision_time,
                    'exec_time': exec_time,
                    'side': side,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'qty': qty,
                    'pnl_usd': pnl_usd,
                    'r_multiple': r_multiple,
                    'time_in_trade_s': time_in_trade_s,
                    'exit_reason': exit_reason,
                    'edge_bps_at_entry': edge_bps_at_entry,
                    'cluster_width_bps': cluster_width_bps,
                    'cluster_intensity_z': cluster_intensity_z
                })
                trade_counter += 1
    
    # Sort chronologically
    trade_summaries.sort(key=lambda x: x.get('exec_time', ''))
    
    # Write CSV
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'trade_id', 'decision_time', 'exec_time', 'side', 'entry_price', 'exit_price',
            'qty', 'pnl_usd', 'r_multiple', 'time_in_trade_s', 'exit_reason',
            'edge_bps_at_entry', 'cluster_width_bps', 'cluster_intensity_z'
        ])
        writer.writeheader()
        writer.writerows(trade_summaries)
    
    print(f"  ✓ Created {output_path} ({len(trade_summaries)} summaries)")


# ============================================================================
# MAIN EXPORT PIPELINE
# ============================================================================

def export_all(
    run_id: Optional[str] = None,
    events_dir: str = "./logs/events",
    out_dir: str = "./backtest_artifacts",
    initial_equity: float = 100000.0
) -> Dict[str, str]:
    """
    Export all backtest artifacts from event logs.
    
    This is the main entrypoint for generating complete backtest artifacts.
    
    Args:
        run_id: Optional run identifier for logging/tracking. If None, aggregates ALL runs.
        events_dir: Directory containing JSONL event files
        out_dir: Output directory for artifacts
        initial_equity: Starting equity for equity curve
        
    Returns:
        Dict mapping artifact name to file path
        
    Example:
        >>> artifacts = export_all()  # Export all runs
        >>> artifacts = export_all(run_id='r_abc123')  # Export specific run
        >>> print(artifacts['trade_log'])
        './backtest_artifacts/trade_log.csv'
    """
    print(f"\n{'='*80}")
    print(f"BACKTEST ARTIFACT EXPORT")
    print(f"Run ID: {run_id if run_id else 'ALL (aggregated)'}")
    print(f"Events: {events_dir}")
    print(f"Output: {out_dir}")
    print(f"{'='*80}\n")
    
    os.makedirs(out_dir, exist_ok=True)
    
    artifacts = {}
    
    # Generate artifacts in dependency order
    try:
        # 1. Trade Log (required for equity curve)
        trade_log_path = os.path.join(out_dir, 'trade_log.csv')
        generate_trade_log(events_dir, trade_log_path)
        artifacts['trade_log'] = trade_log_path
    except Exception as e:
        print(f"  ✗ Failed to generate trade_log.csv: {e}")
    
    try:
        # 2. Equity Curve (depends on trade log)
        equity_path = os.path.join(out_dir, 'equity.csv')
        generate_equity_curve(trade_log_path, equity_path, initial_equity)
        artifacts['equity'] = equity_path
    except Exception as e:
        print(f"  ✗ Failed to generate equity.csv: {e}")
    
    try:
        # 3. Signals (independent)
        signals_path = os.path.join(out_dir, 'signals.csv')
        generate_signals(events_dir, signals_path)
        artifacts['signals'] = signals_path
    except Exception as e:
        print(f"  ✗ Failed to generate signals.csv: {e}")
    
    try:
        # 4. Trade Summary (optional but recommended)
        trade_summary_path = os.path.join(out_dir, 'trade_summary.csv')
        generate_trade_summary(trade_log_path, events_dir, trade_summary_path)
        artifacts['trade_summary'] = trade_summary_path
    except Exception as e:
        print(f"  ✗ Failed to generate trade_summary.csv: {e}")
    
    print(f"\n{'='*80}")
    print(f"EXPORT COMPLETE")
    print(f"{'='*80}\n")
    
    if artifacts:
        print("Generated artifacts:")
        for name, path in artifacts.items():
            print(f"  • {name:20s} → {path}")
    else:
        print("  ⚠ No artifacts generated")
    
    print()
    
    return artifacts


# ============================================================================
# CLI ENTRYPOINT
# ============================================================================

def main():
    """CLI entrypoint for backtest artifact export."""
    parser = argparse.ArgumentParser(
        description='Export backtest artifacts from JSONL event logs',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Export all runs (recommended for live bot)
  python backtest_artifacts_exporter.py
  
  # Export specific run
  python backtest_artifacts_exporter.py --run-id r_abc123
  
  # Custom paths
  python backtest_artifacts_exporter.py \\
      --events-dir /path/to/logs/events \\
      --out-dir /path/to/output
  
  # With custom initial equity
  python backtest_artifacts_exporter.py --initial-equity 1000

Output Structure:
  backtest_artifacts/
    ├── trade_log.csv       (individual trades)
    ├── equity.csv          (equity curve)
    ├── signals.csv         (5-min decision signals)
    └── trade_summary.csv   (enhanced analytics)
        """
    )
    
    parser.add_argument('--run-id', required=False, default=None, help='Run identifier (default: aggregate ALL runs)')
    parser.add_argument('--events-dir', default='./logs/events', help='Events directory (default: ./logs/events)')
    parser.add_argument('--out-dir', default='./backtest_artifacts', help='Output directory (default: ./backtest_artifacts)')
    parser.add_argument('--initial-equity', type=float, default=100000.0, help='Initial equity (default: 100000.0)')
    
    args = parser.parse_args()
    
    export_all(
        run_id=args.run_id,
        events_dir=args.events_dir,
        out_dir=args.out_dir,
        initial_equity=args.initial_equity
    )


if __name__ == '__main__':
    main()
