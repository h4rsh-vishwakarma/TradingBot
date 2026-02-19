# Deployment Guide

## Overview

This project now has automated deployment capabilities to sync code from local development to the production server.

## Deployment Methods

### Method 1: Manual Deployment (Recommended for First Time)

```bash
# From the project root
./deploy/deploy.sh
```

**What it does:**
1. ✅ Checks for uncommitted changes
2. ✅ Creates backup on server
3. ✅ Stops running bots gracefully
4. ✅ Deploys new code
5. ✅ Restarts all bots
6. ✅ Verifies deployment

**Safety Features:**
- Automatic backup before deployment
- Graceful bot shutdown (no lost trades)
- Verification after deployment
- Shows recent logs

### Method 2: GitHub Actions CI/CD

**Setup Required:**

1. Add SSH private key to GitHub Secrets:
   - Go to: Repository → Settings → Secrets and variables → Actions
   - Add new secret: `SSH_PRIVATE_KEY`
   - Paste contents of `~/.ssh/pratik-key-new.pem`

2. Enable GitHub Actions:
   - Push to `main` branch → Auto-deploys
   - Or manually trigger from Actions tab

## Server Information

| Property | Value |
|----------|-------|
| **IP** | 13.236.143.201 |
| **User** | ubuntu |
| **Region** | ap-southeast-2 (Sydney) |
| **Path** | ~/tradingview-bot |
| **SSH Key** | ~/.ssh/pratik-key-new.pem |

## Quick SSH Commands

```bash
# SSH to server
ssh -i ~/.ssh/pratik-key-new.pem ubuntu@13.236.143.201

# Check running bots
ssh -i ~/.ssh/pratik-key-new.pem ubuntu@13.236.143.201 "ps aux | grep main_enhanced"

# View logs
ssh -i ~/.ssh/pratik-key-new.pem ubuntu@13.236.143.201 "tail -f ~/tradingview-bot/logs/bot_institutional_flow_hybrid.log"

# Check disk space
ssh -i ~/.ssh/pratik-key-new.pem ubuntu@13.236.143.201 "df -h"
```

## Project Structure

```
tradingview-bot/
├── config/                 # Strategy configurations
│   ├── config_institutional_flow_hybrid.json
│   ├── config_institutional_matrix.json
│   ├── config_obv_wavetrend_scalper.json
│   ├── config_sma_crossover_9_21.json
│   ├── config_smc_luxalgo.json
│   └── config_supertrend_btc_4h.json
├── core/                   # Core trading logic
├── exchange/               # Exchange integrations
├── utils/                  # Utilities
├── storage/                # Data storage
├── logs/                   # Bot logs
├── main_enhanced.py        # Main bot entry point
└── requirements.txt        # Python dependencies
```

## Deployment Checklist

Before deploying:

- [ ] Test changes locally
- [ ] Commit all changes to git
- [ ] Create backup of critical configs
- [ ] Check server has enough disk space
- [ ] Verify no active trades in progress

After deploying:

- [ ] Verify bots are running
- [ ] Check logs for errors
- [ ] Monitor first 10 minutes
- [ ] Verify signals are being processed

## Troubleshooting

### Deployment Failed

```bash
# Check backup and restore
ssh -i ~/.ssh/pratik-key-new.pem ubuntu@13.236.143.201
ls -la ~/tradingview-bot.backup_*
# Restore if needed
cp -r ~/tradingview-bot.backup_YYYYMMDD_HHMMSS ~/tradingview-bot
```

### Bots Not Starting

```bash
# Check logs
ssh -i ~/.ssh/pratik-key-new.pem ubuntu@13.236.143.201
tail -50 ~/tradingview-bot/logs/bot_*.log

# Restart manually
cd ~/tradingview-bot
source venv/bin/activate
python main_enhanced.py --config config/config_institutional_flow_hybrid.json
```

## Server Status Monitoring

```bash
# Quick health check
ssh -i ~/.ssh/pratik-key-new.pem ubuntu@13.236.143.201 << 'EOF'
  echo "=== System Uptime ==="
  uptime
  echo ""
  echo "=== Disk Space ==="
  df -h /
  echo ""
  echo "=== Memory ==="
  free -h
  echo ""
  echo "=== Running Bots ==="
  ps aux | grep main_enhanced | grep -v grep | wc -l
EOF
```

## Rollback Procedure

If something goes wrong after deployment:

```bash
# SSH to server
ssh -i ~/.ssh/pratik-key-new.pem ubuntu@13.236.143.201

# Stop current deployment
pkill -f main_enhanced.py

# Restore from backup
cp -r ~/tradingview-bot.backup_YYYYMMDD_HHMMSS/* ~/tradingview-bot/

# Restart bots
cd ~/tradingview-bot
source venv/bin/activate
for config in config/config_*.json; do
  python main_enhanced.py --config "$config" &
done
```
