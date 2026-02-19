#!/usr/bin/env python3
"""
Google Sheets Live Trading Monitor - SMC LuxAlgo Single Tab
Shows only SMC LuxAlgo strategy positions and performance
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

def load_smc_positions():
    """Load SMC LuxAlgo positions from storage"""
    positions = []
    positions_file = 'storage/positions_smc_luxalgo.jsonl'
    
    if os.path.exists(positions_file):
        with open(positions_file, 'r') as f:
            for line in f:
                if line.strip():
                    try:
                        pos = json.loads(line)
                        if pos.get('strategy') == 'smc_luxalgo':
                            positions.append(pos)
                    except:
                        pass
    
    return positions

def load_smc_balance():
    """Load SMC LuxAlgo virtual balance"""
    balance_file = 'storage/balance_smc_luxalgo.json'
    
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

def get_smc_data():
    """Get SMC LuxAlgo trading data"""
    client = BinanceClient()
    
    # Load SMC virtual balance
    balance_data = load_smc_balance()
    
    # Get SMC positions from Binance (filter by strategy tag in clientOrderId)
    all_positions = client.get_positions()
    smc_positions = []
    
    for pos in all_positions:
        position_amt = float(pos.get('positionAmt', 0))
        if position_amt != 0:
            # Check if this is an SMC position by checking recent orders
            symbol = pos['symbol']
            try:
                recent_orders = client.client.futures_get_all_orders(symbol=symbol, limit=5)
                for order in recent_orders:
                    client_order_id = order.get('clientOrderId', '')
                    if 'smc_luxalgo' in client_order_id.lower():
                        smc_positions.append(pos)
                        break
            except:
                pass
    
    # Load tracked SMC positions
    tracked_positions = load_smc_positions()
    
    # Calculate unrealized P&L using MAINNET prices for open positions
    total_unrealized_pnl = 0
    try:
        # Get current mainnet price
        import requests
        response = requests.get('https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT', timeout=5)
        current_mainnet_price = float(response.json()['price'])
        
        # Calculate unrealized P&L for each open tracked position using mainnet price
        for pos in tracked_positions:
            if pos.get('status') == 'open':
                try:
                    entry_price = float(pos.get('entry_price', 0))
                    position_size = float(pos.get('position_size', 0))
                    side = pos.get('side', '')
                    
                    if entry_price > 0 and position_size > 0:
                        if side == 'LONG':
                            pnl = (current_mainnet_price - entry_price) * position_size
                        else:  # SHORT
                            pnl = (entry_price - current_mainnet_price) * position_size
                        
                        total_unrealized_pnl += pnl
                except (ValueError, TypeError):
                    continue
                    
    except Exception as e:
        print(f"[WARN] Could not calculate mainnet unrealized P&L: {e}")
        # Fallback to testnet unrealized P&L
        for pos in smc_positions:
            total_unrealized_pnl += float(pos.get('unRealizedProfit', 0))
    
    # Check if bot is running
    bot_running = False
    log_file = 'logs/bot.log'
    if os.path.exists(log_file):
        try:
            mtime = os.path.getmtime(log_file)
            bot_running = (datetime.now().timestamp() - mtime) < 30
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
        'open_positions': smc_positions,
        'tracked_positions': tracked_positions,
        'bot_running': bot_running,
        'last_update': datetime.now(timezone.utc).isoformat()
    }

def update_smc_tab(worksheet, data):
    """
    SMC LuxAlgo Trading Monitor - Single Comprehensive Tab
    Shows: Performance, balance, open positions, and trade history
    """
    print("[SMC] Updating SMC LuxAlgo Dashboard...")
    
    # Calculate performance metrics
    total_pnl = data['realized_pnl'] + data['unrealized_pnl']
    total_pnl_pct = (total_pnl / data['initial_balance'] * 100) if data['initial_balance'] > 0 else 0
    win_rate = (data['winning_trades'] / data['total_trades'] * 100) if data['total_trades'] > 0 else 0
    
    # Build the sheet structure
    sheet_data = []
    
    # === HEADER ===
    sheet_data.append(['SMC LUXALGO - LIVE TRADING DASHBOARD', '', '', '', '', '', ''])
    sheet_data.append(['Last Update:', data['last_update'], '', 'Bot Status:', 'RUNNING ✓' if data['bot_running'] else 'STOPPED ✗', '', ''])
    sheet_data.append(['Strategy:', 'SMC LuxAlgo', '', 'Timeframe:', '15m', '', ''])
    sheet_data.append(['', '', '', '', '', '', ''])
    
    # === PERFORMANCE SUMMARY ===
    sheet_data.append(['PERFORMANCE SUMMARY', '', '', '', '', '', ''])
    sheet_data.append(['Virtual Balance:', f"${data['balance']:,.2f}", '', 'Initial Balance:', f"${data['initial_balance']:,.2f}", '', ''])
    sheet_data.append(['Realized P&L:', f"${data['realized_pnl']:,.2f}", '', 'Unrealized P&L:', f"${data['unrealized_pnl']:,.2f}", '', ''])
    sheet_data.append(['Total P&L:', f"${total_pnl:,.2f}", f"({total_pnl_pct:+.2f}%)", '', '', '', ''])
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
            # Handle timestamp formatting safely
            closed_at = pos.get('closed_at', '')
            if isinstance(closed_at, (int, float)):
                # Convert timestamp to ISO format
                from datetime import datetime
                closed_at_str = datetime.fromtimestamp(closed_at).isoformat()[:19]
            else:
                # Already a string, just truncate
                closed_at_str = str(closed_at)[:19] if closed_at else ''
            
            sheet_data.append([
                closed_at_str,
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
            'backgroundColor': {'red': 0.2, 'green': 0.6, 'blue': 0.9},
            'horizontalAlignment': 'CENTER'
        })
    except:
        pass
    
    print(f"   ✓ Updated SMC dashboard with {len(data['tracked_positions'])} positions")

def update_live_activity_tab(worksheet, data):
    """
    Tab 1: Live Activity
    Shows: Current status, balance, orders, and recent trades
    """
    print("[TAB 1] Updating Live Activity...")
    
    # Calculate totals
    pnl_pct = (data['unrealized_pnl'] / data['balance'] * 100) if data['balance'] > 0 else 0
    
    # Build the sheet structure
    sheet_data = []
    
    # === HEADER SECTION ===
    sheet_data.append(['LIVE TRADING ACTIVITY', '', '', '', '', ''])
    sheet_data.append(['Last Update:', data['timestamp'], '', 'Bot Status:', 'RUNNING ✓' if data['bot_running'] else 'STOPPED ✗', ''])
    sheet_data.append(['Environment:', 'TESTNET' if data['testnet'] else 'MAINNET', '', '', '', ''])
    sheet_data.append(['', '', '', '', '', ''])
    
    # === ACCOUNT SECTION ===
    sheet_data.append(['ACCOUNT BALANCE', '', '', '', '', ''])
    sheet_data.append(['Total Balance:', f"${data['balance']:,.2f}", '', 'Available:', f"${data['available_balance']:,.2f}", ''])
    sheet_data.append(['Unrealized P&L:', f"${data['unrealized_pnl']:,.2f}", f"({pnl_pct:+.2f}%)", '', '', ''])
    sheet_data.append(['Open Positions:', str(len(data['open_positions'])), '', 'Open Orders:', str(len(data['open_orders'])), ''])
    sheet_data.append(['', '', '', '', '', ''])
    
    # === OPEN ORDERS SECTION ===
    sheet_data.append(['OPEN ORDERS', '', '', '', '', ''])
    if data['open_orders']:
        sheet_data.append(['Symbol', 'Side', 'Type', 'Price', 'Quantity', 'Order ID'])
        for order in data['open_orders'][:10]:  # Show max 10 orders
            sheet_data.append([
                order.get('symbol', ''),
                order.get('side', ''),
                order.get('type', ''),
                f"${float(order.get('price', 0)):,.2f}" if order.get('price') else 'MARKET',
                f"{float(order.get('origQty', 0)):.4f}",
                str(order.get('orderId', ''))
            ])
    else:
        sheet_data.append(['No open orders', '', '', '', '', ''])
    
    sheet_data.append(['', '', '', '', '', ''])
    
    # === RECENT TRADES SECTION ===
    sheet_data.append(['RECENT TRADES (Last 15)', '', '', '', '', ''])
    if data['recent_trades']:
        sheet_data.append(['Time', 'Symbol', 'Side', 'Price', 'Quantity', 'Realized P&L'])
        for trade in data['recent_trades'][:15]:
            timestamp = datetime.fromtimestamp(trade['time'] / 1000, tz=timezone.utc).strftime('%H:%M:%S')
            sheet_data.append([
                timestamp,
                trade.get('symbol', ''),
                trade.get('side', ''),
                f"${float(trade.get('price', 0)):,.2f}",
                f"{float(trade.get('qty', 0)):.4f}",
                f"${float(trade.get('realizedPnl', 0)):,.2f}"
            ])
    else:
        sheet_data.append(['No recent trades', '', '', '', '', ''])
    
    # Clear and update entire sheet
    worksheet.clear()
    worksheet.update(values=sheet_data, range_name=f'A1:F{len(sheet_data)}')
    
    # Format headers
    try:
        worksheet.format('A1:F1', {
            'textFormat': {'bold': True, 'fontSize': 14},
            'backgroundColor': {'red': 0.2, 'green': 0.6, 'blue': 0.9},
            'horizontalAlignment': 'CENTER'
        })
        worksheet.format('A5:F5', {
            'textFormat': {'bold': True},
            'backgroundColor': {'red': 0.9, 'green': 0.9, 'blue': 0.7}
        })
        # Find and format section headers
        for i, row in enumerate(sheet_data, start=1):
            if row[0] in ['OPEN ORDERS', 'RECENT TRADES (Last 15)']:
                worksheet.format(f'A{i}:F{i}', {
                    'textFormat': {'bold': True},
                    'backgroundColor': {'red': 0.9, 'green': 0.9, 'blue': 0.7}
                })
    except:
        pass
    
    print(f"   ✓ Updated with {len(data['open_orders'])} orders, {len(data['recent_trades'][:15])} trades")

def update_positions_strategies_tab(worksheet, data):
    """
    Tab 2: Positions & Strategies
    Shows: All open positions with strategy details, entry/exit levels
    """
    print("[TAB 2] Updating Positions & Strategies...")
    
    sheet_data = []
    
    # === HEADER SECTION ===
    sheet_data.append(['POSITIONS & STRATEGIES', '', '', '', '', '', '', '', ''])
    sheet_data.append(['Last Update:', data['timestamp'], '', f"Total Positions: {len(data['open_positions'])}", '', '', '', '', ''])
    sheet_data.append(['', '', '', '', '', '', '', '', ''])
    
    # === BINANCE POSITIONS SECTION ===
    sheet_data.append(['LIVE BINANCE POSITIONS', '', '', '', '', '', '', '', ''])
    
    if data['open_positions']:
        sheet_data.append([
            'Symbol', 'Side', 'Size', 'Entry Price', 'Mark Price', 
            'Liquidation', 'Unrealized P&L', 'ROE %', 'Leverage'
        ])
        
        for pos in data['open_positions']:
            symbol = pos.get('symbol', '')
            position_amt = float(pos.get('positionAmt', 0))
            side = 'LONG 📈' if position_amt > 0 else 'SHORT 📉'
            entry_price = float(pos.get('entryPrice', 0))
            mark_price = float(pos.get('markPrice', 0))
            liquidation = float(pos.get('liquidationPrice', 0))
            unrealized_pnl = float(pos.get('unRealizedProfit', 0))
            leverage = int(pos.get('leverage', 1))
            
            # Calculate ROE
            if entry_price > 0:
                if position_amt > 0:  # LONG
                    roe = ((mark_price - entry_price) / entry_price) * 100 * leverage
                else:  # SHORT
                    roe = ((entry_price - mark_price) / entry_price) * 100 * leverage
            else:
                roe = 0
            
            sheet_data.append([
                symbol,
                side,
                f"{abs(position_amt):.4f}",
                f"${entry_price:,.2f}",
                f"${mark_price:,.2f}",
                f"${liquidation:,.2f}" if liquidation > 0 else 'N/A',
                f"${unrealized_pnl:,.2f}",
                f"{roe:+.2f}%",
                f"{leverage}x"
            ])
    else:
        sheet_data.append(['No open positions', '', '', '', '', '', '', '', ''])
    
    sheet_data.append(['', '', '', '', '', '', '', '', ''])
    
    # === TRACKED POSITIONS WITH STRATEGIES SECTION ===
    sheet_data.append(['BOT TRACKED POSITIONS (With Strategy Details)', '', '', '', '', '', '', '', ''])
    
    # Filter open positions from local storage
    tracked_positions = [p for p in data['local_positions'] if p.get('status') == 'open']
    
    # Create a map of Binance positions for quick lookup
    binance_pos_map = {pos['symbol']: pos for pos in data['open_positions']}
    
    if tracked_positions:
        sheet_data.append([
            'Position ID', 'Strategy', 'Symbol', 'Side', 'Entry Price',
            'Stop Loss', 'Take Profit', 'Size', 'Opened At'
        ])
        
        for pos in tracked_positions:
            symbol = pos.get('symbol', 'N/A')
            
            # Try to get actual entry price from Binance if local storage has $0.00
            entry_price = float(pos.get('entry_price', 0))
            position_size = pos.get('position_size', 0)
            
            # Convert position_size to float if it's a string
            try:
                position_size = float(position_size) if position_size else 0
            except (ValueError, TypeError):
                position_size = 0
            
            # If entry price is 0, try to get it from Binance live data
            if entry_price == 0 and symbol in binance_pos_map:
                binance_pos = binance_pos_map[symbol]
                entry_price = float(binance_pos.get('entryPrice', 0))
                # Also get actual size if stored size is 0
                if position_size == 0:
                    position_size = abs(float(binance_pos.get('positionAmt', 0)))
            
            sheet_data.append([
                pos.get('position_id', 'N/A')[:20],  # Truncate long IDs
                pos.get('strategy', 'N/A'),
                symbol,
                pos.get('side', 'N/A'),
                f"${entry_price:,.2f}" if entry_price > 0 else 'N/A',
                f"${float(pos.get('stop_loss', 0)):,.2f}" if float(pos.get('stop_loss', 0)) > 0 else 'N/A',
                f"${float(pos.get('take_profit', 0)):,.2f}" if float(pos.get('take_profit', 0)) > 0 else 'N/A',
                f"{position_size:.4f}" if position_size > 0 else 'N/A',
                pos.get('opened_at', 'N/A')[:19] if pos.get('opened_at') else 'N/A'
            ])
    else:
        sheet_data.append(['No tracked positions', '', '', '', '', '', '', '', ''])
    
    sheet_data.append(['', '', '', '', '', '', '', '', ''])
    
    # === STRATEGY SUMMARY ===
    sheet_data.append(['STRATEGY BREAKDOWN', '', '', '', '', '', '', '', ''])
    
    # Count positions by strategy
    strategy_count = {}
    for pos in tracked_positions:
        strategy = pos.get('strategy', 'Unknown')
        strategy_count[strategy] = strategy_count.get(strategy, 0) + 1
    
    if strategy_count:
        sheet_data.append(['Strategy', 'Open Positions', '', '', '', '', '', '', ''])
        for strategy, count in sorted(strategy_count.items()):
            sheet_data.append([strategy, str(count), '', '', '', '', '', '', ''])
    else:
        sheet_data.append(['No active strategies', '', '', '', '', '', '', '', ''])
    
    # Clear and update entire sheet
    worksheet.clear()
    worksheet.update(values=sheet_data, range_name=f'A1:I{len(sheet_data)}')
    
    # Format headers
    try:
        worksheet.format('A1:I1', {
            'textFormat': {'bold': True, 'fontSize': 14},
            'backgroundColor': {'red': 0.2, 'green': 0.6, 'blue': 0.9},
            'horizontalAlignment': 'CENTER'
        })
        # Format section headers
        for i, row in enumerate(sheet_data, start=1):
            if row[0] in ['LIVE BINANCE POSITIONS', 'BOT TRACKED POSITIONS (With Strategy Details)', 'STRATEGY BREAKDOWN']:
                worksheet.format(f'A{i}:I{i}', {
                    'textFormat': {'bold': True},
                    'backgroundColor': {'red': 0.9, 'green': 0.9, 'blue': 0.7}
                })
    except:
        pass
    
    print(f"   ✓ Updated with {len(data['open_positions'])} Binance positions, {len(tracked_positions)} tracked positions")

def update_sheet(sheet_id='16LwZRHN0TgXOdut-RwWY805YnKsI2I8xm4AkSG2vRrU'):
    """Update Google Sheet with single SMC LuxAlgo tab"""
    print(f"{'='*60}")
    print(f"GOOGLE SHEETS - SMC LUXALGO TRADING MONITOR")
    print(f"{'='*60}\n")
    
    try:
        # Connect to sheets
        client = connect_to_sheets()
        spreadsheet = client.open_by_key(sheet_id)
        print(f"[OK] Connected to: {spreadsheet.title}\n")
        
        # CRITICAL FIX: DO NOT DELETE OTHER TABS
        # Previous code was deleting reconciled data tabs and institutional matrix tabs
        # This caused major data loss and visibility issues
        print(f"[INFO] Preserving all existing tabs - no cleanup needed")
        
        # Rename first worksheet to "SMC LuxAlgo"
        try:
            first_sheet = spreadsheet.get_worksheet(0)
            first_sheet.update_title('SMC LuxAlgo')
            print(f"[OK] Renamed first sheet to 'SMC LuxAlgo'\n")
        except:
            pass
        
        # Get SMC data
        print("[DATA] Fetching SMC LuxAlgo trading data...")
        data = get_smc_data()
        
        print(f"   Virtual Balance: ${data['balance']:,.2f}")
        print(f"   Realized P&L: ${data['realized_pnl']:,.2f}")
        print(f"   Unrealized P&L: ${data['unrealized_pnl']:,.2f}")
        print(f"   Total Trades: {data['total_trades']} (W:{data['winning_trades']} L:{data['losing_trades']})")
        open_count = len([p for p in data['tracked_positions'] if p.get('status') == 'open'])
        print(f"   Open Positions: {open_count}")
        print(f"   Bot Running: {'YES' if data['bot_running'] else 'NO'}\n")
        
        # Update SMC LuxAlgo Tab
        try:
            worksheet = spreadsheet.worksheet('SMC LuxAlgo')
        except:
            worksheet = spreadsheet.add_worksheet(title='SMC LuxAlgo', rows=100, cols=7)
        
        update_smc_tab(worksheet, data)
        
        print(f"\n[SUCCESS] SMC LuxAlgo dashboard updated!")
        print(f"[LINK] https://docs.google.com/spreadsheets/d/{sheet_id}/\n")
        
        return True
        
    except Exception as e:
        print(f"[ERROR] Failed to update sheet: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    update_sheet()
