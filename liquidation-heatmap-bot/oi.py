import time
import datetime
import requests
import gspread
import logging
from logging.handlers import RotatingFileHandler
from oauth2client.service_account import ServiceAccountCredentials

# === Configuration ===
SERVICE_ACCOUNT_FILE = 'creds_vit.json'
SHEET_ID = '1ysGcPSyyJrlX3Wo7C4s7TCkRVF-d9YlvG7LbZeNNQ8k'
SHEET_NAME = 'oi'
POLL_INTERVAL = 300  # 5 minutes
LOG_FILE = 'btc_oi_logger.log'
LOG_MAX_BYTES = 5 * 1024 * 1024  # 5 MB per file
LOG_BACKUP_COUNT = 3  # keep up to 3 old logs

# === Logging Setup ===
logger = logging.getLogger('BTC_OI_Logger')
logger.setLevel(logging.INFO)
handler = RotatingFileHandler(LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT)
formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s', '%Y-%m-%d %H:%M:%S')
handler.setFormatter(formatter)
logger.addHandler(handler)

# === Google Sheets Setup ===
try:
    scope = ['https://www.googleapis.com/auth/spreadsheets']
    creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_ACCOUNT_FILE, scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)

    # If sheet is empty or only has headers, initialize headers
    existing = sheet.get_all_values()
    if not existing or existing == [['']]:
        sheet.append_row(['Timestamp (UTC)', 'Open Interest (USD)', 'BTC Price (USD)'])
        logger.info('Initialized headers in Google Sheet')
    else:
        # Ensure headers are correct; update if necessary
        headers = existing[0]
        desired = ['Timestamp (UTC)', 'Open Interest (USD)', 'BTC Price (USD)']
        if headers != desired:
            sheet.delete_row(1)
            sheet.insert_row(desired, 1)
            logger.info('Replaced headers with correct format')
    logger.info('Connected to Google Sheet successfully')
except Exception as e:
    logger.exception('Failed to initialize Google Sheets connection')
    raise

# === Fetch Open Interest and Price from Binance ===
def fetch_open_interest_and_price(symbol='BTCUSDT'):
    # Open interest in contracts
    oi_resp = requests.get(
        'https://fapi.binance.com/fapi/v1/openInterest',
        params={'symbol': symbol},
        timeout=10
    )
    oi_resp.raise_for_status()
    oi_contracts = float(oi_resp.json()['openInterest'])

    # BTC spot price
    price_resp = requests.get(
        'https://api.binance.com/api/v3/ticker/price',
        params={'symbol': symbol},
        timeout=10
    )
    price_resp.raise_for_status()
    price = float(price_resp.json()['price'])

    # Convert open interest to USD value
    oi_usd = oi_contracts * price
    return oi_usd, price

# === Main Loop ===
def main():
    logger.info('Starting main loop')
    while True:
        try:
            now_utc = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            oi_usd, btc_price = fetch_open_interest_and_price()
            # Round values for logging and sheet
            oi_rounded = round(oi_usd, 2)
            price_rounded = round(btc_price, 2)
            sheet.append_row([now_utc, oi_rounded, price_rounded])
            logger.info(f'Appended OI: ${oi_rounded:,.2f}, Price: ${price_rounded:,.2f} at {now_utc}')
        except Exception:
            logger.exception('Error during fetch or append')
        time.sleep(POLL_INTERVAL)

if __name__ == '__main__':
    try:
        main()
    except Exception:
        logger.exception('Unhandled exception in main')
