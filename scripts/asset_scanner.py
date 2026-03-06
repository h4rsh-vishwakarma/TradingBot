import requests
import json
import os

def fetch_top_300_futures():
    try:
        url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
        response = requests.get(url).json()
        # Sirf USDT pairs aur Top 300 volume/rank ke hisab se (Binance default order)
        symbols = [s['symbol'] for s in response['symbols'] if s['quoteAsset'] == 'USDT'][:300]
        
        os.makedirs('config', exist_ok=True)
        with open('config/top_300_assets.json', 'w') as f:
            json.dump(symbols, f)
        print(f"✅ Successfully updated Top {len(symbols)} assets.")
    except Exception as e:
        print(f"❌ Error fetching assets: {e}")

if __name__ == "__main__":
    fetch_top_300_futures()
