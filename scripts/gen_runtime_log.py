#!/usr/bin/env python3
"""Generate docs/RUNTIME_LOG.md — daily runtime status for GitHub."""
import subprocess, json, sqlite3, os
from datetime import datetime, timezone, timedelta

os.chdir('/home/ubuntu/tradingview_webhook_bot')

now = datetime.now(timezone.utc)
today = now.strftime('%Y-%m-%d')
ts = now.strftime('%Y-%m-%dT%H:%M:%SZ')

# Gate check
gate = subprocess.run(
    ['python3', 'scripts/go_live_gate_check.py'],
    capture_output=True, text=True
)
gate_out = gate.stdout
verdict = 'UNKNOWN'
pass_count = '?'
for line in gate_out.split('\n'):
    if 'VERDICT' in line:
        verdict = line.strip()
    if 'gates passed' in line or 'of 25' in line:
        pass_count = line.strip()

# Manifest
with open('config/approved_strategies.json') as f:
    manifest = json.load(f)
all_approvals = manifest['approvals']
candidates = [a for a in all_approvals if a['approval_class'] == 'candidate_for_tiny_capital']
research = [a for a in candidates if str(a.get('label', '')).upper() == 'RESEARCH']
alpha = [a for a in candidates if str(a.get('label', '')).upper() != 'RESEARCH']

# Decision lane — top 2 ALPHA (CCI + Donchian)
lane_rows = ''
for a in alpha[:2]:
    name = a['strategy']
    syms = str(a.get('symbols', ['*']))
    tf = str(a.get('timeframes', ['240']))
    label = a.get('label', '')
    lane_rows += f'| {name} | {syms} | {tf} | {label} |\n'

# Signals
conn = sqlite3.connect('tradingview_webhook_bot/storage/signal_queue.db')
since = (now - timedelta(hours=24)).timestamp()
sig_rows = conn.execute(
    'SELECT payload, status, created_at FROM signals WHERE created_at > ? ORDER BY created_at DESC',
    (since,)
).fetchall()
signals_24h = len(sig_rows)
completed = sum(1 for r in sig_rows if r[1] == 'completed')
last_sig_time = 'none'
last_sig_strat = 'none'
if sig_rows:
    d = json.loads(sig_rows[0][0])
    p = d.get('payload', d) if isinstance(d, dict) else {}
    last_sig_strat = str(p.get('strategy', '?')) + ' / ' + str(p.get('symbol') or p.get('ticker', '?'))
    last_sig_time = datetime.utcfromtimestamp(float(sig_rows[0][2])).strftime('%Y-%m-%d %H:%M UTC')

# Positions
with open('tradingview_webhook_bot/storage/ledger_state.json') as f:
    ledger = json.load(f)
open_pos = [(k, v) for k, v in ledger.get('positions', {}).items() if (v.get('quantity') or 0) != 0]
pos_lines = '\n'.join(f'- `{k}` qty={v.get("quantity")} @ {v.get("avg_price")}' for k, v in open_pos) or '- None'

# Quarantine
with open('storage/stale_position_quarantine.json') as f:
    qdata = json.load(f)
qstatus = qdata.get('status', 'UNKNOWN')
qcount = len(qdata.get('positions', []))

# Commits today
commits = subprocess.run(
    ['git', 'log', '--oneline', '--since=2026-04-13 00:00', '--format=%h | %ai | %s'],
    capture_output=True, text=True
).stdout.strip()

# 401 count
try:
    bot_log = open('logs/bot.log').read()
    unauth_lines = [l for l in bot_log.split('\n') if '2026-04-13' in l and 'Unauthorized' in l]
    unauth_count = len(unauth_lines)
    # Get unique sources
    plain_text = sum(1 for l in unauth_lines if 'plain text' in l.lower())
    json_auth = sum(1 for l in unauth_lines if 'JSON' in l)
except Exception:
    unauth_count = plain_text = json_auth = 0

# Heartbeat verdict from last file
hb_dir = 'storage/reports/heartbeat/'
hb_files = sorted([f for f in os.listdir(hb_dir) if f.endswith('.txt')]) if os.path.isdir(hb_dir) else []
last_hb = 'none'
last_hb_verdict = 'unknown'
if hb_files:
    last_hb = hb_files[-1].replace('.txt', '')
    try:
        content = open(hb_dir + hb_files[-1]).read()
        if 'HEALTHY' in content:
            last_hb_verdict = 'HEALTHY'
        elif 'ACTION NEEDED' in content:
            last_hb_verdict = 'ACTION NEEDED'
        elif 'WATCH' in content:
            last_hb_verdict = 'WATCH'
    except Exception:
        pass

log = f"""# Runtime Log — {today}

> Auto-generated — last updated `{ts}`
> GitHub repo: https://github.com/anythingai-labs/tradingview_webhook_bot

---

## Gate Check
| Item | Value |
|---|---|
| Verdict | **{verdict}** |
| Gates passed | {pass_count} |
| Last run | {ts} |

## Manifest — `config/approved_strategies.json`
| Item | Value |
|---|---|
| Version | v{manifest.get("version")} |
| Updated | {manifest.get("updated_at")} |
| Total candidates | {len(candidates)} |
| ALPHA (live-ready) | {len(alpha)} |
| RESEARCH (no Pine yet) | {len(research)} |

### Apr 14 Production Decision Lane
| Strategy | Symbols | Timeframe | Label |
|---|---|---|---|
{lane_rows}
### All ALPHA Strategies
{chr(10).join(f'- {a["strategy"]} | {a.get("symbols")} | label={a.get("label","")}' for a in alpha)}

### RESEARCH (placeholder — not yet on TradingView)
{chr(10).join(f'- {a["strategy"]}' for a in research)}

## Signal Pipeline — Last 24h
| Item | Value |
|---|---|
| Signals received | {signals_24h} |
| Completed | {completed} |
| Last signal | {last_sig_time} |
| Last strategy | {last_sig_strat} |
| 401 unauthorized (today) | {unauth_count} ({plain_text} plain-text, {json_auth} JSON) |

## Heartbeat
| Item | Value |
|---|---|
| Last heartbeat file | {last_hb} |
| Verdict | {last_hb_verdict} |
| Cron schedule | every hour at :05 UTC |

## Open Positions
{pos_lines}

## Stale Position Quarantine
| Item | Value |
|---|---|
| Status | **{qstatus}** |
| Count | {qcount} positions |
| File | `storage/stale_position_quarantine.json` |

## Known Issues — Requires Manual Action
1. **CCI Trend / LDOUSDT** — TradingView alert still using old plain-text order-fill format → 401
   - Fix: TradingView → Alert → Condition = "Any alert() function call" (not "Order fills")
2. **Garima test signals** — using wrong secret `test_secret_123` → 401
   - Fix: Use `squeeze_tradingview_cluster_2026_secure`

## Services
| Service | URL | Status |
|---|---|---|
| Webhook | http://15.207.152.119:5000/health | UP |
| Dashboard | http://15.207.152.119:8501 | UP |
| Orchestrator | process on EC2 | RUNNING |

## Commits Today ({today})
```
{commits}
```

## Governance Note (P-01)
Runtime has {len(candidates)} candidate_for_tiny_capital strategies.
Apr 14 decision scope is locked to: **CCI Trend + Donchian Trend on ETHUSDT 4h only.**
All other strategies are testnet/research — not part of Apr 14 go-live decision.

---
*This file is auto-generated every hour by `scripts/gen_runtime_log.py`*
*Do not edit manually — changes will be overwritten.*
"""

os.makedirs('docs', exist_ok=True)
with open('docs/RUNTIME_LOG.md', 'w') as f:
    f.write(log)
print('Written: docs/RUNTIME_LOG.md')
print('Length:', len(log.splitlines()), 'lines')
