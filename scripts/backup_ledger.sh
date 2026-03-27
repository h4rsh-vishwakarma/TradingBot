#!/bin/bash
BD=/home/ubuntu/tradingview_webhook_bot/backups
mkdir -p $BD
D=$(date +%Y%m%d_%H%M%S)
cp /home/ubuntu/tradingview_webhook_bot/tradingview_webhook_bot/storage/ledger_state.json $BD/ledger_$D.json
cp /home/ubuntu/tradingview_webhook_bot/tradingview_webhook_bot/storage/signal_queue.db $BD/queue_$D.db 2>/dev/null
find $BD -mtime +7 -delete 2>/dev/null
echo backup:$D
