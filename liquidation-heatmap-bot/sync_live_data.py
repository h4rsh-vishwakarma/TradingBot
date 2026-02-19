#!/usr/bin/env python3
"""
Sync Live Trading Data to Google Sheets
Updates the dashboard with latest bot activity
"""

import json
import os
from datetime import datetime, timezone
import gspread
from google.oauth2.service_account import Credentials
from pathlib import Path

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

def load_events(event_type):
    """Load events from jsonl file"""
    file_path = f"events/{event_type}.jsonl"
    if not Path(file_path).exists():
        return []
    
    events = []
    with open(file_path, 'r') as f:
        for line in f:
            if line.strip():
                events.append(json.loads(line))
    return events

def setup_tabs_if_needed(spreadsheet):
    """Create tabs if they don't exist"""
    existing_sheets = [ws.title for ws in spreadsheet.worksheets()]
    
    tabs_to_create = [
        ("📊 Summary", 100, 10),
        ("📍 Positions", 100, 10),
        ("💰 Fills", 500, 12),
        ("🎯 Decisions", 1000, 10),
        ("❤️ Health", 1000, 12),
        ("🚫 Vetoes", 500, 10)
    ]
    
    for tab_name, rows, cols in tabs_to_create:
        if tab_name not in existing_sheets:
            print(f"  Creating tab: {tab_name}")
            ws = spreadsheet.add_worksheet(tab_name, rows, cols)
            setup_tab_headers(ws, tab_name)
    
    # Rename Sheet1 if it exists
    if "Sheet1" in existing_sheets and "📊 Summary" not in existing_sheets:
        ws = spreadsheet.worksheet("Sheet1")
        ws.update_title("📊 Summary")
        setup_tab_headers(ws, "📊 Summary")

def setup_tab_headers(ws, tab_name):
    """Setup headers for each tab"""
    if tab_name == "📊 Summary":
        data = [["🤖 LIVE TRADING DASHBOARD", "", "", ""],
                ["Last Updated:", "", "", ""],
                ["", "", "", ""],
                ["📈 CURRENT STATUS", "", "", ""]]
        ws.update(values=data, range_name='A1:D4')
        ws.format('A1:D1', {'textFormat': {'bold': True, 'fontSize': 14}})
    
    elif tab_name == "📍 Positions":
        headers = [["Timestamp", "Side", "Size (BTC)", "Entry Price", "Current PnL", "Unrealized PnL", "Status", "Duration"]]
        ws.update(values=headers, range_name='A1:H1')
        ws.format('A1:H1', {'textFormat': {'bold': True}, 'backgroundColor': {'red': 0.2, 'green': 0.8, 'blue': 0.4}})
    
    elif tab_name == "💰 Fills":
        headers = [["Timestamp", "Side", "Type", "Size (BTC)", "Price", "PnL Open", "PnL Close", "Fee", "Slippage", "Order ID", "Decision ID"]]
        ws.update(values=headers, range_name='A1:K1')
        ws.format('A1:K1', {'textFormat': {'bold': True}, 'backgroundColor': {'red': 0.2, 'green': 0.7, 'blue': 1}})
    
    elif tab_name == "🎯 Decisions":
        headers = [["Timestamp", "Decision", "Side", "Confidence", "Price", "Entry", "Stop Loss", "Take Profit", "Cluster Info"]]
        ws.update(values=headers, range_name='A1:I1')
        ws.format('A1:I1', {'textFormat': {'bold': True}, 'backgroundColor': {'red': 1, 'green': 0.8, 'blue': 0.2}})
    
    elif tab_name == "❤️ Health":
        headers = [["Timestamp", "Equity", "Positions", "Daily PnL", "Daily Loss", "Risk Used %", "PnL Realized", "PnL Unrealized", "Price Age", "WS Connected", "Kill Switch"]]
        ws.update(values=headers, range_name='A1:K1')
        ws.format('A1:K1', {'textFormat': {'bold': True}, 'backgroundColor': {'red': 1, 'green': 0.4, 'blue': 0.4}})
    
    elif tab_name == "🚫 Vetoes":
        headers = [["Timestamp", "Reason", "Details", "Positions Open", "Cooldown Remaining", "Price", "Side", "Confidence"]]
        ws.update(values=headers, range_name='A1:H1')
        ws.format('A1:H1', {'textFormat': {'bold': True}, 'backgroundColor': {'red': 1, 'green': 0.5, 'blue': 0.3}})

def sync_to_sheet(sheet_id):
    """Sync all data to Google Sheet"""
    
    creds = Credentials.from_service_account_file('credentials.json', scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(sheet_id)
    
    print("📊 Syncing data to dashboard...")
    
    # Setup tabs if they don't exist
    setup_tabs_if_needed(spreadsheet)
    
    # Update summary
    update_summary(spreadsheet)
    
    # Update positions
    update_positions(spreadsheet)
    
    # Update fills
    update_fills(spreadsheet)
    
    # Update decisions
    update_decisions(spreadsheet)
    
    # Update health
    update_health(spreadsheet)
    
    # Update vetoes
    update_vetoes(spreadsheet)
    
    print("✅ Dashboard updated successfully!")

def update_summary(spreadsheet):
    """Update summary tab with latest stats"""
    ws = spreadsheet.worksheet("📊 Summary")
    
    # Load latest data
    health_events = load_events("health")
    fill_events = load_events("fill")
    decision_events = load_events("decision")
    veto_events = load_events("veto")
    
    if health_events:
        latest_health = health_events[-1]
        
        # Update timestamp
        ws.update(values=[[datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")]], range_name='B2')
        
        # Update stats
        equity = f"${latest_health.get('equity_usd', 0):.2f}"
        positions = latest_health.get('positions_open', 0)
        daily_pnl = f"${latest_health.get('daily_pnl', 0):.2f}"
        daily_loss = f"${latest_health.get('daily_loss_usd', 0):.2f}"
        
        ws.update(values=[[equity], [str(positions)], [daily_pnl], [daily_loss]], range_name='B5:B8')
        
        # Session stats
        total_decisions = len(decision_events)
        total_fills = len(fill_events)
        total_vetoes = len(veto_events)
        cooldown_vetoes = sum(1 for v in veto_events if v.get('reason') == 'POSITION_COOLDOWN')
        
        ws.update(values=[[str(total_decisions)], [str(total_vetoes)]], range_name='B11:B12')
        ws.update(values=[[str(total_fills)], [str(cooldown_vetoes)]], range_name='D11:D12')

def update_positions(spreadsheet):
    """Update current positions"""
    ws = spreadsheet.worksheet("📍 Positions")
    
    fill_events = load_events("fill")
    health_events = load_events("health")
    
    # Track positions by order_id - exit_type indicates a close
    positions = {}  # order_id -> fill data
    
    for fill in fill_events:
        order_id = fill.get('order_id', '')
        exit_type = fill.get('exit_type')
        
        # If it's an entry (no exit_type), add to positions
        if not exit_type:
            positions[order_id] = fill
        # If it's an exit, remove from positions  
        else:
            positions.pop(order_id, None)
    
    # Convert to rows
    open_positions = []
    for order_id, fill in positions.items():
        ts = fill.get('ts', '')[:19]
        side = fill.get('side', 'N/A')
        size = fill.get('qty', 0)
        entry_price = fill.get('px', 0)
        pnl_open = fill.get('pnl_open', 0)
        
        # Calculate time since entry
        from datetime import datetime, timezone
        try:
            entry_time = datetime.fromisoformat(fill.get('ts', '').replace('Z', '+00:00'))
            duration = (datetime.now(timezone.utc) - entry_time).total_seconds()
            duration_str = f"{int(duration//60)}m" if duration < 3600 else f"{duration/3600:.1f}h"
        except:
            duration_str = "Unknown"
        
        open_positions.append([
            ts,
            side,
            f"{size:.6f}",
            f"${entry_price:.2f}",
            f"${pnl_open:.3f}",
            "Live",
            "OPEN",
            duration_str
        ])
    
    if open_positions:
        ws.update(values=open_positions, range_name=f'A2:H{len(open_positions)+1}')
    else:
        ws.update(values=[["No open positions", "", "", "", "", "", "", ""]], range_name='A2:H2')

def update_fills(spreadsheet):
    """Update fills tab"""
    ws = spreadsheet.worksheet("💰 Fills")
    
    fill_events = load_events("fill")
    
    rows = []
    for fill in fill_events:
        ts = fill.get('ts', '')[:19]
        side = fill.get('side', 'N/A')
        fill_type = "CLOSE" if fill.get('pnl_close', 0) != 0 else "OPEN"
        size = fill.get('qty', 0)
        price = fill.get('px', 0)
        pnl_open = fill.get('pnl_open', 0)
        pnl_close = fill.get('pnl_close', 0)
        fee = fill.get('fee', 0)
        slippage = fill.get('slippage_bps', 0)
        order_id = fill.get('order_id', '')[:12]
        decision_id = fill.get('decision_id', '')[:12]
        
        rows.append([
            ts,
            side,
            fill_type,
            f"{size:.6f}",
            f"${price:.2f}",
            f"${pnl_open:.2f}",
            f"${pnl_close:.2f}",
            f"${fee:.2f}",
            f"{slippage:.2f}" if slippage else "0",
            order_id,
            decision_id
        ])
    
    if rows:
        ws.update(values=rows, range_name=f'A2:K{len(rows)+1}')
    else:
        ws.update(values=[["No fills yet", "", "", "", "", "", "", "", "", "", ""]], range_name='A2:K2')

def update_decisions(spreadsheet):
    """Update decisions tab"""
    ws = spreadsheet.worksheet("🎯 Decisions")
    
    decision_events = load_events("decision")
    
    rows = []
    for dec in decision_events[-50:]:  # Last 50 decisions
        ts = dec.get('ts', '')[:19]
        action = dec.get('action', 'NO_TRADE')
        
        # Get direction from signal_dir or context
        signal_dir = dec.get('signal_dir', 'NONE')
        side = signal_dir if signal_dir != 'NONE' else 'N/A'
        
        # Get confidence from context
        context = dec.get('context', {})
        confidence = context.get('confidence', 0)
        price = context.get('price', 0)
        entry = dec.get('entry_px') or context.get('entry_px')
        sl = dec.get('stop_px') or context.get('stop_px')
        tp = dec.get('tp_px') or context.get('tp_px')
        
        # Get cluster info
        cluster = dec.get('cluster', {})
        clusters_count = context.get('clusters_count', 0)
        cluster_info = f"{clusters_count} clusters" if clusters_count else "No clusters"
        
        # Show action reason if no trade
        if action == "NO_TRADE":
            reason = dec.get('no_trade_reason', context.get('bias_reason', 'N/A'))
            cluster_info = reason[:50] if reason else cluster_info
        
        rows.append([
            ts,
            action,
            side,
            f"{confidence:.1%}" if confidence else "0%",
            f"${price:.2f}" if price else "N/A",
            f"${entry:.2f}" if entry else "-",
            f"${sl:.2f}" if sl else "-",
            f"${tp:.2f}" if tp else "-",
            cluster_info
        ])
    
    if rows:
        ws.update(values=rows, range_name=f'A2:I{len(rows)+1}')
    else:
        ws.update(values=[["No decisions yet", "", "", "", "", "", "", "", ""]], range_name='A2:I2')

def update_health(spreadsheet):
    """Update health metrics"""
    ws = spreadsheet.worksheet("❤️ Health")
    
    health_events = load_events("health")
    
    rows = []
    for health in health_events[-50:]:  # Last 50 heartbeats
        ts = health.get('ts', '')[:19]
        equity = health.get('equity_usd', 0)
        positions = health.get('positions_open', 0)
        daily_pnl = health.get('daily_pnl', 0)
        daily_loss = health.get('daily_loss_usd', 0)
        risk_used = health.get('risk_used_pct', 0)
        pnl_realized = health.get('pnl_realized_usd', 0)
        pnl_unrealized = health.get('pnl_unrealized_usd', 0)
        price_age = health.get('price_age_s', 0)
        ws_connected = "✅" if health.get('ws_connected') else "❌"
        kill_switch = "🔴 ACTIVE" if health.get('kill_switch_active') else "✅ OK"
        
        rows.append([
            ts,
            f"${equity:.2f}",
            str(positions),
            f"${daily_pnl:.2f}" if daily_pnl else "N/A",
            f"${daily_loss:.2f}" if daily_loss is not None else "N/A",
            f"{risk_used:.2%}" if risk_used else "0%",
            f"${pnl_realized:.2f}",
            f"${pnl_unrealized:.2f}",
            f"{price_age:.1f}s",
            ws_connected,
            kill_switch
        ])
    
    if rows:
        ws.update(values=rows, range_name=f'A2:K{len(rows)+1}')
    else:
        ws.update(values=[["No health data", "", "", "", "", "", "", "", "", "", ""]], range_name='A2:K2')

def update_vetoes(spreadsheet):
    """Update vetoes tab"""
    ws = spreadsheet.worksheet("🚫 Vetoes")
    
    veto_events = load_events("veto")
    
    rows = []
    for veto in veto_events:
        ts = veto.get('ts', '')[:19]
        reason = veto.get('reason', 'UNKNOWN')
        fields = veto.get('fields', {})
        details = fields.get('details', 'N/A')
        positions = fields.get('positions_open', 'N/A')
        cooldown = fields.get('cooldown_remaining', 'N/A')
        price = fields.get('current_price', 'N/A')
        side = fields.get('side', 'N/A')
        confidence = fields.get('confidence', 'N/A')
        
        rows.append([
            ts,
            reason,
            details,
            str(positions),
            f"{cooldown:.0f}s" if isinstance(cooldown, (int, float)) else str(cooldown),
            f"${price:.2f}" if isinstance(price, (int, float)) else str(price),
            side,
            f"{confidence:.2%}" if isinstance(confidence, (int, float)) else str(confidence)
        ])
    
    if rows:
        ws.update(values=rows, range_name=f'A2:H{len(rows)+1}')
    else:
        ws.update(values=[["No vetoes", "", "", "", "", "", "", ""]], range_name='A2:H2')

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        # Try to get from .env
        if Path('.env').exists():
            with open('.env', 'r') as f:
                for line in f:
                    if line.startswith('LIVE_DASHBOARD_SHEET_ID='):
                        sheet_id = line.split('=')[1].strip()
                        break
                else:
                    print("❌ Sheet ID not found in .env. Run setup_live_dashboard.py first.")
                    sys.exit(1)
        else:
            print("Usage: python sync_live_data.py <SHEET_ID>")
            print("Or run setup_live_dashboard.py first to create the sheet.")
            sys.exit(1)
    else:
        sheet_id = sys.argv[1]
    
    try:
        sync_to_sheet(sheet_id)
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
