#!/usr/bin/env python3
"""
COMPREHENSIVE TRADING BOT STATUS CHECKER
Single script to check everything at once
"""

from binance.client import Client
import json
import datetime
from datetime import datetime as dt
import os

def format_time(ts_ms):
    """Convert timestamp to readable format"""
    return dt.fromtimestamp(ts_ms/1000).strftime('%Y-%m-%d %H:%M:%S UTC')

def main():
    print("\n" + "="*80)
    print("🤖 COMPREHENSIVE TRADING BOT STATUS")
    print("="*80)
    
    # Load credentials
    try:
        with open('/home/ubuntu/trading_bot/credentials_multi_exchange.json') as f:
            creds = json.load(f)
        client = Client(creds['binance']['api_key'], creds['binance']['api_secret'], testnet=True)
    except Exception as e:
        print(f"❌ Failed to load credentials: {e}")
        return
    
    now = dt.utcnow()
    print(f"⏰ Current Time: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print()
    
    # ==================== ACCOUNT STATUS ====================
    print("💰 ACCOUNT STATUS")
    print("-" * 80)
    try:
        account = client.futures_account()
        balance = float(account['totalWalletBalance'])
        available = float(account['availableBalance'])
        unrealized_pnl = float(account['totalUnrealizedProfit'])
        
        print(f"  Balance:        ${balance:,.2f}")
        print(f"  Available:      ${available:,.2f}")
        print(f"  Unrealized PnL: ${unrealized_pnl:+,.2f}")
        print()
    except Exception as e:
        print(f"  ❌ Error: {e}\n")
    
    # ==================== POSITIONS ====================
    print("📊 ACTIVE POSITIONS")
    print("-" * 80)
    try:
        positions = client.futures_position_information(symbol='BTCUSDT')
        active_positions = [p for p in positions if float(p['positionAmt']) != 0]
        
        if active_positions:
            for pos in active_positions:
                amt = float(pos['positionAmt'])
                entry = float(pos['entryPrice'])
                mark = float(pos['markPrice'])
                upnl = float(pos['unRealizedProfit'])
                side = 'LONG' if amt > 0 else 'SHORT'
                
                print(f"  {pos['symbol']}: {side} {abs(amt)} BTC")
                print(f"    Entry Price:    ${entry:,.2f}")
                print(f"    Mark Price:     ${mark:,.2f}")
                print(f"    Unrealized PnL: ${upnl:+,.2f}")
                print(f"    Leverage:       {pos['leverage']}x")
        else:
            print("  ✅ No active positions")
        print()
    except Exception as e:
        print(f"  ❌ Error: {e}\n")
    
    # ==================== OPEN ORDERS ====================
    print("📋 OPEN ORDERS")
    print("-" * 80)
    try:
        orders = client.futures_get_open_orders(symbol='BTCUSDT')
        
        if orders:
            for order in orders:
                print(f"  Order #{order['orderId']}: {order['type']} {order['side']}")
                print(f"    Price: ${float(order['price']):,.2f}")
                print(f"    Quantity: {order['origQty']} BTC")
                print(f"    Stop Price: ${float(order['stopPrice']):,.2f}" if order.get('stopPrice') else "")
        else:
            print("  ✅ No open orders")
        print()
    except Exception as e:
        print(f"  ❌ Error: {e}\n")
    
    # ==================== RECENT TRADES ====================
    print("📈 RECENT TRADES (Last 10)")
    print("-" * 80)
    try:
        trades = client.futures_account_trades(symbol='BTCUSDT', limit=10)
        
        for trade in reversed(trades):
            time_str = format_time(trade['time'])
            side = trade['side']
            qty = float(trade['qty'])
            price = float(trade['price'])
            pnl = float(trade['realizedPnl'])
            fee = float(trade['commission'])
            
            print(f"  {time_str}: {side} {qty} BTC @ ${price:,.2f}")
            if pnl != 0:
                print(f"    PnL: ${pnl:+,.2f}, Fee: ${fee:.4f}")
        print()
    except Exception as e:
        print(f"  ❌ Error: {e}\n")
    
    # ==================== PROCESS STATUS ====================
    print("🔧 PROCESS STATUS")
    print("-" * 80)
    try:
        import subprocess
        result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
        lines = result.stdout.split('\n')
        
        bot_running = False
        webhook_running = False
        
        for line in lines:
            if 'enhanced_trading_bot' in line and 'grep' not in line:
                pid = line.split()[1]
                print(f"  ✅ Bot Running (PID {pid})")
                bot_running = True
            elif 'webhook' in line and 'grep' not in line:
                pid = line.split()[1]
                print(f"  ✅ Webhook Running (PID {pid})")
                webhook_running = True
        
        if not bot_running:
            print("  ❌ Bot NOT running")
        if not webhook_running:
            print("  ❌ Webhook NOT running")
        print()
    except Exception as e:
        print(f"  ❌ Error: {e}\n")
    
    # ==================== TRADINGVIEW SIGNALS ====================
    print("📡 TRADINGVIEW SIGNALS QUEUE")
    print("-" * 80)
    try:
        queue_file = '/home/ubuntu/trading_bot/tradingview_signals_queue.jsonl'
        if os.path.exists(queue_file):
            with open(queue_file) as f:
                signals = [json.loads(line) for line in f]
            
            print(f"  Total Signals in Queue: {len(signals)}")
            
            if signals:
                last_signal = signals[-1]
                signal_time = dt.fromisoformat(last_signal['timestamp'].replace('Z', ''))
                age_min = (now - signal_time).total_seconds() / 60
                
                print(f"  Last Signal:")
                print(f"    ID: {last_signal['signal_id']}")
                print(f"    Strategy: {last_signal['strategy']}")
                print(f"    Side: {last_signal['side']}")
                print(f"    Price: ${last_signal['price']:,.2f}")
                print(f"    Confidence: {last_signal['indicator_confidence']:.2%}")
                print(f"    Age: {age_min:.1f} minutes")
                print(f"    Status: {last_signal['status']}")
                
                # Count stale signals (> 60 min)
                stale = sum(1 for s in signals if (now - dt.fromisoformat(s['timestamp'].replace('Z', ''))).total_seconds() > 3600)
                print(f"  Stale Signals (>60 min): {stale}")
        else:
            print("  ⚠️ Queue file not found")
        print()
    except Exception as e:
        print(f"  ❌ Error: {e}\n")
    
    # ==================== BOT CONFIGURATION ====================
    print("⚙️ BOT CONFIGURATION")
    print("-" * 80)
    try:
        import sys
        sys.path.insert(0, '/home/ubuntu/trading_bot')
        from trading_bot.config import Config
        
        cfg = Config()
        print(f"  Min Confidence Threshold: {cfg.min_confidence_threshold:.0%}")
        print(f"  Signal Cooldown: {cfg.signal_cooldown_minutes} minutes")
        print(f"  Max Positions: {cfg.max_positions}")
        print(f"  Risk Per Trade: {cfg.risk_per_trade_pct}%")
        print(f"  Leverage: {cfg.leverage}x")
        print()
    except Exception as e:
        print(f"  ⚠️ Could not load config: {e}\n")
    
    # ==================== RECENT LOG ACTIVITY ====================
    print("📝 RECENT BOT ACTIVITY (Last 30 lines)")
    print("-" * 80)
    try:
        log_file = '/home/ubuntu/trading_bot/bot.log'
        if os.path.exists(log_file):
            with open(log_file) as f:
                lines = f.readlines()
            
            # Show last 30 lines with key events
            for line in lines[-30:]:
                if any(kw in line for kw in ['EXECUTING', 'Signal rejected', 'confidence', 
                                              'BLOCKING', 'validated_signals', 'ERROR', 
                                              'Position check', 'TradingView']):
                    print(f"  {line.strip()}")
        print()
    except Exception as e:
        print(f"  ❌ Error: {e}\n")
    
    # ==================== SUMMARY ====================
    print("="*80)
    print("✅ STATUS CHECK COMPLETE")
    print("="*80)
    
    # Quick health assessment
    try:
        health_score = 0
        issues = []
        
        if bot_running:
            health_score += 30
        else:
            issues.append("Bot not running")
        
        if webhook_running:
            health_score += 20
        else:
            issues.append("Webhook not running")
        
        if balance > 0:
            health_score += 30
        else:
            issues.append("Zero balance")
        
        if len(active_positions) <= 4:
            health_score += 20
        else:
            issues.append("Too many positions")
        
        print(f"\n🏥 Health Score: {health_score}/100")
        
        if issues:
            print(f"⚠️ Issues Detected:")
            for issue in issues:
                print(f"  - {issue}")
        else:
            print("✅ All systems operational")
    except:
        pass
    
    print()

if __name__ == '__main__':
    main()
