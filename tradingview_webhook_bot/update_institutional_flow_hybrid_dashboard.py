#!/usr/bin/env python3
"""
Google Sheets Live Trading Monitor - Institutional Flow Hybrid
Shows institutional matrix strategy positions and performance
Sheet ID: 16LwZRHN0TgXOdut-RwWY805YnKsI2I8xm4AkSG2vRrU
"""
import os
import sys
import json
from datetime import datetime, timezone
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# Add local bot path
sys.path.insert(0, os.path.dirname(__file__))

from exchange.binance_client import BinanceClient

def connect_to_sheets():
    """Connect to Google Sheets"""
    scope = [
        'https://spreadsheets.google.com/feeds',
        'https://www.googleapis.com/auth/drive'
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(
        'credentials.json', 
        scope
    )
    return gspread.authorize(creds)

def load_institutional_positions():
    """Load Institutional Flow Hybrid positions from storage"""
    positions = []
    positions_file = 'storage/positions_institutional_flow_hybrid.jsonl'
    
    if os.path.exists(positions_file):
        with open(positions_file, 'r') as f:
            for line in f:
                if line.strip():
                    try:
                        pos = json.loads(line)
                        positions.append(pos)
                    except:
                        pass
    
    return positions

def load_institutional_balance():
    """Load Institutional Flow Hybrid virtual balance"""
    balance_file = 'storage/balance_institutional_flow_hybrid.json'
    
    if os.path.exists(balance_file):
        try:
            with open(balance_file, 'r') as f:
                return json.load(f)
        except:
            pass
    
    return {
        'balance': 500.0,
        'initial': 500.0,
        'realized_pnl': 0.0,
        'total_trades': 0,
        'winning_trades': 0,
        'losing_trades': 0
    }

def get_institutional_data():
    """Get Institutional Flow Hybrid trading data"""
    client = BinanceClient()
    
    # Load Institutional Flow Hybrid virtual balance
    balance_data = load_institutional_balance()
    
    # Get Institutional Flow Hybrid positions from Binance (filter by strategy tags)
    all_positions = client.get_positions()
    institutional_positions = []
    
    # Institutional strategies to filter
    institutional_strategies = [
        'hybrid_smc', 'mvo_momentum_variance', 'lorentzian_classification',
        'atr_supertrend', 'supertrend_basic', 'squeeze_momentum', 'ema_9_15'
    ]
    
    for pos in all_positions:
        position_amt = float(pos.get('positionAmt', 0))
        if position_amt != 0:
            # Check if this is an Institutional Flow Hybrid position
            symbol = pos['symbol']
            try:
                recent_orders = client.client.futures_get_all_orders(symbol=symbol, limit=10)
                for order in recent_orders:
                    client_order_id = order.get('clientOrderId', '').lower()
                    # Check if order ID contains any institutional strategy name
                    if any(strat in client_order_id for strat in institutional_strategies):
                        institutional_positions.append(pos)
                        break
            except:
                pass
    
    # Load tracked Institutional Flow Hybrid positions
    tracked_positions = load_institutional_positions()
    
    # Calculate unrealized P&L using MAINNET prices for open positions
    total_unrealized_pnl = 0
    try:
        import requests
        
        # Calculate unrealized P&L for each open tracked position using mainnet price
        for pos in tracked_positions:
            if pos.get('status') == 'open':
                try:
                    symbol = pos.get('symbol', '')
                    entry_price = float(pos.get('entry_price', 0))
                    position_size = float(pos.get('position_size', 0))
                    side = pos.get('side', '')
                    
                    if entry_price > 0 and position_size > 0 and symbol:
                        # Get current mainnet price for THIS symbol
                        response = requests.get(f'https://api.binance.com/api/v3/ticker/price?symbol={symbol}', timeout=5)
                        current_price = float(response.json()['price'])
                        
                        if side == 'LONG':
                            pnl = (current_price - entry_price) * position_size
                        else:  # SHORT
                            pnl = (entry_price - current_price) * position_size
                        
                        total_unrealized_pnl += pnl
                except (ValueError, TypeError, Exception):
                    continue
                    
    except Exception as e:
        print(f"[WARN] Could not calculate mainnet unrealized P&L: {e}")
        # Fallback to testnet unrealized P&L
        for pos in institutional_positions:
            total_unrealized_pnl += float(pos.get('unRealizedProfit', 0))
    
    # Check if bot is running
    bot_running = False
    log_file = 'logs/bot.log'
    if os.path.exists(log_file):
        try:
            # Check if log was updated in last 60 seconds
            mtime = os.path.getmtime(log_file)
            bot_running = (datetime.now().timestamp() - mtime) < 60
            
            # Also check if the bot process is actually running
            if bot_running:
                try:
                    import subprocess
                    result = subprocess.run(['pgrep', '-f', 'config_institutional_flow_hybrid'], 
                                          capture_output=True, text=True, timeout=5)
                    bot_running = bool(result.stdout.strip())
                except:
                    pass
        except:
            pass
    
    return {
        'balance': balance_data['balance'],
        'initial_balance': balance_data['initial'],
        'realized_pnl': balance_data['realized_pnl'],
        'unrealized_pnl': total_unrealized_pnl,
        'total_trades': balance_data['total_trades'],
        'winning_trades': balance_data['winning_trades'],
        'losing_trades': balance_data['losing_trades'],
        'open_positions': institutional_positions,
        'tracked_positions': tracked_positions,
        'bot_running': bot_running,
        'last_update': datetime.now(timezone.utc).isoformat()
    }

def update_institutional_tab(worksheet, data):
    """
    Institutional Flow Hybrid Trading Monitor - Single Comprehensive Tab
    Shows: Performance, balance, open positions, and trade history
    """
    print("[INSTITUTIONAL] Updating Institutional Flow Hybrid Dashboard...")
    
    # Calculate performance metrics
    total_pnl = data['realized_pnl'] + data['unrealized_pnl']
    total_pnl_pct = (total_pnl / data['initial_balance'] * 100) if data['initial_balance'] > 0 else 0
    win_rate = (data['winning_trades'] / data['total_trades'] * 100) if data['total_trades'] > 0 else 0
    
    # Build the sheet structure
    sheet_data = []
    
    # === HEADER ===
    sheet_data.append(['INSTITUTIONAL FLOW HYBRID - LIVE TRADING DASHBOARD', '', '', '', '', '', ''])
    sheet_data.append(['Last Update:', data['last_update'], '', 'Bot Status:', 'RUNNING ✓' if data['bot_running'] else 'STOPPED ✗', '', ''])
    sheet_data.append(['Strategies:', 'Multi-Strategy Institutional', '', 'Timeframe:', 'Multiple', '', ''])
    sheet_data.append(['', '', '', '', '', '', ''])
    
    # === PERFORMANCE SUMMARY ===
    sheet_data.append(['PERFORMANCE SUMMARY', '', '', '', '', '', ''])
    sheet_data.append(['Virtual Balance:', f"${data['balance']:.2f}", '', 'Initial Balance:', f"${data['initial_balance']:.2f}", '', ''])
    sheet_data.append(['Realized P&L:', f"${data['realized_pnl']:.2f}", '', 'Unrealized P&L:', f"${data['unrealized_pnl']:.2f}", '', ''])
    sheet_data.append(['Total P&L:', f"${total_pnl:.2f}", f"({total_pnl_pct:+.2f}%)", '', '', '', ''])
    sheet_data.append(['Total Trades:', str(data['total_trades']), '', 'Win Rate:', f"{win_rate:.1f}%", f"({data['winning_trades']}W / {data['losing_trades']}L)", ''])
    open_count = len([p for p in data['tracked_positions'] if p.get('status') == 'open'])
    sheet_data.append(['Open Positions:', str(open_count), '', '', '', '', ''])
    sheet_data.append(['', '', '', '', '', '', ''])
    
    # === OPEN POSITIONS ===
    sheet_data.append(['OPEN POSITIONS', '', '', '', '', '', ''])
    if data['tracked_positions']:
        sheet_data.append(['Position ID', 'Symbol', 'Side', 'Entry Price', 'Size', 'Stop Loss', 'Take Profit'])
        for pos in data['tracked_positions']:
            if pos.get('status') == 'open':
                sheet_data.append([
                    pos.get('position_id', '')[:30],  # Truncate long IDs
                    pos.get('symbol', ''),
                    pos.get('side', ''),
                    f"${float(pos.get('entry_price', 0)):,.2f}",
                    pos.get('position_size', '0'),
                    f"${float(pos.get('stop_loss', 0)):,.2f}",
                    f"${float(pos.get('take_profit', 0)):,.2f}"
                ])
    else:
        sheet_data.append(['No open positions', '', '', '', '', '', ''])
    
    sheet_data.append(['', '', '', '', '', '', ''])
    
    # === LIVE BINANCE POSITIONS (for verification) ===
    sheet_data.append(['LIVE BINANCE POSITIONS', '', '', '', '', '', ''])
    if data['open_positions']:
        sheet_data.append(['Symbol', 'Position', 'Entry Price', 'Mark Price', 'Unrealized P&L', 'ROE %', ''])
        for pos in data['open_positions']:
            entry_price = float(pos.get('entryPrice', 0))
            mark_price = float(pos.get('markPrice', 0))
            position_amt = float(pos.get('positionAmt', 0))
            unrealized_pnl = float(pos.get('unRealizedProfit', 0))
            
            # Calculate ROE
            roe = (unrealized_pnl / abs(position_amt * entry_price) * 100) if entry_price > 0 and position_amt != 0 else 0
            
            sheet_data.append([
                pos.get('symbol', ''),
                f"{abs(position_amt):.4f} {'LONG' if position_amt > 0 else 'SHORT'}",
                f"${entry_price:,.2f}",
                f"${mark_price:,.2f}",
                f"${unrealized_pnl:,.2f}",
                f"{roe:+.2f}%",
                ''
            ])
    else:
        sheet_data.append(['No live positions on Binance', '', '', '', '', '', ''])
    
    sheet_data.append(['', '', '', '', '', '', ''])
    
    # === CLOSED POSITIONS (Recent 10) ===
    sheet_data.append(['RECENT CLOSED POSITIONS', '', '', '', '', '', ''])
    closed_positions = [p for p in data['tracked_positions'] if p.get('status') == 'closed']
    if closed_positions:
        sheet_data.append(['Closed At', 'Symbol', 'Side', 'Entry', 'Exit', 'P&L', 'Result'])
        for pos in closed_positions[-10:]:  # Last 10 closed
            pnl = float(pos.get('pnl', 0))
            sheet_data.append([
                datetime.fromtimestamp(pos.get('closed_at', 0)).strftime('%Y-%m-%d %H:%M:%S') if pos.get('closed_at') else '',  # Timestamp without milliseconds
                pos.get('symbol', ''),
                pos.get('side', ''),
                f"${float(pos.get('entry_price', 0)):,.2f}",
                f"${float(pos.get('exit_price', 0)):,.2f}" if pos.get('exit_price') else '',
                f"${pnl:,.2f}",
                'WIN' if pnl > 0 else 'LOSS'
            ])
    else:
        sheet_data.append(['No closed positions yet', '', '', '', '', '', ''])
    
    # Clear and update entire sheet
    worksheet.clear()
    worksheet.update(values=sheet_data, range_name=f'A1:G{len(sheet_data)}')
    
    # Format headers
    try:
        worksheet.format('A1:G1', {
            'textFormat': {'bold': True, 'fontSize': 14},
            'backgroundColor': {'red': 0.6, 'green': 0.2, 'blue': 0.9},
            'horizontalAlignment': 'CENTER'
        })
    except:
        pass
    
    print(f"   ✓ Updated Institutional Flow Hybrid dashboard with {len(data['tracked_positions'])} positions")

def update_sheet(sheet_id='16LwZRHN0TgXOdut-RwWY805YnKsI2I8xm4AkSG2vRrU'):
    """Update Google Sheet with Institutional Flow Hybrid tab"""
    print(f"{'='*60}")
    print(f"GOOGLE SHEETS - INSTITUTIONAL FLOW HYBRID TRADING MONITOR")
    print(f"{'='*60}\n")
    
    try:
        # Connect to sheets
        client = connect_to_sheets()
        spreadsheet = client.open_by_key(sheet_id)
        print(f"[OK] Connected to: {spreadsheet.title}\n")
        
        # Get or create Institutional Flow Hybrid worksheet
        try:
            worksheet = spreadsheet.worksheet('Institutional Flow Hybrid')
            print(f"[OK] Found existing 'Institutional Flow Hybrid' tab\n")
        except:
            worksheet = spreadsheet.add_worksheet(title='Institutional Flow Hybrid', rows=100, cols=7)
            print(f"[OK] Created new 'Institutional Flow Hybrid' tab\n")
        
        # Get Institutional Flow Hybrid data
        print("[DATA] Fetching Institutional Flow Hybrid trading data...")
        data = get_institutional_data()
        
        print(f"   Virtual Balance: ${data['balance']:,.2f}")
        print(f"   Realized P&L: ${data['realized_pnl']:,.2f}")
        print(f"   Unrealized P&L: ${data['unrealized_pnl']:,.2f}")
        print(f"   Total Trades: {data['total_trades']} (W:{data['winning_trades']} L:{data['losing_trades']})")
        open_count = len([p for p in data['tracked_positions'] if p.get('status') == 'open'])
        print(f"   Open Positions: {open_count}")
        print(f"   Bot Running: {'YES' if data['bot_running'] else 'NO'}\n")
        
        # Update Institutional Flow Hybrid Tab
        update_institutional_tab(worksheet, data)
        
        print(f"\n[SUCCESS] Institutional Flow Hybrid dashboard updated!")
        print(f"[LINK] https://docs.google.com/spreadsheets/d/{sheet_id}/\n")
        
        return True
        
    except Exception as e:
        print(f"[ERROR] Failed to update sheet: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    update_sheet()
