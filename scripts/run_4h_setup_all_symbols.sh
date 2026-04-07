#!/bin/bash
# ══════════════════════════════════════════════════════════════════════
# 4H Setup Pipeline — All 16 Symbols
# Run on server: bash scripts/run_4h_setup_all_symbols.sh
# ══════════════════════════════════════════════════════════════════════
set -e
cd /home/ubuntu/tradingview_webhook_bot

echo "======================================================"
echo " STEP 1/3: Download 4H data for all 16 symbols"
echo "======================================================"
cd scripts
python3 fetch_4h_data_all_symbols.py

echo ""
echo "======================================================"
echo " STEP 2/3: Run tournament on 4H data (all 16 symbols)"
echo "======================================================"
python3 tournament_4h_all_symbols.py

echo ""
echo "======================================================"
echo " STEP 3/3: Generate backtest CSVs from results"
echo "======================================================"
python3 generate_backtest_csvs_4h.py 2>/dev/null || echo "Skipping CSV gen (optional)"

echo ""
echo "======================================================"
echo " DONE! Results saved to:"
echo "   storage/reports/tournament_winners_4h.csv"
echo ""
echo " Next steps:"
echo "   1. Open TradingView → 4H chart → any of 16 symbols"
echo "   2. Load strategies/supertrend_4h_universal.pine"
echo "   3. Load strategies/squeeze_flow_4h_universal.pine"
echo "   4. Load strategies/full_momentum_4h_universal.pine"
echo "   5. Check Strategy Tester → if profitable → add alert"
echo "======================================================"
