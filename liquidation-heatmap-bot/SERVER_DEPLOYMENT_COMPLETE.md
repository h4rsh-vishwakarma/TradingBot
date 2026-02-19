# Backtest Artifact Export - Server Deployment Guide

## 🎉 IMPLEMENTATION COMPLETE

The backtest artifact export system has been successfully deployed to the server!

---

## 📁 Files Deployed

### Core Files
- ✅ **backtest_artifacts_exporter.py** - Complete CSV artifact generation pipeline
- ✅ **event_schemas.py** - Enhanced with P0/P1 observability fields
- ✅ **enhanced_trading_bot.py** - Integrated with export functionality
- ✅ **start_bot_with_export.sh** - Startup script with export enabled

### Location
All files are in: `~/trading_bot/`

---

## 🚀 Usage

### Option 1: Start Bot with Export Enabled (Recommended)

```bash
cd ~/trading_bot
./start_bot_with_export.sh
```

This will:
- Start the bot with `EXPORT_BACKTEST_ARTIFACTS=1`
- Generate all 4 CSV artifacts on shutdown (Ctrl+C)
- Save artifacts to `./backtest_artifacts/`

### Option 2: Manual Start with Export

```bash
cd ~/trading_bot
export EXPORT_BACKTEST_ARTIFACTS=1
python3 enhanced_trading_bot.py
```

### Option 3: Run Export on Existing Logs

```bash
cd ~/trading_bot
python3 backtest_artifacts_exporter.py --run-id my_backtest_001
```

### Option 4: Custom Export

```bash
python3 backtest_artifacts_exporter.py \
    --run-id my_run_id \
    --events-dir ./logs/events \
    --out-dir ./my_artifacts \
    --initial-equity 50000
```

---

## 📊 Generated Artifacts

After running the bot with export enabled, you'll find:

```
~/trading_bot/backtest_artifacts/
├── trade_log.csv          # Individual trade execution records
├── equity.csv             # Cumulative equity curve
├── signals.csv            # 5-minute decision signals
└── trade_summary.csv      # Enhanced trade analytics
```

### Artifact Schemas

**trade_log.csv** (7 columns):
- decision_time, exec_time, side, qty, price, pnl_usd, transaction_cost

**equity.csv** (2 columns):
- ts, equity_value

**signals.csv** (6 columns):
- ts, pred_bps, pred_raw, S_top, S_bot, adv20

**trade_summary.csv** (14 columns):
- trade_id, decision_time, exec_time, side, entry_price, exit_price, qty, pnl_usd
- r_multiple, time_in_trade_s, exit_reason, edge_bps_at_entry, cluster_width_bps, cluster_intensity_z

---

## ✅ Verification

### Test the Export System

```bash
cd ~/trading_bot

# Test with existing logs
python3 backtest_artifacts_exporter.py --run-id test_001 --events-dir ./logs/events

# Check generated files
ls -lh backtest_artifacts/

# View sample data
head -5 backtest_artifacts/trade_log.csv
head -5 backtest_artifacts/equity.csv
head -5 backtest_artifacts/signals.csv
```

### Expected Output

```
================================================================================
BACKTEST ARTIFACT EXPORT
Run ID: test_001
Events: ./logs/events
Output: ./backtest_artifacts
================================================================================

[1/4] Generating trade_log.csv...
  ✓ Created ./backtest_artifacts/trade_log.csv (X trades)
[2/4] Generating equity.csv...
  ✓ Created ./backtest_artifacts/equity.csv (X records)
[3/4] Generating signals.csv...
  ✓ Created ./backtest_artifacts/signals.csv (X signals)
[4/4] Generating trade_summary.csv...
  ✓ Created ./backtest_artifacts/trade_summary.csv (X summaries)

================================================================================
EXPORT COMPLETE
================================================================================

Generated artifacts:
  • trade_log            → ./backtest_artifacts/trade_log.csv
  • equity               → ./backtest_artifacts/equity.csv
  • signals              → ./backtest_artifacts/signals.csv
  • trade_summary        → ./backtest_artifacts/trade_summary.csv
```

---

## 🔧 Key Features

✅ **All timestamps in Asia/Kolkata (UTC+5:30)**
✅ **5-minute bar frequency for signals (288 bars/day)**
✅ **Field alias normalization** (pnl_usd ↔ pnl_$ ↔ pnl)
✅ **No data fabrication** - only real events from logs
✅ **Backward compatible** - works with existing event logs
✅ **P0/P1 observability** - enhanced event schemas

---

## 📝 Notes

### Timezone
All timestamps are converted to Asia/Kolkata (UTC+5:30) as specified.

Example: `2025-12-04T15:30:00+05:30`

### Bar Frequency
Signals are normalized to 5-minute bars (288 bars per day) using pandas resampling.

### Field Aliases
The exporter automatically normalizes common field name variants:
- PnL: `pnl_usd`, `pnl_$`, `pnl`, `pnl_close`
- Costs: `transaction_cost`, `cost_$`, `fee_usd`, `fees_usd`, `fee`

### Data Integrity
The system never fabricates data. Missing fields are left as 0.0 or NaN, not invented.

---

## 🐛 Troubleshooting

### Issue: No artifacts generated

**Check**: Is `EXPORT_BACKTEST_ARTIFACTS=1` set?
```bash
echo $EXPORT_BACKTEST_ARTIFACTS
```

**Fix**: Use the startup script or set the variable manually
```bash
export EXPORT_BACKTEST_ARTIFACTS=1
```

### Issue: Empty CSV files

**Check**: Are there events in the logs?
```bash
ls -lh logs/events/
wc -l logs/events/decision.jsonl
wc -l logs/events/order.jsonl
wc -l logs/events/fill.jsonl
```

**Fix**: Run the bot to generate events first

### Issue: Missing fields in CSVs

**Check**: Are decision/order/fill events properly linked?

**Fix**: Ensure decision_id and order_id are populated in events

---

## 📞 Support

For issues or questions:
1. Check the logs: `tail -50 enhanced_bot.log`
2. Test the exporter: `python3 backtest_artifacts_exporter.py --run-id test`
3. Verify event logs exist: `ls -lh logs/events/`

---

## 🎯 Quick Start Checklist

- [x] Files deployed to server
- [x] Exporter tested successfully
- [x] CSV artifacts generated
- [x] Startup script created
- [ ] Run bot with export enabled
- [ ] Verify artifacts after shutdown
- [ ] Analyze CSV files for LLM training

---

## Status: ✅ READY FOR PRODUCTION

All components are deployed, tested, and working correctly!
