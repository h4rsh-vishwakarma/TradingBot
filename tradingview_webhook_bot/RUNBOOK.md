# Trading Bot Core Module

> **Full runbook and architecture docs are at the project root: [`/RUNBOOK.md`](../RUNBOOK.md)**

## Quick Reference

```bash
# Service status
sudo systemctl status trading_webhook trading_orchestrator

# Live logs
journalctl -u trading_orchestrator -f
journalctl -u trading_webhook -f

# Health check
curl http://127.0.0.1:5000/health

# Emergency stop
python3 scripts/kill_switch.py

# Check positions
cat tradingview_webhook_bot/storage/ledger_state.json | python3 -m json.tool

# Force analytics update
python3 -c 'from tradingview_webhook_bot.storage.analytics_writer import AnalyticsWriter; AnalyticsWriter().update_today()'

# Force tournament rerun
python3 scripts/strategy_tournament.py
```

## Module Layout

```
tradingview_webhook_bot/
  core/
    webhook_server.py     - Flask HTTP receiver (JSON + plain text)
    orchestrator.py       - Signal pipeline with 7 safety gates
  exchange/
    binance_client.py     - Binance Futures execution
    hl_client.py          - Hyperliquid client (optional)
  ledger/
    positions.py          - Position state + PnL tracking
  storage/
    jsonl_queue.py        - Crash-safe append-only signal queue
    sheets_logger.py      - Google Sheets trade logging
    analytics_writer.py   - Auto-updates 3 analytics tabs per trade
    idempotency_store.py  - SQLite duplicate prevention
  alerts/
    telegram_alerts.py    - Trade alerts + heartbeat
  recon/
    reconciler.py         - Binance vs ledger audit
```

Maintained by: AnythingAi Labs
Developed by: Harsh Vishwakarma
Last Updated: March 2026
