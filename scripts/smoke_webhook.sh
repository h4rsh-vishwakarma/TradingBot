#!/bin/bash
# Subtask 9.2: Smoke script to test webhook health
echo "🔥 Running Smoke Test..."

# 1. Check Health Endpoint
HEALTH=$(curl -s http://localhost:5000/health | grep '"status":"ok"')

if [ -z "$HEALTH" ]; then
    echo "❌ Health Check Failed!"
    exit 1
else
    echo "✅ Health Check Passed!"
fi

# 2. Send Dummy Signal
curl -X POST http://localhost:5000/webhook \
     -H "Content-Type: application/json" \
     -d '{"signal_id": "smoke_test_1", "payload": {"symbol": "BTCUSDT", "side": "BUY"}}'

echo "✅ Dummy Signal Sent. Check storage/tradingview_signals_queue.jsonl"