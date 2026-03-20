import json
import os
from datetime import datetime, timedelta
from collections import defaultdict

# Calculate 7 days ago
seven_days_ago = datetime.now() - timedelta(days=7)

strategies = [
    "smc_luxalgo",
    "institutional_flow_hybrid", 
    "squeeze_flow_expansion",
    "sma_crossover_9_21",
    "supertrend_btc_4h",
    "obv_wavetrend_scalper"
]

print("="*80)
print(f"7-DAY TRADING ACTIVITY REPORT ({seven_days_ago.strftime('%Y-%m-%d')} to {datetime.now().strftime('%Y-%m-%d')})")
print("="*80)
print()

total_trades = 0
total_pnl = 0
total_wins = 0
total_losses = 0

for strategy in strategies:
    filepath = f"storage/positions_{strategy}.jsonl"
    if not os.path.exists(filepath):
        continue
    
    positions = []
    with open(filepath, 'r') as f:
        for line in f:
            try:
                pos = json.loads(line.strip())
                if pos.get('status') == 'closed':
                    closed_time = pos.get('closed_at', 0)
                    if isinstance(closed_time, (int, float)):
                        closed_dt = datetime.fromtimestamp(closed_time)
                        if closed_dt >= seven_days_ago:
                            positions.append(pos)
            except:
                pass
    
    if not positions:
        continue
    
    wins = [p for p in positions if p.get('pnl', 0) > 0]
    losses = [p for p in positions if p.get('pnl', 0) <= 0]
    pnl = sum(p.get('pnl', 0) for p in positions)
    
    print(f"STRATEGY: {strategy.upper()}")
    print(f"  Total Trades: {len(positions)}")
    print(f"  Wins: {len(wins)} ({len(wins)/len(positions)*100:.1f}%)")
    print(f"  Losses: {len(losses)} ({len(losses)/len(positions)*100:.1f}%)")
    print(f"  Total PnL: ${pnl:.2f}")
    print(f"  Avg Win: ${sum(p['pnl'] for p in wins)/len(wins):.2f}" if wins else "  Avg Win: N/A")
    print(f"  Avg Loss: ${sum(p['pnl'] for p in losses)/len(losses):.2f}" if losses else "  Avg Loss: N/A")
    
    # Show symbols traded
    symbols = defaultdict(int)
    for p in positions:
        symbols[p.get('symbol', 'UNKNOWN')] += 1
    print(f"  Symbols Traded: {dict(symbols)}")
    print()
    
    total_trades += len(positions)
    total_pnl += pnl
    total_wins += len(wins)
    total_losses += len(losses)

print("="*80)
print("OVERALL SUMMARY")
print("="*80)
print(f"Total Trades (All Strategies): {total_trades}")
print(f"Total Wins: {total_wins} ({total_wins/total_trades*100:.1f}%)" if total_trades > 0 else "Total Wins: 0")
print(f"Total Losses: {total_losses} ({total_losses/total_trades*100:.1f}%)" if total_trades > 0 else "Total Losses: 0")
print(f"Total PnL: ${total_pnl:.2f}")
print(f"Avg Profit Per Trade: ${total_pnl/total_trades:.2f}" if total_trades > 0 else "Avg Profit Per Trade: N/A")
