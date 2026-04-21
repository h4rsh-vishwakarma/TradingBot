import os
import pandas as pd
from binance.client import Client
from dotenv import load_dotenv

# Path setup — matches existing fetch_historical_data.py convention
ENV_FILE_PATH = "/etc/tradingbot/env_vars"
load_dotenv(dotenv_path=ENV_FILE_PATH)

# Initialize Binance Futures client
client = Client(os.getenv('BINANCE_API_KEY'), os.getenv('BINANCE_API_SECRET'))

# All 16 user symbols for the 4H tournament
SYMBOLS = [
    'FILUSDT', 'OPUSDT', 'LDOUSDT', 'UNIUSDT',
    'NEARUSDT', 'INJUSDT', 'SUIUSDT', 'ARBUSDT',
    'AAVEUSDT', 'DOGEUSDT', 'APTUSDT', 'ATOMUSDT',
    'SOLUSDT', 'LINKUSDT', 'AVAXUSDT', 'DOTUSDT',
]

OUTPUT_DIR = 'storage/backtest_data'


def download_4h_data(symbol):
    """
    Downloads 3 years of 4H OHLCV futures data from Binance and saves as CSV.
    Returns True on success, False on failure.
    """
    print(f"Fetching 4H data for {symbol}...")

    try:
        klines = client.futures_historical_klines(symbol, '4h', '3 years ago UTC')

        if not klines:
            print(f"  WARNING: No data returned for {symbol}. Skipping.")
            return False

        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_av', 'trades', 'tb_base_av', 'tb_quote_av', 'ignore'
        ])

        # Keep only the columns needed by the backtest engine
        df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]

        # Convert timestamp from milliseconds to human-readable datetime
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

        # Numeric conversion for OHLCV columns
        cols = ['open', 'high', 'low', 'close', 'volume']
        df[cols] = df[cols].apply(pd.to_numeric, errors='coerce')

        # Save to disk
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        file_path = os.path.join(OUTPUT_DIR, f'{symbol}_3y_4h.csv')
        df.to_csv(file_path, index=False)

        print(f"  OK: {len(df)} rows -> {file_path}")
        return True

    except Exception as e:
        print(f"  ERROR fetching {symbol}: {e}")
        return False


if __name__ == "__main__":
    print(f"Starting 4H data download for {len(SYMBOLS)} symbols (3-year lookback)...")
    print("-" * 60)

    success_count = 0
    failed_symbols = []

    for symbol in SYMBOLS:
        ok = download_4h_data(symbol)
        if ok:
            success_count += 1
        else:
            failed_symbols.append(symbol)

    print("-" * 60)
    print(f"Done. {success_count}/{len(SYMBOLS)} symbols downloaded successfully.")

    if failed_symbols:
        print(f"Failed symbols: {', '.join(failed_symbols)}")
    else:
        print("All symbols fetched without errors. Ready for 4H tournament.")
