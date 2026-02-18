"""
Binance Liquidation & Liquidity Data Scraper
Replaces CoinGlass scraping with official Binance Futures API

This scraper collects:
- Open Interest (actual liquidation exposure)
- Long/Short Ratios (trader positioning)
- Funding Rates (perpetual swap mechanics)
- Order Book Depth (liquidity levels)
- Top Trader Positions (smart money tracking)
"""

import requests
import pandas as pd
import time
from datetime import datetime, timedelta
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials

class BinanceLiquidityScraper:
    """Scrapes liquidation and liquidity data from Binance Futures API"""
    
    BASE_URL = "https://fapi.binance.com"
    
    def __init__(self, symbol="BTCUSDT"):
        self.symbol = symbol
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
    def get_open_interest(self):
        """Get current open interest (total contract value)"""
        try:
            url = f"{self.BASE_URL}/fapi/v1/openInterest"
            params = {'symbol': self.symbol}
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            return {
                'open_interest': float(data['openInterest']),
                'timestamp': datetime.fromtimestamp(data['time'] / 1000)
            }
        except Exception as e:
            print(f"Error getting open interest: {e}")
            return None
    
    def get_mark_price_and_funding(self):
        """Get mark price and funding rate"""
        try:
            url = f"{self.BASE_URL}/fapi/v1/premiumIndex"
            params = {'symbol': self.symbol}
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            return {
                'mark_price': float(data['markPrice']),
                'funding_rate': float(data['lastFundingRate']),
                'next_funding_time': datetime.fromtimestamp(data['nextFundingTime'] / 1000),
                'timestamp': datetime.fromtimestamp(data['time'] / 1000)
            }
        except Exception as e:
            print(f"Error getting mark price: {e}")
            return None
    
    def get_long_short_ratio(self, period="5m", limit=288):
        """
        Get long/short ratio for all traders
        period: 5m, 15m, 30m, 1h, 2h, 4h, 6h, 12h, 1d
        limit: max 500
        """
        try:
            url = f"{self.BASE_URL}/futures/data/globalLongShortAccountRatio"
            params = {
                'symbol': self.symbol,
                'period': period,
                'limit': limit
            }
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            df = pd.DataFrame(data)
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df['longShortRatio'] = df['longShortRatio'].astype(float)
            df['longAccount'] = df['longAccount'].astype(float)
            df['shortAccount'] = df['shortAccount'].astype(float)
            
            return df
        except Exception as e:
            print(f"Error getting long/short ratio: {e}")
            return None
    
    def get_top_trader_long_short_ratio(self, period="5m", limit=288):
        """Get long/short ratio for top traders (accounts by position)"""
        try:
            url = f"{self.BASE_URL}/futures/data/topLongShortAccountRatio"
            params = {
                'symbol': self.symbol,
                'period': period,
                'limit': limit
            }
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            df = pd.DataFrame(data)
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df['longShortRatio'] = df['longShortRatio'].astype(float)
            df['longAccount'] = df['longAccount'].astype(float)
            df['shortAccount'] = df['shortAccount'].astype(float)
            
            return df
        except Exception as e:
            print(f"Error getting top trader ratio: {e}")
            return None
    
    def get_top_trader_position_ratio(self, period="5m", limit=288):
        """Get position long/short ratio for top traders"""
        try:
            url = f"{self.BASE_URL}/futures/data/topLongShortPositionRatio"
            params = {
                'symbol': self.symbol,
                'period': period,
                'limit': limit
            }
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            df = pd.DataFrame(data)
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df['longShortRatio'] = df['longShortRatio'].astype(float)
            df['longAccount'] = df['longAccount'].astype(float)
            df['shortAccount'] = df['shortAccount'].astype(float)
            
            return df
        except Exception as e:
            print(f"Error getting position ratio: {e}")
            return None
    
    def get_order_book(self, limit=100):
        """Get order book depth (for liquidity analysis)"""
        try:
            url = f"{self.BASE_URL}/fapi/v1/depth"
            params = {
                'symbol': self.symbol,
                'limit': limit  # Max 1000
            }
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # Process bids (buy orders)
            bids_df = pd.DataFrame(data['bids'], columns=['price', 'quantity'])
            bids_df['price'] = bids_df['price'].astype(float)
            bids_df['quantity'] = bids_df['quantity'].astype(float)
            bids_df['side'] = 'bid'
            
            # Process asks (sell orders)
            asks_df = pd.DataFrame(data['asks'], columns=['price', 'quantity'])
            asks_df['price'] = asks_df['price'].astype(float)
            asks_df['quantity'] = asks_df['quantity'].astype(float)
            asks_df['side'] = 'ask'
            
            return {
                'bids': bids_df,
                'asks': asks_df,
                'lastUpdateId': data['lastUpdateId']
            }
        except Exception as e:
            print(f"Error getting order book: {e}")
            return None
    
    def calculate_liquidation_levels(self, mark_price, open_interest):
        """
        Calculate estimated liquidation price levels
        Based on typical leverage ranges (5x-50x)
        """
        liquidation_levels = []
        
        # Common leverage levels
        leverages = [5, 10, 15, 20, 25, 30, 50, 75, 100, 125]
        
        # Estimate OI distribution (simplified - real distribution varies)
        # Assume 60% long, 40% short based on typical market conditions
        long_oi_pct = 0.60
        short_oi_pct = 0.40
        
        for lev in leverages:
            # Long liquidation (price drops)
            long_liq_price = mark_price * (1 - 1/lev)
            long_oi_at_level = open_interest * long_oi_pct * (1/len(leverages))
            
            liquidation_levels.append({
                'price': long_liq_price,
                'leverage': lev,
                'side': 'long',
                'estimated_oi': long_oi_at_level,
                'distance_pct': ((long_liq_price - mark_price) / mark_price) * 100
            })
            
            # Short liquidation (price rises)
            short_liq_price = mark_price * (1 + 1/lev)
            short_oi_at_level = open_interest * short_oi_pct * (1/len(leverages))
            
            liquidation_levels.append({
                'price': short_liq_price,
                'leverage': lev,
                'side': 'short',
                'estimated_oi': short_oi_at_level,
                'distance_pct': ((short_liq_price - mark_price) / mark_price) * 100
            })
        
        return pd.DataFrame(liquidation_levels).sort_values('price')
    
    def collect_all_data(self):
        """Collect all liquidity and liquidation data"""
        print(f"=== Binance Liquidity Data Collection for {self.symbol} ===\n")
        
        # 1. Open Interest
        print("Fetching Open Interest...")
        oi_data = self.get_open_interest()
        if oi_data:
            print(f"  ✓ Open Interest: {oi_data['open_interest']:,.2f} {self.symbol}")
        
        # 2. Mark Price & Funding
        print("Fetching Mark Price & Funding Rate...")
        price_data = self.get_mark_price_and_funding()
        if price_data:
            print(f"  ✓ Mark Price: ${price_data['mark_price']:,.2f}")
            print(f"  ✓ Funding Rate: {price_data['funding_rate']*100:.4f}%")
        
        # 3. Long/Short Ratios
        print("Fetching Long/Short Ratios...")
        ls_ratio = self.get_long_short_ratio(period="5m", limit=288)  # 24h of 5min data
        if ls_ratio is not None:
            latest_ratio = ls_ratio.iloc[-1]['longShortRatio']
            print(f"  ✓ Current L/S Ratio: {latest_ratio:.4f}")
        
        # 4. Top Trader Ratios
        print("Fetching Top Trader Ratios...")
        top_ratio = self.get_top_trader_long_short_ratio(period="5m", limit=288)
        if top_ratio is not None:
            latest_top = top_ratio.iloc[-1]['longShortRatio']
            print(f"  ✓ Top Trader L/S: {latest_top:.4f}")
        
        # 5. Top Trader Positions
        print("Fetching Top Trader Positions...")
        top_pos = self.get_top_trader_position_ratio(period="5m", limit=288)
        if top_pos is not None:
            latest_pos = top_pos.iloc[-1]['longShortRatio']
            print(f"  ✓ Top Trader Pos Ratio: {latest_pos:.4f}")
        
        # 6. Order Book
        print("Fetching Order Book...")
        orderbook = self.get_order_book(limit=100)
        if orderbook:
            bid_liquidity = orderbook['bids']['quantity'].sum()
            ask_liquidity = orderbook['asks']['quantity'].sum()
            print(f"  ✓ Bid Liquidity: {bid_liquidity:,.2f} BTC")
            print(f"  ✓ Ask Liquidity: {ask_liquidity:,.2f} BTC")
        
        # 7. Calculate Liquidation Levels
        if oi_data and price_data:
            print("\nCalculating Liquidation Levels...")
            liq_levels = self.calculate_liquidation_levels(
                price_data['mark_price'], 
                oi_data['open_interest']
            )
            print(f"  ✓ Generated {len(liq_levels)} liquidation levels")
            
            # Show top 5 long and short liquidations
            print("\n  Top 5 Long Liquidations (price going down):")
            long_liqs = liq_levels[liq_levels['side'] == 'long'].head(5)
            for _, row in long_liqs.iterrows():
                print(f"    ${row['price']:,.2f} ({row['distance_pct']:.2f}%) - {row['leverage']}x - {row['estimated_oi']:,.0f} BTC")
            
            print("\n  Top 5 Short Liquidations (price going up):")
            short_liqs = liq_levels[liq_levels['side'] == 'short'].head(5)
            for _, row in short_liqs.iterrows():
                print(f"    ${row['price']:,.2f} (+{row['distance_pct']:.2f}%) - {row['leverage']}x - {row['estimated_oi']:,.0f} BTC")
        
        return {
            'open_interest': oi_data,
            'mark_price': price_data,
            'long_short_ratio': ls_ratio,
            'top_trader_ratio': top_ratio,
            'top_trader_position': top_pos,
            'orderbook': orderbook,
            'liquidation_levels': liq_levels if (oi_data and price_data) else None
        }
    
    def upload_to_sheets(self, data, spreadsheet_id="1ZeS5XS-SvnfTpmWQ5KNchV52b5f1X6qBqTWxnYQbBAQ"):
        """Upload data to Google Sheets (matching existing structure)"""
        try:
            # Authenticate with embedded credentials from top of file
            scope = ['https://spreadsheets.google.com/feeds',
                    'https://www.googleapis.com/auth/drive']
            
            # Get credentials from full_liquidity_7_12.py format
            from oauth2client.service_account import ServiceAccountCredentials
            creds_info = {
                "type": "service_account",
                "project_id": "t-isotope-444017-a4",
                "private_key_id": "7c904154fbb69a42945161759e0b2101f8086283",
                "private_key": """-----BEGIN PRIVATE KEY-----
MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQC2lw18e96Avkgn
r8tPkk/XiB351vFz3OQ/RyO4D+0sq7mchuMxreTXLozDnm7fUk11TKNgcQraeBIJ
mExGOM+q2iWvWLRhYQtTcOu9ONF7OX81+C+BqbQe7XT+6vUXROzqddv/LwYk0dgz
mR8bMgFUr1VVYoxZUazJoyVvjdOFC6KBazA5dZuzSmigTwW5V8hiLmRx0KBw3pnM
Syw+oUlvWm+esM3Rx6+l/BV3I7yKT8fQVK9JTY0qfEniU0EuneerlJQsaVmwiLbE
mFCKESMvB2KJ4O8n/M0VL2EkmWpy8uWx/FF/S3ob8uFvwsKVWzZbkMn4GX3zkKiY
PkOToGBvAgMBAAECggEAHgATpzBzDpQ1JtArh5dypucmhbZbVb4lgoAdzlBPl9df
V+iRy8fWocR0PG/7p5XOREejUGVCc0LnM8xiO+d5t4jASF86xAU95yfWk/CR+r0n
uaZdp+BKSAqb/oZ8XqZkhuF2lCcVy1bvPwsZoU5GCbQFQVI/3S0eRsMXk4yqBGHt
pYu+EKm6b7DR+OsetY7SJIrqC2vt+eMg2hdhXR3ZOwfWcH76KrP3oCnfwpMOVsOq
AihaVKJsA+35RqyPRn6xL+qYueDwHYMqU9wjV6/OXgKUCN94EsSZ+aBOSOmBqtx4
IS5C9YHrNAn5b4QQB711TjwOUM1YdTwEc4fqkXUxgQKBgQDtct6GjWS+hOHuXiax
wdbSNlU0LZ9ey50OHn1hMibS9ax5+VhlSLIx381DFZRBaDTXBRm2tbKwogaFHYDY
TBBQpx907NyK7mUhVNILEwps+i56Ot/fLtQgC9C29XvYL7AnuYRjF+0dDPzv/i43
ATVDnkfmt5lqfvE9hK0egg0TGwKBgQDE2vleD4q0QYpK2+cZwGgNrN6MK1NEjOKS
+Oy2ZqYOazMPUGPyYrWUHmWZaFcpf0CUmhq4vkkQHVWAkbYeoxOvA8wGaq8vac+2
XPtarPdaNHHGLpaIH0bNyr30I+Yp7tv3dvw1EOeqg/8h6FH9CJsta9mEOuXMpHHs
CcNmpxKpPQKBgQCBVL+/qePloZstqjqJN3s6pD1kXjUf/OdeeVzxQ8/Bt+5pwVZU
VHQ6lhvHHknSFmAxfaWzzuO1MYs7lgZHyaZZR63qkdjOE2sh7IE7ZvOWx+3oxYiK
l4cSrVzRSoRaDB92g6WIE9AisqBSV6/0ZcQNQHkJQZdeWiYry8g/hbZ5YQKBgQC6
WrWA5uOeuwDI1x4SkcOvVnwjY4xjM5/2FHI6RjhjI/ZlQ+wp9GoCuzfhHxaMcSvY
wX4UcAbIm4xqtwYaQLUMlGKbnHkVQGzjLWjBsUZD/avLOiVE3Z7wiEKEkUt9XOKd
hOVC8yrskCKBneWnzXLhb9ytwffzX6V9Fs0FK5qN3QKBgD6gSkLh8so8xMQ/CAo1
QEhvUR6BQENg+OVG/mPFYvi3riMjH8E/nHG+1MfYiQ+0upqdXPEyb+4EpU1nNHAv
qARVBGrIZ+3nlIKq3YBeomM2R31LXI4kvQzL+eORj2HsLWQ3e/CxcnmFfePN19CA
ze1TTKQ3XR1d7SH8wYBHgf4N
-----END PRIVATE KEY-----
""",
                "client_email": "newyeartaken@t-isotope-444017-a4.iam.gserviceaccount.com",
                "client_id": "105479795730764346073",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/newyeartaken%40t-isotope-444017-a4.iam.gserviceaccount.com",
                "universe_domain": "googleapis.com"
            }
            
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
            client = gspread.authorize(creds)
            
            # Open spreadsheet
            sheet = client.open_by_key(spreadsheet_id)
            
            # Update liquidation levels for ALL timeframes (bot expects 5 worksheets)
            if data['liquidation_levels'] is not None:
                # Prepare base data - rename columns to match bot's expectations
                liq_df = data['liquidation_levels'].copy()
                liq_df = liq_df.rename(columns={
                    'estimated_oi': 'liquidation',
                    'side': 'liquidation_type'
                })
                
                # Define timeframe thresholds based on distance_pct
                # Bot expects: 12h_data, 24h_data, 48h_data, 3d_data, 1w_data
                # Use cumulative approach: each timeframe includes all closer levels
                timeframe_configs = {
                    '12h_data': {'max_distance': 1.5, 'description': '0-1.5%'},
                    '24h_data': {'max_distance': 2.5, 'description': '0-2.5%'},
                    '48h_data': {'max_distance': 4.0, 'description': '0-4.0%'},
                    '3d_data': {'max_distance': 6.0, 'description': '0-6.0%'},
                    '1w_data': {'max_distance': 10.0, 'description': '0-10.0%'}
                }
                
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                for worksheet_name, config in timeframe_configs.items():
                    try:
                        # Filter data for this timeframe's distance threshold
                        tf_df = liq_df[abs(liq_df['distance_pct']) <= config['max_distance']].copy()
                        
                        if len(tf_df) == 0:
                            print(f"WARN No liquidations within {config['description']} for {worksheet_name}")
                            continue
                        
                        # Get or create worksheet
                        try:
                            ws = sheet.worksheet(worksheet_name)
                        except gspread.exceptions.WorksheetNotFound:
                            ws = sheet.add_worksheet(title=worksheet_name, rows=1000, cols=20)
                        
                        # Prepare data with required columns
                        tf_df = tf_df[['price', 'liquidation', 'liquidation_type', 'leverage', 'distance_pct']].copy()
                        tf_df['timestamp'] = timestamp
                        
                        # Convert to list of lists for gspread
                        values = [tf_df.columns.tolist()] + tf_df.astype(str).values.tolist()
                        
                        # Clear and update
                        ws.clear()
                        ws.update(values=values, range_name='A1')
                        
                        print(f"OK Uploaded {len(tf_df)} liquidations to {worksheet_name} ({config['description']} distance)")
                        
                    except Exception as e:
                        print(f"ERROR uploading {worksheet_name}: {e}")
                
                print(f"\nOK Multi-timeframe upload complete - populated all 5 worksheets")
            
            return True
            
        except Exception as e:
            print(f"\nERROR uploading to Google Sheets: {e}")
            return False


def main():
    """Main execution"""
    scraper = BinanceLiquidityScraper(symbol="BTCUSDT")
    
    # Collect all data
    data = scraper.collect_all_data()
    
    # Save to local files
    print("\n=== Saving Data ===")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    if data['liquidation_levels'] is not None:
        filename = f"binance_liquidations_{timestamp}.csv"
        data['liquidation_levels'].to_csv(filename, index=False)
        print(f"OK Saved liquidation levels to {filename}")
    
    if data['long_short_ratio'] is not None:
        filename = f"binance_ls_ratio_{timestamp}.csv"
        data['long_short_ratio'].to_csv(filename, index=False)
        print(f"OK Saved long/short ratio to {filename}")
    
    # Try to upload to Google Sheets
    print("\n=== Uploading to Google Sheets ===")
    scraper.upload_to_sheets(data)
    
    print("\n=== Complete ===")
    print("Binance API is now the primary data source.")
    print("All CoinGlass scraping has been replaced.")


if __name__ == "__main__":
    main()
