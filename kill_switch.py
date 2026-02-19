#!/usr/bin/env python3
"""
Emergency Kill Switch System
Creates immediate stop mechanism for trading bot
"""

import sys
sys.path.insert(0, '/home/ubuntu/tradingview-bot')
import os
from binance.client import Client
from binance.enums import *
from dotenv import load_dotenv
from datetime import datetime
import json

load_dotenv('/home/ubuntu/tradingview-bot/.env')

KILL_SWITCH_FILE = '/home/ubuntu/tradingview-bot/KILL_SWITCH'
STATUS_FILE = '/home/ubuntu/tradingview-bot/kill_switch_status.json'

def activate_kill_switch():
    """Create kill switch file"""
    with open(KILL_SWITCH_FILE, 'w') as f:
        f.write(f"ACTIVATED: {datetime.now().isoformat()}\n")
    print("✅ Kill switch ACTIVATED")

def deactivate_kill_switch():
    """Remove kill switch file"""
    if os.path.exists(KILL_SWITCH_FILE):
        os.remove(KILL_SWITCH_FILE)
        print("✅ Kill switch DEACTIVATED")
    else:
        print("ℹ️  Kill switch was not active")

def is_kill_switch_active():
    """Check if kill switch is active"""
    return os.path.exists(KILL_SWITCH_FILE)

def emergency_stop():
    """Emergency stop all trading"""
    try:
        client = Client(
            os.getenv('BINANCE_API_KEY'),
            os.getenv('BINANCE_API_SECRET'),
            testnet=True
        )
        
        print("\n" + "="*60)
        print("🚨 EMERGENCY STOP INITIATED")
        print("="*60)
        
        # 1. Close all positions
        print("\n1. Closing all open positions...")
        positions = client.futures_position_information()
        active_positions = [p for p in positions if float(p["positionAmt"]) != 0]
        
        if active_positions:
            for pos in active_positions:
                symbol = pos['symbol']
                amt = float(pos['positionAmt'])
                side = "LONG" if amt > 0 else "SHORT"
                
                try:
                    # Close position
                    close_side = SIDE_SELL if amt > 0 else SIDE_BUY
                    order = client.futures_create_order(
                        symbol=symbol,
                        side=close_side,
                        type=FUTURE_ORDER_TYPE_MARKET,
                        quantity=abs(amt),
                        reduceOnly='true'
                    )
                    print(f"   ✅ Closed {symbol} {side} position")
                except Exception as e:
                    print(f"   ❌ Failed to close {symbol}: {e}")
        else:
            print("   ℹ️  No open positions to close")
        
        # 2. Cancel all open orders
        print("\n2. Canceling all open orders...")
        symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
        for symbol in symbols:
            try:
                client.futures_cancel_all_open_orders(symbol=symbol)
                print(f"   ✅ Canceled all orders for {symbol}")
            except Exception as e:
                if "No need to cancel" not in str(e):
                    print(f"   ⚠️  {symbol}: {e}")
        
        # 3. Activate kill switch
        print("\n3. Activating kill switch...")
        activate_kill_switch()
        
        # 4. Save status
        status = {
            'activated_at': datetime.now().isoformat(),
            'reason': 'Manual emergency stop',
            'positions_closed': len(active_positions),
            'balance': float(client.futures_account()['totalWalletBalance'])
        }
        
        with open(STATUS_FILE, 'w') as f:
            json.dump(status, f, indent=2)
        
        print("\n" + "="*60)
        print("✅ EMERGENCY STOP COMPLETE")
        print("="*60)
        print(f"Positions closed: {len(active_positions)}")
        print(f"Current balance: ${status['balance']:.2f}")
        print("\nTo resume trading:")
        print("  python3 kill_switch.py --deactivate")
        print("  sudo systemctl restart tradingbot")
        print("="*60)
        
    except Exception as e:
        print(f"\n❌ EMERGENCY STOP FAILED: {e}")
        print("Please manually close positions and stop the bot!")
        import traceback
        traceback.print_exc()

def show_status():
    """Show kill switch status"""
    is_active = is_kill_switch_active()
    
    print("\n" + "="*60)
    print("KILL SWITCH STATUS")
    print("="*60)
    print(f"Status: {'🔴 ACTIVE' if is_active else '🟢 INACTIVE'}")
    
    if is_active and os.path.exists(STATUS_FILE):
        with open(STATUS_FILE, 'r') as f:
            status = json.load(f)
        print(f"\nActivated: {status['activated_at']}")
        print(f"Reason: {status['reason']}")
        print(f"Positions closed: {status['positions_closed']}")
        print(f"Balance at stop: ${status['balance']:.2f}")
    
    print("="*60)

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Emergency Kill Switch for Trading Bot')
    parser.add_argument('--activate', action='store_true', help='Activate kill switch (emergency stop)')
    parser.add_argument('--deactivate', action='store_true', help='Deactivate kill switch (resume trading)')
    parser.add_argument('--status', action='store_true', help='Show kill switch status')
    parser.add_argument('--emergency-stop', action='store_true', help='Emergency stop: close all positions and activate kill switch')
    
    args = parser.parse_args()
    
    if args.emergency_stop:
        emergency_stop()
    elif args.activate:
        activate_kill_switch()
    elif args.deactivate:
        deactivate_kill_switch()
    elif args.status:
        show_status()
    else:
        print("Usage:")
        print("  Emergency stop: python3 kill_switch.py --emergency-stop")
        print("  Activate:       python3 kill_switch.py --activate")
        print("  Deactivate:     python3 kill_switch.py --deactivate")
        print("  Status:         python3 kill_switch.py --status")
