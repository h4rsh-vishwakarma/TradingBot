import gspread
from oauth2client.service_account import ServiceAccountCredentials
import datetime
import logging

logger = logging.getLogger(__name__)

class GoogleSheetsLogger:
    def __init__(self, sheet_name="Trading_Bot_Ledger", json_key="service_account.json"):
        try:
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            creds = ServiceAccountCredentials.from_json_keyfile_name(json_key, scope)
            client = gspread.authorize(creds)
            self.sheet = client.open(sheet_name).sheet1
            logger.info(f"✅ Google Sheets Connected: {sheet_name}")
        except Exception as e:
            logger.error(f"❌ Sheets Connection Error: {e}")
            self.sheet = None

    def log_trade(self, symbol, action, qty, price, strategy="N/A"):
        if not self.sheet:
            return
        try:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # Row format: Timestamp, Symbol, Action, Quantity, Price, Strategy
            self.sheet.append_row([timestamp, symbol, action, qty, price, strategy])
            logger.info(f"📊 Sheet Updated: {symbol} {action}")
        except Exception as e:
            logger.error(f"❌ Failed to update sheet: {e}")
