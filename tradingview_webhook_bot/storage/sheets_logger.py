import gspread
import datetime
import logging
import os
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

class GoogleSheetsLogger:
    def __init__(self, sheet_name=None, json_key=None):
        """
        Initialize Google Sheets using secure system paths.
        """
        # 1. Prioritize Environment Variable (Set in /etc/tradingbot/env_vars)
        # 2. Fallback to the new secure production path
        # 3. Last fallback to the legacy project path
        self.json_key = json_key or os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE") or "/etc/tradingbot/service_account.json"
        
        # Legacy fallback check for safety
        if not os.path.exists(self.json_key):
             legacy_path = "/home/ubuntu/tradingview_webhook_bot/tradingview_webhook_bot/storage/service_account.json"
             if os.path.exists(legacy_path):
                 self.json_key = legacy_path

        self.sheet_name = sheet_name or os.getenv("GOOGLE_SHEET_NAME") or "Trading_Bot_Ledger"
        self.sheet = None
        self._authenticate()

    def _authenticate(self):
        try:
            if not os.path.exists(self.json_key):
                logger.error(f"❌ Service account file NOT FOUND at: {self.json_key}")
                return

            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"
            ]

            creds = Credentials.from_service_account_file(self.json_key, scopes=scopes)
            client = gspread.authorize(creds)

            # Open the sheet
            self.sheet = client.open(self.sheet_name).sheet1
            logger.info(f"✅ Google Sheets Connected: {self.sheet_name}")

        except Exception as e:
            logger.error(f"❌ Sheets Connection Error: {e}")
            self.sheet = None

    def log_trade(self, symbol, action, qty, price, strategy="N/A"):
        if not self.sheet:
            logger.warning("⚠️ Skipping Sheet Update: Connection not established.")
            return

        try:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            row = [timestamp, str(symbol).upper(), str(action).upper(), float(qty), float(price), str(strategy)]
            self.sheet.append_row(row)
            logger.info(f"📊 Sheet Updated: {symbol} {action}")
        except Exception as e:
            logger.error(f"❌ Failed to update sheet: {e}")
