# Backtest Artifact Export System - Quick Reference

## ✅ DEPLOYED & TESTED

All components are deployed to ~/trading_bot/ and tested successfully!

---

## 🚀 Quick Start

### Start Bot with Export Enabled
```bash
cd ~/trading_bot
./start_bot_with_export.sh
```

Press Ctrl+C to stop the bot. Artifacts will be automatically generated in ./backtest_artifacts/

---

## 📊 Artifacts Generated

1. **trade_log.csv** - Individual trade records
2. **equity.csv** - Cumulative equity curve
3. **signals.csv** - 5-minute decision signals
4. **trade_summary.csv** - Enhanced trade analytics

---

## 🔧 Manual Export

Export from existing logs:
```bash
python3 backtest_artifacts_exporter.py --run-id my_run_001
```

Custom export:
```bash
python3 backtest_artifacts_exporter.py \
    --run-id my_run_001 \
    --events-dir ./logs/events \
    --out-dir ./my_artifacts \
    --initial-equity 100000
```

---

## 📁 Output Location

Artifacts saved to: **~/trading_bot/backtest_artifacts/**

View artifacts:
```bash
ls -lh backtest_artifacts/
head -5 backtest_artifacts/*.csv
```

---

## ✅ Verification

Test was successful! Generated:
- ✅ trade_log.csv (1 trades)
- ✅ equity.csv (1 records)  
- ✅ signals.csv (1 signals)
- ✅ trade_summary.csv (1 summaries)

All timestamps in Asia/Kolkata (UTC+5:30) ✓
Field alias normalization working ✓
No data fabrication ✓

---

## 📖 Full Documentation

- **SERVER_DEPLOYMENT_COMPLETE.md** - Complete deployment guide
- **BACKTEST_EXPORT_INTEGRATION.md** - Full integration details
- **QUICK_INTEGRATION_GUIDE.md** - Code snippets

---

## Status: READY FOR PRODUCTION ✨
