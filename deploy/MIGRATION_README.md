# Server Migration Guide

## Overview

The server structure is being updated to match the repository structure. Both will now use `tradingview-webhook-bot/` as a subdirectory.

## What's Changing

**Before (Server):**
```
~/tradingview-bot/
├── main_enhanced.py
├── core/
├── exchange/
├── utils/
├── storage/
└── alerts/
```

**After (Server & Repo):**
```
~/tradingview-bot/
├── tradingview-webhook-bot/
│   ├── main_enhanced.py
│   ├── core/
│   ├── exchange/
│   ├── utils/
│   ├── storage/
│   └── alerts/
├── strategies/
├── scripts/
├── config/
└── liquidation-heatmap-bot/
```

## Migration Steps (Run ONCE on Server)

### 1. SSH to the server

```bash
ssh ubuntu@13.236.143.201
cd ~/tradingview-bot
```

### 2. Run the migration script

```bash
# Copy the migration script from repo to server
# (From your local machine)
scp -i ~/.ssh/pratik-key-new.pem \
    deploy/migrate-server.sh \
    ubuntu@13.236.143.201:~/tradingview-bot/

# SSH and run it
ssh -i ~/.ssh/pratik-key-new.pem ubuntu@13.236.143.201
cd ~/tradingview-bot
chmod +x migrate-server.sh
./migrate-server.sh
```

### 3. Verify the migration

```bash
ls -la ~/tradingview-bot/
# You should see tradingview-webhook-bot/ directory

ls -la ~/tradingview-bot/tradingview-webhook-bot/
# You should see core/, exchange/, utils/, storage/, alerts/, main_enhanced.py
```

### 4. Deploy latest code

```bash
# From your local machine
cd /path/to/Trading-view-indicators
./deploy/deploy.sh
```

This will:
- Deploy the new structure
- Restart bots with new path: `tradingview-webhook-bot/main_enhanced.py`

## Rollback (If Needed)

If something goes wrong:

```bash
# On server
cd ~
sudo rm -rf tradingview-bot
cp -r tradingview-bot.pre-migration_* tradingview-bot
# Restart bots manually
```

## Verification

After migration, verify:

1. **Directory structure**
   ```bash
   ls -la ~/tradingview-bot/ | grep tradingview-webhook-bot
   ```

2. **Bot processes**
   ```bash
   ps aux | grep main_enhanced.py
   ```

3. **Bot logs**
   ```bash
   tail -f ~/tradingview-bot/logs/bot_institutional_flow_hybrid.log
   ```

## Benefits After Migration

- ✅ Identical structure on repo and server
- ✅ No file path confusion
- ✅ Easier debugging
- ✅ Simpler deployment process
- ✅ Can copy files directly between repo and server

## Files Changed

- `.github/workflows/deploy.yml` - Simplified, no flattening
- `deploy/deploy.sh` - Simplified, no flattening
- `deploy/migrate-server.sh` - New, one-time migration script
