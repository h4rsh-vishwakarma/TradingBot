#!/bin/bash
# Sync signals from backtest_artifacts to logs/backtests
mkdir -p logs/backtests
if [ -f backtest_artifacts/signals.csv ]; then
    cp backtest_artifacts/signals.csv logs/backtests/signals_live.csv
fi
