#!/bin/bash
cd /home/ubuntu/tradingview-webhook-mvp/trading_bot
while true; do
    python3 collect_oi_funding.py
    sleep 300
done
