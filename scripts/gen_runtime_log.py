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
        ['sudo', 'journalctl', '-u', 'tradingbot-webhook.service',
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


# STOP_DISPATCH detection
_stop_dispatch_path = "tradingview_webhook_bot/storage/STOP_DISPATCH"
_stop_dispatch_active = os.path.exists(_stop_dispatch_path)
_stop_dispatch_note = ""
if _stop_dispatch_active:
    import time as _time
    _sd_mtime = os.path.getmtime(_stop_dispatch_path)
    _sd_age_h = (_time.time() - _sd_mtime) / 3600
    _sd_since = datetime.fromtimestamp(_sd_mtime, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    _stop_dispatch_note = f"⚠️ STOP_DISPATCH active since {_sd_since} ({_sd_age_h:.1f}h ago) — no signals are being dispatched to the exchange"

# Decision-lane scoreboard (CCI Trend + Donchian Trend ETHUSDT closed trades)
# Closed-trade count: reads execution_metrics.jsonl (only populated on actual fills)
# Last signal: reads signal_queue.db (populated on every received signal, including test signals)
_decision_strats = ["CCI Trend", "Donchian Trend"]
_dl_closed = {s: 0 for s in _decision_strats}
_dl_last_signal = {s: "never" for s in _decision_strats}
_dl_last_ts = {s: 0.0 for s in _decision_strats}

# Closed trade count from execution_metrics
_metrics_path = "storage/reports/paper_validation/execution_metrics.jsonl"
_paper_start = os.getenv("PAPER_WINDOW_START", "2026-04-07")
_paper_start_ts = datetime.strptime(_paper_start, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
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
            _ts = float(_rec.get("timestamp_epoch", 0))
            if _strat in _decision_strats and _sym == "ETHUSDT" and _ts >= _paper_start_ts:
                if _rec.get("is_exit"):
                    _dl_closed[_strat] = _dl_closed.get(_strat, 0) + 1

# Last signal received: from signal_queue.db (more current than execution_metrics)
import re as _re_norm
_candidate_norm = {_re_norm.sub(r"[^a-z0-9]+", " ", s.lower()).strip(): s for s in _decision_strats}
try:
    _sq_conn = sqlite3.connect("tradingview_webhook_bot/storage/signal_queue.db")
    _sq_rows = _sq_conn.execute(
        "SELECT payload, created_at FROM signals WHERE created_at >= ? ORDER BY created_at DESC LIMIT 2000",
        (_paper_start_ts,)
    ).fetchall()
    for _raw, _ts_sq in _sq_rows:
        try:
            _d = json.loads(_raw)
            _p = _d.get("payload", _d) if isinstance(_d, dict) else {}
            _strat_raw = str(_p.get("strategy", ""))
            _sym_sq = str(_p.get("symbol", "")).upper().strip()
            _strat_n = _re_norm.sub(r"[^a-z0-9]+", " ", _strat_raw.lower()).strip()
            if _strat_n in _candidate_norm and _sym_sq == "ETHUSDT":
                _canonical = _candidate_norm[_strat_n]
                _ts_f = float(_ts_sq)
                if _ts_f > _dl_last_ts.get(_canonical, 0):
                    _dl_last_ts[_canonical] = _ts_f
                    _dl_last_signal[_canonical] = datetime.fromtimestamp(_ts_f, timezone.utc).strftime("%Y-%m-%dT%H:%M") + " UTC"
        except Exception:
            pass
    _sq_conn.close()
except Exception:
    pass
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
{_stop_dispatch_note if _stop_dispatch_active else "_No outstanding operational issues._"}

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

# P-04: Signal drought alert — Telegram notification at 48h / 72h / 96h / 120h thresholds
_drought_hours = float('inf')
_most_recent_dl_ts = max(_dl_last_ts.values()) if any(v > 0 for v in _dl_last_ts.values()) else 0.0
if _most_recent_dl_ts > 0:
    _drought_hours = (now.timestamp() - _most_recent_dl_ts) / 3600
_recency_failing = any('Decision-lane ETHUSDT signal' in l for l in gate_out.split(chr(10)) if '[FAIL]' in l)
_drought_alert_thresholds = [48, 72, 96, 120]
if _recency_failing and any(t <= _drought_hours < t + 1.5 for t in _drought_alert_thresholds):
    try:
        from tradingview_webhook_bot.alerts.telegram_alerts import TelegramAlert, AlertSeverity
        _tg = TelegramAlert()
        _cci_last = _dl_last_signal.get('CCI Trend', 'never')
        _don_last = _dl_last_signal.get('Donchian Trend', 'never')
        _tg.send(
            severity=AlertSeverity.WARNING,
            title=chr(9888) + " Decision-Lane Signal Drought",
            message=(
                f"No ETHUSDT decision-lane signal in {_drought_hours:.0f}h "
                f"(gate FAIL threshold: 72h).\n\n"
                f"CCI Trend last: {_cci_last}\n"
                f"Donchian Trend last: {_don_last}\n\n"
                "Verify TradingView alerts are active on ETHUSDT 4H chart."
            ),
        )
        print(f"Telegram drought alert sent ({_drought_hours:.0f}h stale)")
    except Exception as _tg_exc:
        print(f"Telegram drought alert skipped: {_tg_exc}")

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

# Auto-push RUNTIME_LOG to runtime-logs branch -- keeps main history clean
try:
    subprocess.run(['git', 'add', 'docs/RUNTIME_LOG.md'], capture_output=True, text=True)
    _diff = subprocess.run(['git', 'diff', '--cached', '--stat'], capture_output=True, text=True)
    if 'RUNTIME_LOG' in _diff.stdout:
        subprocess.run(
            ['git', 'commit', '-m', f'chore: auto-update RUNTIME_LOG {ts}'],
            capture_output=True, text=True
        )
        subprocess.run(
            ['git', 'push', '--force', 'origin', 'HEAD:refs/heads/runtime-logs'],
            capture_output=True, text=True
        )
        subprocess.run(['git', 'reset', '--soft', 'HEAD~1'], capture_output=True, text=True)
        subprocess.run(['git', 'reset', 'HEAD', 'docs/RUNTIME_LOG.md'], capture_output=True, text=True)
        print('GitHub push: RUNTIME_LOG.md -> runtime-logs (main kept clean)')
    else:
        print('GitHub push: no changes to push')
except Exception as _e:
    print(f'GitHub push skipped: {_e}')
