# Quick Integration: Code Snippets to Add

## File: observability/emitters/emitters.py

### Add these fields when emitting DecisionEvent

Find the `emit_decision()` method and ensure these P1 fields are included:

```python
def emit_decision(
    self,
    decision_id: Optional[str] = None,
    signal_dir: str = 'NONE',
    signal_strength: str = 'NONE',
    S_long: float = 0.0,
    S_short: float = 0.0,
    action: str = 'NO_TRADE',
    # ... existing params ...
    
    # ADD THESE FOR COMPLETE ARTIFACT EXPORT:
    pred_bps: Optional[float] = None,       # Prediction in basis points
    pred_raw: Optional[float] = None,       # Raw model score
    vote_scores: Optional[Dict] = None,     # P1: Confidence scores per timeframe
    cluster_rank: int = 0,                  # P1: Cluster ranking
    entry_px: float = 0.0,                  # P1: Precise entry price
    adv20: Optional[float] = None,          # Average daily volume
):
    """Emit a decision event with complete fields for artifact export."""
    
    event = DecisionEvent(
        decision_id=decision_id or generate_decision_id(),
        signal_dir=signal_dir,
        signal_strength=signal_strength,
        S_long=S_long,
        S_short=S_short,
        action=action,
        
        # For signals.csv
        pred_bps=pred_bps or (costs or {}).get('edge_bps'),
        pred_raw=pred_raw or S_long if signal_dir == 'LONG' else S_short,
        
        # P1 fields
        vote_scores=vote_scores or {'m1': 0.0, 'm2': 0.0, 'm3': 0.0},
        cluster_rank=cluster_rank,
        entry_px=entry_px,
        
        # ... rest of existing fields ...
    )
```

### Example Usage in Signal Generator

```python
# In signal_generator.py, when emitting decisions:

self.emitters.emit_decision(
    decision_id=decision_id,
    signal_dir='LONG' if long_score > short_score else 'SHORT',
    signal_strength='STRONG',
    S_long=long_score,
    S_short=short_score,
    action='PLACE',
    
    # ADD THESE:
    pred_bps=edge_bps,                     # From cost analysis
    pred_raw=max(long_score, short_score), # Raw signal strength
    vote_scores={
        'm1': m1_confidence * 100,         # 1-min timeframe confidence
        'm2': m2_confidence * 100,         # 5-min timeframe confidence
        'm3': m3_confidence * 100          # 15-min timeframe confidence
    },
    cluster_rank=ranked_clusters[0]['rank'] if ranked_clusters else 0,
    entry_px=target_cluster['level'],
    adv20=volume_analysis.get('adv20'),    # If available
    
    # Cluster info for trade_summary
    cluster={
        'target_level': target_cluster['level'],
        'target_width_pct': target_cluster['width_pct'],
        'intensity_z': target_cluster['intensity_z'],
        'distance_bps': target_cluster['distance_bps']
    },
    
    # Cost analysis for trade_summary
    costs={
        'spread_bps': current_spread_bps,
        'est_slip_bps': estimated_slippage_bps,
        'edge_bps': edge_bps
    }
)
```

## File: observability/emitters/emitters.py (OrderEvent)

### Ensure decision_id linkage

```python
def emit_order(
    self,
    order_id: Optional[str] = None,
    decision_id: str = '',  # CRITICAL: Must link to decision
    side: str = 'BUY',
    px: float = 0.0,
    qty: float = 0.0,
    # ... existing params ...
):
    """Emit order event with decision linkage."""
    
    event = OrderEvent(
        order_id=order_id or generate_order_id(),
        decision_id=decision_id,  # Link to decision event
        side=side,
        px=px,
        qty=qty,
        # ... rest of fields ...
    )
```

### Example Usage

```python
# When placing order, pass decision_id from signal
order_id = self.place_order(signal)

self.emitters.emit_order(
    order_id=order_id,
    decision_id=signal['decision_id'],  # Link back to decision
    side='BUY' if signal['direction'] == 'LONG' else 'SELL',
    px=signal['entry_price'],
    qty=signal['quantity']
)
```

## File: observability/emitters/emitters.py (FillEvent)

### Ensure complete fill data with aliases

```python
def emit_fill(
    self,
    fill_id: Optional[str] = None,
    order_id: str = '',  # CRITICAL: Must link to order
    px: float = 0.0,
    qty: float = 0.0,
    
    # PnL (any of these field names works - exporter normalizes)
    pnl_close: float = 0.0,     # Use this one
    # pnl_usd: float = 0.0,     # Or this
    # pnl: float = 0.0,         # Or this
    
    # Transaction cost (any of these works)
    fee: float = 0.0,           # Use this one
    # transaction_cost: float = 0.0,  # Or this
    # fee_usd: float = 0.0,     # Or this
    
    # For trade_summary.csv
    r_multiple: Optional[float] = None,
    hold_duration_s: Optional[float] = None,
    exit_type: Optional[str] = None,  # 'tp', 'sl', 'time', 'manual', 'risk_cap'
    
    # P0/P1 enhancements
    slippage_bps: Optional[float] = None,
    tp_level_hit: Optional[int] = None,
    cluster_evolution: Optional[str] = None,
):
    """Emit fill event with complete data for artifact export."""
    
    event = FillEvent(
        fill_id=fill_id or generate_fill_id(),
        order_id=order_id,  # Link to order event
        px=px,
        qty=qty,
        pnl_close=pnl_close,
        fee=fee,
        r_multiple=r_multiple,
        hold_duration_s=hold_duration_s,
        exit_type=exit_type,
        slippage_bps=slippage_bps,
        tp_level_hit=tp_level_hit,
        cluster_evolution=cluster_evolution,
        # ... rest of fields ...
    )
```

### Example Usage

```python
# When order fills
entry_time = time.time()

# ... trading happens ...

# On exit
exit_time = time.time()
hold_duration_s = exit_time - entry_time

self.emitters.emit_fill(
    fill_id=f'fill_{uuid.uuid4().hex[:8]}',
    order_id=order_id,              # Link back to order
    px=fill_price,
    qty=filled_quantity,
    pnl_close=realized_pnl,         # Canonical field name
    fee=total_fees,                 # Canonical field name
    r_multiple=pnl / initial_risk,  # Risk-adjusted return
    hold_duration_s=hold_duration_s,
    exit_type='tp1',                # 'tp1', 'tp2', 'tp3', 'sl', 'time', etc.
    slippage_bps=(fill_price - expected_price) / expected_price * 10000,
    tp_level_hit=1,                 # Which TP level hit (1, 2, or 3)
    cluster_evolution='strengthened'  # 'strengthened', 'weakened', 'dissolved'
)
```

## Integration into Main Bot Script

### Option 1: Add to enhanced_trading_bot.py

Add this at the END of your main() function, AFTER the bot shuts down:

```python
def main():
    # ... existing bot code ...
    
    try:
        # Run trading bot
        bot.run()
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    finally:
        bot.shutdown()
    
    # ADD THIS: Export backtest artifacts
    if os.getenv('EXPORT_BACKTEST_ARTIFACTS', '0') == '1':
        logger.info("="*80)
        logger.info("EXPORTING BACKTEST ARTIFACTS")
        logger.info("="*80)
        
        try:
            from backtest_artifacts_exporter import export_all
            artifacts = export_all(
                run_id=run_id,
                events_dir='./logs/events',
                out_dir='./backtest_artifacts',
                initial_equity=100000.0
            )
            logger.info(f"Exported {len(artifacts)} artifacts")
        except Exception as e:
            logger.error(f"Artifact export failed: {e}")


if __name__ == '__main__':
    main()
```

### Option 2: Add CLI Argument

```python
import argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', default='PAPER')
    parser.add_argument('--export-artifacts', action='store_true',
                       help='Export backtest artifacts on shutdown')
    args = parser.parse_args()
    
    # ... bot code ...
    
    # At end
    if args.export_artifacts:
        from backtest_artifacts_exporter import export_all
        export_all(run_id=run_id, events_dir='./logs/events')
```

## Complete Minimal Example

```python
# example_integration.py
import os
from datetime import datetime, timezone
from observability.emitters import ObservabilityHub
from backtest_artifacts_exporter import export_all

# Initialize observability
run_id = f"r_{int(datetime.now().timestamp())}"
hub = ObservabilityHub(run_id=run_id, session_id='s_001', mode='PAPER')

# Simulate trading
decision_id = 'dec_001'
order_id = 'ord_001'

# 1. Decision
hub.emit_decision(
    decision_id=decision_id,
    signal_dir='LONG',
    action='PLACE',
    S_long=0.85,
    S_short=0.35,
    pred_bps=12.5,
    entry_px=96500.0,
    cluster={'target_width_pct': 0.25, 'intensity_z': 3.2},
    costs={'edge_bps': 12.5}
)

# 2. Order
hub.emit_order(
    order_id=order_id,
    decision_id=decision_id,
    side='BUY',
    px=96500.0,
    qty=0.1
)

# 3. Fill
hub.emit_fill(
    fill_id='fill_001',
    order_id=order_id,
    px=96520.0,
    qty=0.1,
    pnl_close=180.0,
    fee=2.4,
    r_multiple=2.8,
    hold_duration_s=320.0,
    exit_type='tp1'
)

hub.flush()

# 4. Export artifacts
artifacts = export_all(run_id=run_id, events_dir='./logs/events')
print(f"Generated: {list(artifacts.keys())}")
```

## Running the Integration

```bash
# Method 1: Environment variable
export EXPORT_BACKTEST_ARTIFACTS=1
python enhanced_trading_bot.py --mode PAPER

# Method 2: CLI flag
python enhanced_trading_bot.py --mode PAPER --export-artifacts

# Method 3: Standalone export
python backtest_artifacts_exporter.py --run-id r_12345 --events-dir logs/events

# Method 4: Test example
python example_integration.py
```

## Verification Checklist

After integration, verify:

- [ ] decision.jsonl contains decision_id, signal_dir, S_long, S_short, pred_bps
- [ ] order.jsonl contains order_id, decision_id (linkage)
- [ ] fill.jsonl contains fill_id, order_id (linkage), pnl_close, fee
- [ ] trade_log.csv generated with >0 rows
- [ ] equity.csv generated with cumulative equity
- [ ] signals.csv generated with 5-minute bars
- [ ] trade_summary.csv generated with cluster/cost analysis
- [ ] All timestamps in IST (UTC+5:30)
- [ ] No fabricated data (only real events)

## Done!

You now have a complete, production-ready backtest artifact export system integrated into your trading bot.
