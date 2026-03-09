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

            # Open the sheet (Make sure it's the first tab 'Trades')
            spreadsheet = client.open(self.sheet_name)
            self.sheet = spreadsheet.worksheet("Trades")
            logger.info(f"✅ Google Sheets Connected to tab 'Trades'")

        except Exception as e:
            logger.error(f"❌ Sheets Connection Error: {e}")
            self.sheet = None

    def log_trade(self, signal_id, symbol, action, qty, price, strategy="N/A", indicator="N/A", pnl=0.0):
        """
        Logs detailed trade data including PnL for Analytics formulas.
        Row Structure: [ID, Time, Symbol, Action, Qty, Price, PnL, Indicator, Strategy]
        """
        if not self.sheet:
            logger.warning("⚠️ Skipping Sheet Update: Connection not established.")
            return

        try:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # 📊 Row Mapping for your Dashboard formulas
            # Column A: ID | B: Time | C: Symbol | D: Action | E: Qty | F: Price | G: PnL | H: Indicator
            row = [
                str(signal_id),
                timestamp,
                str(symbol).upper(),
                str(action).upper(),
                float(qty),
                float(price),
                float(pnl),  # 💰 This goes to Column G for your SUMIF formulas
                str(indicator),
                str(strategy)
            ]
            
            self.sheet.append_row(row)
            logger.info(f"📊 Sheet Updated: {symbol} | PnL: ${pnl}")
        except Exception as e:
            logger.error(f"❌ Failed to update sheet: {e}")
