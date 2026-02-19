"""
Direct Binance API calls for real-time data (bypasses Google Sheets caching).
Used as fallback/primary source for critical time-sensitive data.
"""
import requests
import pandas as pd
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

class BinanceDirectAPI:
    """Direct Binance API client for real-time data without Google Sheets caching."""
    
    BASE_URL = "https://fapi.binance.com"
    
    def __init__(self, symbol="BTCUSDT"):
        self.symbol = symbol
        
    def get_funding_rate(self, limit=100):
        """
        Get funding rate history directly from Binance API.
        
        Args:
            limit: Number of records to fetch (max 1000, default 100)
            
        Returns:
            DataFrame with columns: Timestamp, Funding Rate, Mark Price
        """
        try:
            endpoint = f"{self.BASE_URL}/fapi/v1/fundingRate"
            params = {
                'symbol': self.symbol,
                'limit': min(limit, 1000)  # API max is 1000
            }
            
            response = requests.get(endpoint, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if not data:
                logger.warning("No funding rate data returned from Binance API")
                return pd.DataFrame()
            
            # Convert to DataFrame
            df = pd.DataFrame(data)
            
            # Rename columns to match our format
            df = df.rename(columns={
                'fundingTime': 'Timestamp',
                'fundingRate': 'Funding Rate',
                'markPrice': 'Mark Price'
            })
            
            # Convert timestamp from milliseconds to datetime
            df['Timestamp'] = pd.to_datetime(df['Timestamp'], unit='ms', utc=True)
            
            # Convert funding rate to percentage (Binance returns decimal)
            df['Funding Rate'] = df['Funding Rate'].astype(float)
            
            # Convert mark price to float
            if 'Mark Price' in df.columns:
                df['Mark Price'] = df['Mark Price'].astype(float)
            
            # Sort by timestamp
            df = df.sort_values('Timestamp')
            
            # Keep only last 48 hours (matching get_funding_rate_data logic)
            cutoff_time = df['Timestamp'].max() - pd.Timedelta(hours=48)
            df = df[df['Timestamp'] >= cutoff_time]
            
            logger.info(f"✅ Fetched {len(df)} funding rate records from Binance API, latest: {df['Timestamp'].max()}")
            return df[['Timestamp', 'Funding Rate', 'Mark Price']]
            
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Error fetching funding rate from Binance API: {str(e)}")
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"❌ Unexpected error in get_funding_rate: {str(e)}")
            return pd.DataFrame()
    
    def get_open_interest(self):
        """
        Get current open interest directly from Binance API.
        
        Returns:
            dict with 'openInterest' (in contracts) and 'timestamp'
        """
        try:
            endpoint = f"{self.BASE_URL}/fapi/v1/openInterest"
            params = {'symbol': self.symbol}
            
            response = requests.get(endpoint, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # Convert timestamp from milliseconds
            data['timestamp'] = datetime.fromtimestamp(data['time'] / 1000, tz=timezone.utc)
            
            logger.info(f"✅ Fetched OI from Binance API: {data['openInterest']} contracts")
            return data
            
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Error fetching OI from Binance API: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"❌ Unexpected error in get_open_interest: {str(e)}")
            return None
    
    def get_mark_price(self):
        """
        Get current mark price directly from Binance API.
        
        Returns:
            dict with 'markPrice', 'indexPrice', 'lastFundingRate', 'time'
        """
        try:
            endpoint = f"{self.BASE_URL}/fapi/v1/premiumIndex"
            params = {'symbol': self.symbol}
            
            response = requests.get(endpoint, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # Convert timestamp from milliseconds
            data['timestamp'] = datetime.fromtimestamp(data['time'] / 1000, tz=timezone.utc)
            
            return data
            
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Error fetching mark price from Binance API: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"❌ Unexpected error in get_mark_price: {str(e)}")
            return None


if __name__ == "__main__":
    # Test the API
    logging.basicConfig(level=logging.INFO)
    
    api = BinanceDirectAPI("BTCUSDT")
    
    print("\n=== Testing Funding Rate API ===")
    df = api.get_funding_rate(limit=10)
    if not df.empty:
        print(f"Fetched {len(df)} records")
        print(f"Latest timestamp: {df['Timestamp'].max()}")
        print(f"Latest funding rate: {df['Funding Rate'].iloc[-1]:.6f} ({df['Funding Rate'].iloc[-1] * 100:.4f}%)")
        print("\nLast 3 records:")
        print(df.tail(3).to_string())
    else:
        print("Failed to fetch funding rate data")
    
    print("\n=== Testing Open Interest API ===")
    oi = api.get_open_interest()
    if oi:
        print(f"Current OI: {oi['openInterest']} contracts")
        print(f"Timestamp: {oi['timestamp']}")
    else:
        print("Failed to fetch OI data")
    
    print("\n=== Testing Mark Price API ===")
    mark = api.get_mark_price()
    if mark:
        print(f"Mark Price: ${float(mark['markPrice']):,.2f}")
        print(f"Index Price: ${float(mark['indexPrice']):,.2f}")
        print(f"Last Funding Rate: {float(mark['lastFundingRate']):.6f}")
        print(f"Timestamp: {mark['timestamp']}")
    else:
        print("Failed to fetch mark price data")
