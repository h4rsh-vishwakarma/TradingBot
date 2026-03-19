import os
import pandas as pd
from binance.client import Client
from datetime import datetime
from dotenv import load_dotenv

# Path setup
ENV_FILE_PATH = "/etc/tradingbot/env_vars"
load_dotenv(dotenv_path=ENV_FILE_PATH)

client = Client(os.getenv('BINANCE_API_KEY'), os.getenv('BINANCE_API_SECRET'))

def download_data(symbol, interval='15m', lookback='1 year ago UTC'):
    print(f"📥 Fetching 1 year of {symbol} data...")
    klines = client.futures_historical_klines(symbol, interval, lookback)
    
    df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 
                                       'close_time', 'quote_av', 'trades', 'tb_base_av', 'tb_quote_av', 'ignore'])
    
    # Data Cleaning (RAM optimization)
    df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    
    # Save to CSV
    os.makedirs('storage/backtest_data', exist_ok=True)
    file_path = f'storage/backtest_data/{symbol}_1y_15m.csv'
    df.to_csv(file_path, index=False)
    print(f"✅ Saved to {file_path}")

if __name__ == "__main__":
    symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
    for s in symbols:
        download_data(s)
