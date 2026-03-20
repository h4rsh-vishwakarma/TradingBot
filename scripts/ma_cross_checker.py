import pandas as pd
import requests
import json
import time
import os

def get_ma_signal(symbol):
    try:
        # Fetching 1h klines
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=1h&limit=300"
        response = requests.get(url, timeout=10)
        data = response.json()
        
        # Binance klines index: 0:TS, 1:Open, 2:High, 3:Low, 4:Close, 5:Vol
        df = pd.DataFrame(data)
        if df.empty: return None
        
        # Selecting and naming columns properly
        df = df.iloc[:, [0, 4]] 
        df.columns = ['timestamp', 'close']
        df['close'] = df['close'].astype(float)
        
        # Calculating MAs
        ma50 = df['close'].rolling(window=50).mean()
        ma200 = df['close'].rolling(window=200).mean()
        
        last_ma50 = ma50.iloc[-1]
        last_ma200 = ma200.iloc[-1]
        prev_ma50 = ma50.iloc[-2]
        prev_ma200 = ma200.iloc[-2]

        # Signal Logic
        if prev_ma50 <= prev_ma200 and last_ma50 > last_ma200:
            return "BUY"
        elif prev_ma50 >= prev_ma200 and last_ma50 < last_ma200:
            return "SELL"
    except Exception as e:
        print(f"⚠️ Error scanning {symbol}: {e}")
    return None

def scan_all():
    config_path = '/home/ubuntu/tradingview_webhook_bot/config/top_300_assets.json'
    if not os.path.exists(config_path):
        print("❌ config/top_300_assets.json not found!")
        return []
        
    with open(config_path, 'r') as f:
        assets = json.load(f)
    
    signals = []
    print(f"🔍 Starting deep scan of {len(assets)} assets...")
    
    # Scanning first 50 for speed test
    for symbol in assets[:50]:
        sig = get_ma_signal(symbol)
        if sig:
            print(f"🎯 SIGNAL FOUND: {symbol} -> {sig}")
            signals.append({"symbol": symbol, "action": sig})
        time.sleep(0.05) 
    
    return signals

if __name__ == "__main__":
    found = scan_all()
    print(f"\n✅ Scan Complete. Total signals found: {len(found)}")
    if found:
        print(f"Signals: {json.dumps(found, indent=2)}")
