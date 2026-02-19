#!/bin/bash
###############################################################################
# Server Migration Script
# Migrates server from flat structure to organized structure
# Run this ONCE on the server to reorganize files
###############################################################################

set -e

echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║         SERVER STRUCTURE MIGRATION                                  ║"
echo "║         Migrating from flat to organized structure                   ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""

# Check if we're on the server
if [ ! -d "$HOME/tradingview-bot" ]; then
    echo "❌ Error: tradingview-bot directory not found"
    echo "   This script must be run on the production server"
    exit 1
fi

cd ~/tradingview-bot

# Check if migration already done
if [ -d "tradingview-webhook-bot" ]; then
    echo "⚠️  tradingview-webhook-bot directory already exists"
    echo "   Migration may have already been run"
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Migration cancelled"
        exit 0
    fi
fi

echo "📦 Current structure:"
ls -d core/ exchange/ utils/ storage/ alerts/ 2>/dev/null | sed 's|^|  │|'
echo ""

# Create backup
BACKUP_DIR="$HOME/tradingview-bot.pre-migration_$(date +%Y%m%d_%H%M%S)"
echo ""
echo "📋 Creating backup: $BACKUP_DIR"
cp -r ~/tradingview-bot "$BACKUP_DIR"

echo ""
echo "🚀 Starting migration..."
echo ""

# Create tradingview-webhook-bot directory
echo "1. Creating tradingview-webhook-bot/ directory..."
mkdir -p tradingview-webhook-bot

# Move directories
echo "2. Moving TradingView bot modules..."
if [ -d "core" ]; then
    echo "   → core/"
    mv core tradingview-webhook-bot/
fi

if [ -d "exchange" ]; then
    echo "   → exchange/"
    mv exchange tradingview-webhook-bot/
fi

if [ -d "utils" ]; then
    echo "   → utils/"
    mv utils tradingview-webhook-bot/
fi

if [ -d "storage" ]; then
    echo "   → storage/"
    mv storage tradingview-webhook-bot/
fi

if [ -d "alerts" ]; then
    echo "   → alerts/"
    mv alerts tradingview-webhook-bot/
fi

if [ -f "main_enhanced.py" ]; then
    echo "   → main_enhanced.py"
    mv main_enhanced.py tradingview-webhook-bot/
fi

# Move dashboard scripts
if [ -f "update_live_dashboard.py" ]; then
    echo "   → update_live_dashboard.py"
    mv update_live_dashboard.py tradingview-webhook-bot/
fi

if [ -f "update_institutional_flow_hybrid_dashboard.py" ]; then
    echo "   → update_institutional_flow_hybrid_dashboard.py"
    mv update_institutional_flow_hybrid_dashboard.py tradingview-webhook-bot/
fi

echo ""
echo "3. Verifying new structure..."
echo ""
echo "   tradingview-webhook-bot/"
ls -1 tradingview-webhook-bot/ | sed 's|^|     ├──|'
echo ""

echo "✅ Migration complete!"
echo ""
echo "📊 Summary:"
echo "   • Old structure backed up to: $BACKUP_DIR"
echo "   • New structure: ~/tradingview-bot/tradingview-webhook-bot/"
echo ""
echo "🔄 Next steps:"
echo "   1. Update any scripts that reference old paths"
echo "   2. Restart bots using new path: tradingview-webhook-bot/main_enhanced.py"
echo "   3. Verify bots are running correctly"
echo ""
echo "   To rollback if needed:"
echo "   sudo rm -rf ~/tradingview-bot"
echo "   cp -r $BACKUP_DIR ~/tradingview-bot"
echo ""
