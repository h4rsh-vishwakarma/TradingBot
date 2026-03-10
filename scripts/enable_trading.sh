#!/bin/bash
echo "🟢 ENABLING REAL TRADES..."
sudo sed -i 's/ALLOW_REAL_TRADES="false"/ALLOW_REAL_TRADES="true"/' /etc/tradingbot/env_vars
sudo systemctl restart trading_orchestrator
echo "🚀 Trading is now LIVE."
