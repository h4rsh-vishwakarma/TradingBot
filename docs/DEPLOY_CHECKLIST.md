# Deploy Checklist — Post-Governance-Change Verification

Run this checklist after every governance change (manifest update, service config change, env_var rotation, code deploy).

---

## 1. Git State

- [ ] `git status` — no uncommitted changes on server
- [ ] `git rev-parse HEAD` matches GitHub `main` HEAD
- [ ] Local HEAD = Remote HEAD (verify with `git fetch && git status`)

**Command:**
```bash
git rev-parse HEAD && git fetch && git status
```

---

## 2. Service Health

- [ ] `tradingbot-webhook.service` is active
- [ ] `tradingbot-orchestrator.service` is active
- [ ] `trading_dashboard.service` is active

**Command:**
```bash
systemctl is-active tradingbot-webhook.service tradingbot-orchestrator.service trading_dashboard.service
```

---

## 3. Manifest Integrity

- [ ] Manifest loads without error
- [ ] Manifest version matches expected (e.g., v30)
- [ ] `approved_strategies.json` is valid JSON

**Command:**
```bash
python3 -c "import json; d=json.load(open('config/approved_strategies.json')); print('v'+str(d['version']), 'approvals:', len(d['approvals']))"
```

---

## 4. Heartbeat Verification

- [ ] Trigger heartbeat and confirm no unexpected issues
- [ ] P07_NOMINEE shows correct `paper_window_status` (ACTIVE/NOT_STARTED)
- [ ] System State block shows correct Repo HEAD + manifest version

**Command:**
```bash
python3 scripts/hourly_heartbeat_report.py 2>&1 | tail -5
ls -t storage/reports/heartbeat/ | head -1 | xargs -I{} sh -c 'grep "P07 Paper\|System State\|Repo HEAD\|Verdict\|Status:" storage/reports/heartbeat/{}'
```

---

## 5. Execution Freeze Baseline

- [ ] Run freeze check and confirm `status=none`
- [ ] If diff detected: document each changed file as authorized before refreshing

**Command:**
```bash
python3 scripts/check_execution_freeze.py
# If changes are authorized:
# echo "GOVERNANCE_NOTE: <reason>" >> storage/reports/paper_validation/execution_freeze.log
# python3 scripts/check_execution_freeze.py --refresh-baseline
```

---

## 6. Signal Pipeline (if webhook/env changed)

- [ ] Signal DB exists and has tables
- [ ] Last signal timestamp is within expected range
- [ ] Auth secret in env_vars matches what TradingView is sending

**Command:**
```bash
python3 -c "
import sqlite3; from pathlib import Path
db = Path('tradingview_webhook_bot/storage/signal_queue.db')
print('size:', db.stat().st_size if db.exists() else 'MISSING')
if db.exists():
    with sqlite3.connect(str(db)) as c:
        row = c.execute('SELECT COUNT(*), MAX(created_at) FROM signals').fetchone()
        print('total:', row[0], 'latest:', row[1])
"
```

---

## 7. Paper Window (if manifest changed)

- [ ] Confirm `paper_window_status` is correct for all P07_NOMINEE entries
- [ ] Confirm `paper_window_start` timestamp is set for ACTIVE nominees
- [ ] Paper watchdog will alert if no signal received in 24h

**Command:**
```bash
python3 -c "
import json
d=json.load(open('config/approved_strategies.json'))
for a in d['approvals']:
    if a.get('label')=='P07_NOMINEE':
        print(a['strategy'], '|', a.get('paper_window_status'), '|', a.get('paper_window_start'))
"
```

---

## 8. Position Ledger (if execution config changed)

- [ ] No unexpected open positions
- [ ] All stale testnet positions are quarantined

**Command:**
```bash
python3 -c "
import json
l=json.load(open('tradingview_webhook_bot/storage/ledger_state.json'))
for k,v in l.get('positions',{}).items():
    if (v.get('quantity') or 0) != 0:
        print(k, 'qty:', v['quantity'], 'avg:', v.get('avg_price'))
"
```

---

## Governance Change Log

| Date | Change | Verified by | Baseline refreshed |
|------|--------|-------------|-------------------|
| 2026-05-06 | Manifest v30: Donchian_40 paper ACTIVE | Harsh | Yes |
| 2026-05-07 | P-04: baseline refresh (manifest+webhook+env authorized) | Harsh | Yes |
| 2026-05-07 | P-05: stale positions zeroed (ETH/BTC/OP pre-governance) | Harsh | N/A |
