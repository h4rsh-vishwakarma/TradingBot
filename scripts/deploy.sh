#!/usr/bin/env bash
# deploy.sh — restart services, refresh freeze baseline, run gate check
# Usage: bash scripts/deploy.sh [--skip-pull]

set -euo pipefail
cd /home/ubuntu/tradingview_webhook_bot

echo "=== DEPLOY $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="

if [[ "${1:-}" != "--skip-pull" ]]; then
    echo "[1/5] git pull..."
    git pull origin main
fi

echo "[2/5] Restarting webhook service..."
sudo systemctl restart tradingbot-webhook.service
sleep 3
systemctl is-active tradingbot-webhook.service

echo "[3/5] Restarting orchestrator service..."
sudo systemctl restart tradingbot-orchestrator.service
sleep 3
systemctl is-active tradingbot-orchestrator.service

echo "[4/5] Refreshing execution freeze baseline..."
venv/bin/python3 scripts/check_execution_freeze.py --refresh-baseline

echo "[5/5] Running go-live gate check..."
SKIP_PYTEST=1 venv/bin/python3 scripts/go_live_gate_check.py

echo "=== DEPLOY COMPLETE ==="
