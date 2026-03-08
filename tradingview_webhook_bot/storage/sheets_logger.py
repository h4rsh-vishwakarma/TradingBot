import gspread
import datetime
import logging
import os
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

class GoogleSheetsLogger:
    def __init__(self, sheet_name=None, json_key=None):
        """
        Initialize Google Sheets connection using Absolute Paths.
        """
        # 1. Prioritize .env, then provided arg, then default relative-to-root path
        self.json_key = json_key or os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE") or "tradingview_webhook_bot/tradingview_webhook_bot/storage/service_account.json"
        self.sheet_name = sheet_name or os.getenv("GOOGLE_SHEET_NAME") or "Trading_Bot_Ledger"
        self.sheet = None
        
        self._authenticate()

    def _authenticate(self):
        try:
            # Ensure the path is absolute for Systemd compatibility
            if not os.path.isabs(self.json_key):
                # Construct path relative to the home directory if it looks like a project path
                home = os.path.expanduser("~")
                if "tradingview_webhook_bot" in self.json_key:
                    self.json_key = os.path.join(home, self.json_key)

            if not os.path.exists(self.json_key):
                logger.error(f"❌ Service account file NOT FOUND at: {self.json_key}")
                return

            # Modern Scopes
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"
            ]
            
            creds = Credentials.from_service_account_file(self.json_key, scopes=scopes)
            client = gspread.authorize(creds)
            
            # Open by name (Ensure you have shared the sheet with the service account email)
            self.sheet = client.open(self.sheet_name).sheet1
            logger.info(f"✅ Google Sheets Connected: {self.sheet_name}")
            
        except Exception as e:
            logger.error(f"❌ Sheets Connection Error: {e}")
            self.sheet = None

    def log_trade(self, symbol, action, qty, price, strategy="N/A"):
        """
        Appends a row to the Google Sheet.
        """
        if not self.sheet:
            logger.warning("⚠️ Skipping Sheet Update: Connection not established.")
            return
            
        try:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # Format: Timestamp, Symbol, Action, Quantity, Price, Strategy
            row = [timestamp, str(symbol), str(action), float(qty), float(price), str(strategy)]
            self.sheet.append_row(row)
            logger.info(f"📊 Sheet Updated: {symbol} {action}")
        except Exception as e:
            logger.error(f"❌ Failed to update sheet: {e}")
