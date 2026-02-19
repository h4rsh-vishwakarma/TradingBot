#!/bin/bash
###############################################################################
# TradingView Bot Deployment Script
# Deploys code from local to production server safely
###############################################################################

set -e  # Exit on error

# Configuration
SERVER_USER="ubuntu"
SERVER_IP="13.236.143.201"
SERVER_PATH="~/tradingview-bot"
SSH_KEY="$HOME/.ssh/pratik-key-new.pem"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if SSH key exists
if [ ! -f "$SSH_KEY" ]; then
    log_error "SSH key not found at $SSH_KEY"
    log_info "Please ensure the key exists or update SSH_KEY variable"
    exit 1
fi

# Pre-deployment checks
log_info "🔍 Pre-deployment checks..."

# Check if git has uncommitted changes
if [ -n "$(git status --porcelain)" ]; then
    log_warn "You have uncommitted changes:"
    git status --short
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "Deployment cancelled"
        exit 1
    fi
fi

# Check if we're on main branch
CURRENT_BRANCH=$(git branch --show-current)
if [ "$CURRENT_BRANCH" != "main" ]; then
    log_warn "Not on main branch (current: $CURRENT_BRANCH)"
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "Deployment cancelled"
        exit 1
    fi
fi

# Deployment
log_info "🚀 Starting deployment to $SERVER_IP..."

# Create temp directory on server
log_info "Creating temp directory..."
ssh -i "$SSH_KEY" "$SERVER_USER@$SERVER_IP" "mkdir -p /tmp/tradingview-deploy"

# Copy files to temp directory
log_info "Copying files to server..."
rsync -avz --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='logs/' \
    --exclude='storage/*.jsonl' \
    --exclude='storage/*.db' \
    --exclude='.env' \
    --exclude='aws-configs/' \
    --exclude='.claude/' \
    --exclude='*.local.backup' \
    --exclude='*.server.backup' \
    -e "ssh -i $SSH_KEY" \
    ./ "$SERVER_USER@$SERVER_IP:/tmp/tradingview-deploy/"

# Stop bots gracefully (using sudo for root processes)
log_info "Stopping running bots..."
ssh -i "$SSH_KEY" "$SERVER_USER@$SERVER_IP" "
    cd ~/tradingview-bot
    # Find all running bot processes and send SIGTERM (using sudo for root processes)
    sudo pkill -TERM -f 'main_enhanced.py' || true
    sleep 3
    # Force kill if still running
    sudo pkill -KILL -f 'main_enhanced.py' || true
    sleep 2
    echo 'Bots stopped'
"

# Backup current deployment
log_info "Backing up current deployment..."
BACKUP_DIR="$SERVER_PATH.backup_$(date +%Y%m%d_%H%M%S)"
ssh -i "$SSH_KEY" "$SERVER_USER@$SERVER_IP" "cp -r ~/tradingview-bot $BACKUP_DIR"

# Deploy new files
log_info "Deploying new files..."
ssh -i "$SSH_KEY" "$SERVER_USER@$SERVER_IP" "
    cd /tmp/tradingview-deploy

    # Move TradingView bot files to root (for server compatibility)
    if [ -d 'tradingview-webhook-bot' ]; then
      echo '📦 Restructuring TradingView bot for server...'
      cp -r tradingview-webhook-bot/* ./
      cp -r tradingview-webhook-bot/core ./
      cp -r tradingview-webhook-bot/exchange ./
      cp -r tradingview-webhook-bot/utils ./
      cp -r tradingview-webhook-bot/storage ./
      cp -r tradingview-webhook-bot/alerts ./
      cp tradingview-webhook-bot/main_enhanced.py ./
    fi

    rsync -av --exclude='tradingview-webhook-bot' --exclude='.git' \
        --exclude='__pycache__' --exclude='*.pyc' \
        --exclude='logs/' --exclude='storage/' --exclude='.env' \
        ./ ~/tradingview-bot/
    rm -rf /tmp/tradingview-deploy
"

# Restart bots
log_info "Restarting bots..."
ssh -i "$SSH_KEY" "$SERVER_USER@$SERVER_IP" "
    cd ~/tradingview-bot
    source venv/bin/activate

    BOT_COUNT=0
    for config in config/config_*.json; do
      if [ -f \"\$config\" ]; then
        strategy_name=\$(basename \"\$config\" .json | sed 's/config_//')
        echo \"  → Starting \$strategy_name\"
        nohup python main_enhanced.py --config \"\$config\" > \"logs/bot_\${strategy_name}.log\" 2>&1 &
        BOT_COUNT=\$((BOT_COUNT + 1))
      fi
    done
    echo \"Started \$BOT_COUNT bots\"
"

# Verify deployment
log_info "Verifying deployment..."
sleep 3
BOT_COUNT=$(ssh -i "$SSH_KEY" "$SERVER_USER@$SERVER_IP" "ps aux | grep 'main_enhanced.py' | grep -v grep | wc -l")

log_info "✅ Deployment completed!"
log_info "📊 Active bots: $BOT_COUNT"
log_info "💾 Backup location: $BACKUP_DIR"

# Show recent logs
log_info "📋 Recent logs:"
ssh -i "$SSH_KEY" "$SERVER_USER@$SERVER_IP" "tail -10 ~/tradingview-bot/logs/bot_institutional_flow_hybrid.log"

# Fix permissions for logs and storage (important after deployment)
log_info "Fixing permissions..."
ssh -i "$SSH_KEY" "$SERVER_USER@$SERVER_IP" "
    cd ~/tradingview-bot
    sudo chown -R ubuntu:ubuntu logs/ storage/ 2>/dev/null || true
    sudo chmod -R 755 logs/ storage/ 2>/dev/null || true
"
