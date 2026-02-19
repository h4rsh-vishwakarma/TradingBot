"""
Observability Module
Contains classes for monitoring and observability, such as Google Sheets logging.
"""

import os
import logging
import gspread
from datetime import datetime, timezone
from typing import List
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

class ObservabilitySheets:
    """Optional creation of an observability spreadsheet for structured events."""
    def __init__(self, creds_path: str, title_prefix: str = "TradingBot_Observability"):
        self.creds_path = creds_path
        self.title = f"{title_prefix}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        self.url = None
        self.spreadsheet = None
        self.client = None
        self.enabled = False
        try:
            if not os.path.exists(self.creds_path):
                raise FileNotFoundError(f"Observability credentials not found: {self.creds_path}")
            scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
            creds = Credentials.from_service_account_file(self.creds_path, scopes=scopes)
            self.client = gspread.authorize(creds)
            self.enabled = True
        except Exception as e:
            logger.warning(f"ObservabilitySheets init failed: {e}")

    def ensure_created(self):
        if not self.enabled or self.spreadsheet is not None:
            return
        try:
            self.spreadsheet = self.client.create(self.title)
            self.url = f"https://docs.google.com/spreadsheets/d/{self.spreadsheet.id}"
            # Remove default worksheet
            try:
                default_ws = self.spreadsheet.sheet1
                self.spreadsheet.del_worksheet(default_ws)
            except Exception:
                pass
            schema = {
                'decisions': ['ts','run_id','session_id','decision_id','mode','symbol','direction','confidence','votes_oi','votes_funding','votes_clusters','multi_tf','action','reason'],
                'orders': ['ts','run_id','session_id','decision_id','order_id','side','entry','stop','tp','qty','rr','combined_conf','executed','validation'],
                'health': ['ts','run_id','session_id','price_age_s','heatmap_age_s','ws_connected','positions_open','risk_used_pct','daily_cap_hit','kill_switch','kill_reason'],
                'errors': ['ts','run_id','session_id','component','severity','message']
            }
            for title, headers in schema.items():
                ws = self.spreadsheet.add_worksheet(title=title, rows=1000, cols=len(headers)+2)
                ws.append_row(headers)
            logger.info(f"Observability spreadsheet created: {self.url}")
        except Exception as e:
            logger.error(f"Failed to create observability spreadsheet: {e}")

    def append(self, sheet_name: str, row: List):
        if not self.enabled or self.spreadsheet is None:
            return
        try:
            ws = self.spreadsheet.worksheet(sheet_name)
            ws.append_row(row)
        except Exception as e:
            logger.warning(f"Observability append failed ({sheet_name}): {e}")
