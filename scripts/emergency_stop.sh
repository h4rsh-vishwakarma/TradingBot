#!/bin/bash
echo "🚨 EMERGENCY STOP TRIGGERED..."

# Set ALLOW_REAL_TRADES to false in the env file
sudo sed -i 's/ALLOW_REAL_TRADES="true"/ALLOW_REAL_TRADES="false"/' /etc/tradingbot/env_vars

# Restart the orchestrator to apply changes
sudo systemctl restart trading_orchestrator

echo "🛑 Trading has been DISABLED. Check logs for confirmation."
journalctl -u trading_orchestrator -n 101~#!/bin/bash

