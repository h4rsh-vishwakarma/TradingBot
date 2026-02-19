#!/usr/bin/env python3
"""
Live Trading Dashboard - Google Sheets Integration
Real-time trading decisions, orders, fills, and health status for supervisor visibility
"""

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timezone
import logging
import threading
import time
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class LiveTradingDashboard:
    """Upload live trading data to Google Sheets for supervisor monitoring"""
    
    def __init__(self, spreadsheet_key: str, credentials_path: str = '/home/ubuntu/trading_bot/credentials.json'):
        """
        Initialize dashboard connection
        
        Args:
            spreadsheet_key: Google Sheets ID (create new sheet and share with service account)
            credentials_path: Path to service account JSON credentials
        """
        self.spreadsheet_key = spreadsheet_key
        self.credentials_path = credentials_path
        self.client = None
        self.sheet = None
        self._lock = threading.Lock()
        self._connect()
        
    def _connect(self):
        """Establish connection to Google Sheets"""
        try:
            scope = ['https://spreadsheets.google.com/feeds',
                    'https://www.googleapis.com/auth/drive']
            creds = ServiceAccountCredentials.from_json_keyfile_name(
                self.credentials_path, scope)
            self.client = gspread.authorize(creds)
            self.sheet = self.client.open_by_key(self.spreadsheet_key)
            logger.info(f"Connected to live trading dashboard: {self.spreadsheet_key}")
            self._initialize_worksheets()
        except Exception as e:
            logger.error(f"Failed to connect to dashboard: {e}")
            raise
    
    def _initialize_worksheets(self):
        """Create/verify required worksheets"""
        required_sheets = {
            'Decisions': ['Timestamp', 'Direction', 'Action', 'Strength', 'S_Long', 'S_Short', 
                         'Votes_M1', 'Votes_M2', 'Votes_M3', 'Cluster_Distance', 'Edge_BPS', 
                         'Confidence', 'Reason', 'Price'],
            'Orders': ['Timestamp', 'Order_ID', 'Side', 'Type', 'Price', 'Quantity', 
                      'Status', 'Decision_ID'],
            'Fills': ['Timestamp', 'Fill_ID', 'Order_ID', 'Price', 'Quantity', 'Fee', 
                     'PnL_Open', 'PnL_Close'],
            'Health': ['Timestamp', 'Equity_USD', 'PnL_Realized', 'PnL_Unrealized', 
                      'Positions_Open', 'Risk_Used_Pct', 'Price_Age_S', 'Heatmap_Age_S', 
                      'WS_Connected', 'CoinGlass_OK'],
            'Summary': ['Metric', 'Value', 'Last_Updated']
        }
        
        existing_sheets = {ws.title for ws in self.sheet.worksheets()}
        
        for sheet_name, headers in required_sheets.items():
            if sheet_name not in existing_sheets:
                try:
                    ws = self.sheet.add_worksheet(title=sheet_name, rows=1000, cols=len(headers))
                    ws.update('A1', [headers])
                    logger.info(f"Created worksheet: {sheet_name}")
                except Exception as e:
                    logger.warning(f"Could not create {sheet_name}: {e}")
            else:
                # Verify headers
                ws = self.sheet.worksheet(sheet_name)
                existing_headers = ws.row_values(1)
                if not existing_headers:
                    ws.update('A1', [headers])
                    logger.info(f"Added headers to {sheet_name}")
    
    def insert_decision(self, decision: Dict[str, Any]):
        """Insert trading decision to Decisions sheet"""
        try:
            with self._lock:
                ws = self.sheet.worksheet('Decisions')
                
                row = [
                    decision.get('ts', datetime.now(timezone.utc).isoformat()),
                    decision.get('signal_dir', 'NONE'),
                    decision.get('action', 'NO_TRADE'),
                    decision.get('signal_strength', 'NONE'),
                    decision.get('S_long', 0.0),
                    decision.get('S_short', 0.0),
                    decision.get('votes', {}).get('m1', 'NONE'),
                    decision.get('votes', {}).get('m2', 'NONE'),
                    decision.get('votes', {}).get('m3', 'NONE'),
                    decision.get('cluster', {}).get('distance_bps', ''),
                    decision.get('costs', {}).get('edge_bps', ''),
                    decision.get('context', {}).get('confidence', 0.0),
                    decision.get('no_trade_reason', decision.get('context', {}).get('bias_reason', '')),
                    decision.get('context', {}).get('price', '')
                ]
                
                ws.append_row(row, value_input_option='RAW')
                
                # Keep only last 500 rows
                self._trim_sheet(ws, 500)
                
        except Exception as e:
            logger.error(f"Failed to insert decision: {e}")
    
    def insert_order(self, order: Dict[str, Any]):
        """Insert order to Orders sheet"""
        try:
            with self._lock:
                ws = self.sheet.worksheet('Orders')
                
                row = [
                    order.get('ts', datetime.now(timezone.utc).isoformat()),
                    order.get('order_id', ''),
                    order.get('side', ''),
                    order.get('type', ''),
                    order.get('px', ''),
                    order.get('qty', ''),
                    order.get('status', ''),
                    order.get('decision_id', '')
                ]
                
                ws.append_row(row, value_input_option='RAW')
                self._trim_sheet(ws, 200)
                
        except Exception as e:
            logger.error(f"Failed to insert order: {e}")
    
    def insert_fill(self, fill: Dict[str, Any]):
        """Insert fill to Fills sheet"""
        try:
            with self._lock:
                ws = self.sheet.worksheet('Fills')
                
                row = [
                    fill.get('ts', datetime.now(timezone.utc).isoformat()),
                    fill.get('fill_id', ''),
                    fill.get('order_id', ''),
                    fill.get('px', ''),
                    fill.get('qty', ''),
                    fill.get('fee', ''),
                    fill.get('pnl_open', ''),
                    fill.get('pnl_close', '')
                ]
                
                ws.append_row(row, value_input_option='RAW')
                self._trim_sheet(ws, 200)
                
        except Exception as e:
            logger.error(f"Failed to insert fill: {e}")
    
    def insert_health(self, health: Dict[str, Any]):
        """Insert health snapshot to Health sheet"""
        try:
            with self._lock:
                ws = self.sheet.worksheet('Health')
                
                row = [
                    health.get('ts', datetime.now(timezone.utc).isoformat()),
                    health.get('equity_usd', ''),
                    health.get('pnl_realized_usd', ''),
                    health.get('pnl_unrealized_usd', ''),
                    health.get('positions_open', 0),
                    health.get('risk_used_pct', 0.0),
                    health.get('price_age_s', ''),
                    health.get('heatmap_age_s', ''),
                    health.get('ws_connected', False),
                    health.get('coinglass_ok', False)
                ]
                
                ws.append_row(row, value_input_option='RAW')
                self._trim_sheet(ws, 100)
                
                # Update summary
                self._update_summary(health)
                
        except Exception as e:
            logger.error(f"Failed to insert health: {e}")
    
    def _update_summary(self, health: Dict[str, Any]):
        """Update Summary sheet with key metrics"""
        try:
            ws = self.sheet.worksheet('Summary')
            
            summary_data = [
                ['Equity (USD)', health.get('equity_usd', 0), datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')],
                ['PnL Realized (USD)', health.get('pnl_realized_usd', 0), datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')],
                ['PnL Unrealized (USD)', health.get('pnl_unrealized_usd', 0), datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')],
                ['Open Positions', health.get('positions_open', 0), datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')],
                ['Risk Used %', health.get('risk_used_pct', 0), datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')],
                ['WebSocket Connected', health.get('ws_connected', False), datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')],
                ['CoinGlass Scraper OK', health.get('coinglass_ok', False), datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')],
                ['Data Age (seconds)', health.get('price_age_s', 0), datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')]
            ]
            
            ws.clear()
            ws.update('A1', [['Metric', 'Value', 'Last Updated']] + summary_data)
            
        except Exception as e:
            logger.error(f"Failed to update summary: {e}")
    
    def _trim_sheet(self, worksheet, max_rows: int):
        """Keep only last N rows (plus header)"""
        try:
            all_values = worksheet.get_all_values()
            if len(all_values) > max_rows + 1:  # +1 for header
                # Keep header + last max_rows
                worksheet.clear()
                worksheet.update('A1', [all_values[0]] + all_values[-(max_rows):])
        except Exception as e:
            logger.warning(f"Failed to trim sheet {worksheet.title}: {e}")


def create_supervisor_dashboard(credentials_path: str = '/home/ubuntu/trading_bot/credentials.json') -> str:
    """
    Create a new Google Sheet for supervisor monitoring
    
    Returns:
        Spreadsheet ID to add to config
    """
    try:
        scope = ['https://spreadsheets.google.com/feeds',
                'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name(credentials_path, scope)
        client = gspread.authorize(creds)
        
        # Create new spreadsheet
        sheet_name = f"Live_Trading_Dashboard_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        sheet = client.create(sheet_name)
        
        print(f"✅ Created dashboard: {sheet_name}")
        print(f"📊 Spreadsheet ID: {sheet.id}")
        print(f"🔗 URL: https://docs.google.com/spreadsheets/d/{sheet.id}")
        print(f"\n📝 Share this sheet with your supervisor (View or Edit access)")
        print(f"⚙️  Add this ID to your config: LIVE_DASHBOARD_KEY = '{sheet.id}'")
        
        return sheet.id
        
    except Exception as e:
        print(f"❌ Failed to create dashboard: {e}")
        raise


if __name__ == '__main__':
    # Create new dashboard
    print("Creating live trading dashboard...")
    sheet_id = create_supervisor_dashboard()
    
    # Test connection
    print("\nTesting dashboard connection...")
    dashboard = LiveTradingDashboard(sheet_id)
    
    # Insert test data
    dashboard.insert_health({
        'ts': datetime.now(timezone.utc).isoformat(),
        'equity_usd': 1000.0,
        'pnl_realized_usd': 0.0,
        'pnl_unrealized_usd': 0.0,
        'positions_open': 0,
        'risk_used_pct': 0.0,
        'price_age_s': 1.5,
        'heatmap_age_s': 45,
        'ws_connected': True,
        'coinglass_ok': True
    })
    
    print("✅ Test data inserted successfully!")
    print(f"🔗 View dashboard: https://docs.google.com/spreadsheets/d/{sheet_id}")
