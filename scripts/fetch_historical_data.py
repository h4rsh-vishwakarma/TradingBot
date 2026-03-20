import os
import pandas as pd
from binance.client import Client
from datetime import datetime
from dotenv import load_dotenv

# Path setup
ENV_FILE_PATH = "/etc/tradingbot/env_vars"
load_dotenv(dotenv_path=ENV_FILE_PATH)

# Initialize Binance Client
client = Client(os.getenv('BINANCE_API_KEY'), os.getenv('BINANCE_API_SECRET'))

def download_data(symbol, interval='15m', lookback='3 years ago UTC'):
    """
    Fetches 3 years of historical futures data from Binance.
    """
    print(f"📥 Starting 3-Year Data Fetch for {symbol} ({interval})...")
    
    try:
        # Fetching Futures Klines
        klines = client.futures_historical_klines(symbol, interval, lookback)

        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_av', 'trades', 'tb_base_av', 'tb_quote_av', 'ignore'
        ])

        # Data Cleaning & RAM Optimization
        # Hum sirf wahi columns rakh rahe hain jo Backtesting Engine ko chahiye
        df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
        
        # Convert timestamp to human-readable datetime
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        
        # Numeric conversion for price columns
        cols = ['open', 'high', 'low', 'close', 'volume']
        df[cols] = df[cols].apply(pd.to_numeric, errors='coerce')

        # Create directory if not exists
        os.makedirs('storage/backtest_data', exist_ok=True)
        
        # File naming update to reflect 3y data
        file_path = f'storage/backtest_data/{symbol}_3y_15m.csv'
        
        df.to_csv(file_path, index=False)
        print(f"✅ Successfully saved {len(df)} rows to {file_path}")

    except Exception as e:
        print(f"❌ Error fetching data for {symbol}: {e}")

if __name__ == "__main__":
    # Top Alpha Symbols for Tournament
    symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
    
    print(f"🚀 Data Migration: Shifting from 1-Year to 3-Year Lookback...")
    
    for s in symbols:
        download_data(s)
        
    print("\n🏁 Data Sync Complete. Ready for 3-Year Tournament Scan.")
