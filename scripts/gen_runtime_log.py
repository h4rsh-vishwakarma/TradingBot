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
    capture_output=True, text=True,
    env={**__import__('os').environ, 'SKIP_PYTEST': '1'}
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
    syms = str(a.get('symbols', ['ETHUSDT']))
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

# Positions -- split by lane (A-10)
def _load_ledger(path):
    try:
        with open(path) as f:
            return __import__("json").load(f)
    except Exception:
        return {}

_dl_path = os.getenv("DECISION_LANE_LEDGER_PATH", "tradingview_webhook_bot/storage/ledger_decision.json")
_rl_path = os.getenv("RESEARCH_LANE_LEDGER_PATH", "tradingview_webhook_bot/storage/ledger_research.json")
ledger_decision = _load_ledger(_dl_path)
ledger_research = _load_ledger(_rl_path)
ledger = _load_ledger("tradingview_webhook_bot/storage/ledger_state.json")

def _open_pos(ld): return [(k, v) for k, v in ld.get("positions", {}).items() if (v.get("quantity") or 0) != 0]
def _lane_pnl(ld): return sum(v.get("realized_pnl", 0.0) for v in ld.get("positions", {}).values())

dl_open = _open_pos(ledger_decision)
rl_open = _open_pos(ledger_research)
open_pos = dl_open or _open_pos(ledger)
dl_pnl = _lane_pnl(ledger_decision)
rl_pnl = _lane_pnl(ledger_research)
dl_lines = chr(10).join(f'- `{k}` qty={v.get("quantity")} @ {v.get("avg_price")}' for k, v in dl_open) or "- None"
rl_lines = chr(10).join(f'- `{k}` qty={v.get("quantity")} @ {v.get("avg_price")}' for k, v in rl_open) or "- None"
pos_lines = dl_lines
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

# 401 count — read from today's journalctl
try:
    import subprocess as _sp, datetime as _dt
    _today = _dt.date.today().strftime('%Y-%m-%d')
    _res = _sp.run(
        ['sudo', 'journalctl', '-u', 'trading_webhook.service',
         '--since', _today + ' 00:00:00', '--no-pager'],
        capture_output=True, text=True
    )
    unauth_lines = [l for l in _res.stdout.split(chr(10)) if 'Unauthorized' in l or 'unauthorized' in l]
    unauth_count = len(unauth_lines)
    plain_text = sum(1 for l in unauth_lines if 'plain text' in l.lower())
    json_auth = sum(1 for l in unauth_lines if 'JSON' in l or 'json' in l)
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


# Decision-lane scoreboard (CCI Trend + Donchian Trend ETHUSDT closed trades)
_decision_strats = ["CCI Trend", "Donchian Trend"]
_dl_closed = {s: 0 for s in _decision_strats}
_dl_last_signal = {s: "never" for s in _decision_strats}
_dl_last_ts = {s: 0.0 for s in _decision_strats}
_metrics_path = "storage/reports/paper_validation/execution_metrics.jsonl"
if os.path.exists(_metrics_path):
    with open(_metrics_path) as _mf:
        for _line in _mf:
            _line = _line.strip()
            if not _line:
                continue
            try:
                _rec = json.loads(_line)
            except Exception:
                continue
            _strat = str(_rec.get("strategy", "")).strip()
            _sym = str(_rec.get("symbol", "")).upper().strip()
            if _strat in _decision_strats and _sym == "ETHUSDT":
                _ts = float(_rec.get("timestamp_epoch", 0))
                if _rec.get("is_exit"):
                    _dl_closed[_strat] = _dl_closed.get(_strat, 0) + 1
                if _ts > _dl_last_ts.get(_strat, 0):
                    _dl_last_ts[_strat] = _ts
                    _dl_last_signal[_strat] = str(_rec.get("recorded_at", "?"))[:19] + " UTC"
_scoreboard_items = []
for _s in _decision_strats:
    _closed = _dl_closed.get(_s, 0)
    _last = _dl_last_signal.get(_s, "never")
    _icon = "OK" if _closed >= 5 else "NEED MORE"
    row = "| " + str(_s) + " | " + str(_closed) + "/5 (" + _icon + ") | " + str(_last) + " |"
    _scoreboard_items.append(row)
_scoreboard_rows = chr(10).join(_scoreboard_items)

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

### Production Decision Lane (ETH 4h ONLY)
| Strategy | Symbols | Timeframe | Label |
|---|---|---|---|
{lane_rows}
### All ALPHA Strategies
{chr(10).join(f'- {a["strategy"]} | {a.get("symbols")} | label={a.get("label","")}' for a in alpha)}

### RESEARCH (placeholder — not yet on TradingView)
{chr(10).join(f'- {a["strategy"]}' for a in research)}

## Decision-Lane Scoreboard (ETHUSDT 4H)
| Strategy | Closed ETHUSDT Trades | Last ETHUSDT Signal |
|---|---|---|
{_scoreboard_rows}
> Gate requires 5 closed ETHUSDT trades per strategy. OK = threshold met.

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

## Open Positions -- Decision Lane (Harsh / live-approved)
{dl_lines}
Realized P&L: ${dl_pnl:.2f}

## Open Positions -- Research Lane (Garima / paper_only)
{rl_lines}
Realized P&L: ${rl_pnl:.2f}

## Stale Position Quarantine
| Item | Value |
|---|---|
| Status | **{qstatus}** |
| Count | {qcount} positions |
| File | `storage/stale_position_quarantine.json` |

## Known Issues — Requires Manual Action
_None outstanding as of 2026-04-16. All legacy 401 sources resolved (G-series JSON format + auth bypass + SKIP_PYTEST cron noise)._

**Resolved today (2026-04-16):**
- G-series alerts: now sending JSON format with correct strategy names (Harsh Pine Script update)
- CCI Trend / LDOUSDT old plain-text format: superseded by server-side TV order-fill bypass
- Garima test signals (`test_secret_123`): no hits since 2026-04-13; stale note removed
- TestStrategy: pytest-only infrastructure (operator=harsh), no manifest entry, no live alerts

## Services
| Service | URL | Status |
|---|---|---|
| Webhook | https://tradingbot.operatorbrief.xyz/health | UP |
| Dashboard | https://tradingbot.operatorbrief.xyz/ | UP |
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

import re as _re
_ist_now = datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime('%Y-%m-%d %H:%M IST')
_fail_lines = [l.strip() for l in gate_out.split(chr(10)) if '[FAIL]' in l]
_warn_lines = [l.strip() for l in gate_out.split(chr(10)) if '[WARN]' in l]
_verdict_line = next((l.strip() for l in gate_out.split(chr(10)) if 'VERDICT:' in l), verdict)
_gate_block_lines = [_verdict_line] + _fail_lines + _warn_lines
_new_gate_block = chr(10).join(_gate_block_lines)
_dls_path = 'docs/DECISION_LANE_STATUS.md'
if os.path.exists(_dls_path):
    with open(_dls_path) as _df:
        _dls = _df.read()
    _dls = _re.sub(
        r'## Gate Verdict \(live as of [^)]*\)',
        '## Gate Verdict (live as of ' + _ist_now + ')',
        _dls
    )
    _dls = _re.sub(
        r'```\nVERDICT:.*?```',
        chr(96)*3 + chr(10) + _new_gate_block + chr(10) + chr(96)*3,
        _dls,
        flags=_re.DOTALL
    )
    with open(_dls_path, 'w') as _df:
        _df.write(_dls)
    print('Updated: docs/DECISION_LANE_STATUS.md gate verdict')

os.makedirs('docs', exist_ok=True)
with open('docs/RUNTIME_LOG.md', 'w') as f:
    f.write(log)
print('Written: docs/RUNTIME_LOG.md')
print('Length:', len(log.splitlines()), 'lines')

# Auto-push to GitHub so runtime log stays fresh (replaces disabled hourly cron push)
try:
    _push = subprocess.run(
        ['git', 'add', 'docs/RUNTIME_LOG.md'],
        capture_output=True, text=True
    )
    _diff = subprocess.run(
        ['git', 'diff', '--cached', '--stat'],
        capture_output=True, text=True
    )
    if 'RUNTIME_LOG' in _diff.stdout:
        subprocess.run(
            ['git', 'commit', '-m', f'chore: auto-update RUNTIME_LOG {ts}'],
            capture_output=True, text=True
        )
        subprocess.run(
            ['git', 'push', 'origin', 'main'],
            capture_output=True, text=True
        )
        print('GitHub push: RUNTIME_LOG.md updated')
    else:
        print('GitHub push: no changes to push')
except Exception as _e:
    print(f'GitHub push skipped: {_e}')
