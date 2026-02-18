#!/usr/bin/env python3
"""
CoinGlass Long/Short Ratio Scraper
Fetches LSR data from CoinGlass (PRIMARY SOURCE)
Replaces Binance API scraper - uses ONLY CoinGlass
"""
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
from datetime import datetime, timezone
import logging
import re
import sys

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class CoinGlassLSRScraper:
    def __init__(self, credentials_file='credentials.json', spreadsheet_key='1ysGcPSyyJrlX3Wo7C4s7TCkRVF-d9YlvG7LbZeNNQ8k'):
        """Initialize CoinGlass LSR scraper with Google Sheets connection"""
        self.credentials_file = credentials_file
        self.spreadsheet_key = spreadsheet_key
        self.lsr_url = "https://www.coinglass.com/LongShortRatio"
        self.driver = None
        self.worksheet = None
        
        # Authenticate with Google Sheets
        self._init_sheets()
    
    def _init_sheets(self):
        """Initialize Google Sheets connection"""
        try:
            scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
            creds = ServiceAccountCredentials.from_json_keyfile_name(self.credentials_file, scope)
            client = gspread.authorize(creds)
            spreadsheet = client.open_by_key(self.spreadsheet_key)
            self.worksheet = spreadsheet.worksheet('lsr')
            logger.info(f"Connected to Google Sheets: {spreadsheet.title} / lsr")
        except Exception as e:
            logger.error(f"Failed to connect to Google Sheets: {e}")
            raise
    
    def setup_driver(self):
        """Initialize headless Chrome browser"""
        try:
            logger.info("Starting Chrome browser for CoinGlass LSR scraping")
            
            options = uc.ChromeOptions()
            options.add_argument('--headless=new')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            options.add_argument('--window-size=1920,1080')
            options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
            
            self.driver = uc.Chrome(options=options, version_main=143)
            logger.info("Chrome browser started successfully")
        except Exception as e:
            logger.error(f"Failed to start Chrome: {e}")
            raise
    
    def fetch_lsr_from_coinglass(self):
        """Fetch Long/Short Ratio from CoinGlass"""
        driver_created = False
        try:
            if not self.driver:
                self.setup_driver()
                driver_created = True
            
            logger.info("Navigating to CoinGlass Long/Short Ratio page")
            self.driver.get(self.lsr_url)
            
            # Wait for page to load
            wait = WebDriverWait(self.driver, 15)
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            time.sleep(5)  # Additional wait for dynamic content
            
            # Get page source and extract LSR data
            page_text = self.driver.page_source
            
            lsr_data = {
                'timestamp': datetime.now(timezone.utc),
                'exchange': 'CoinGlass',
                'symbol': 'BTCUSDT',
                'long_ratio': None,
                'short_ratio': None,
                'long_short_ratio': None
            }
            
            # Multiple regex patterns to extract LSR data from CoinGlass
            # CoinGlass formats: "Long: 52.34%", "Short: 47.66%", or in JSON data
            patterns = [
                # JSON format
                (r'"long"[^}]*?["\']value["\']\s*:\s*["\']?(\d+\.?\d*)', r'"short"[^}]*?["\']value["\']\s*:\s*["\']?(\d+\.?\d*)'),
                # Text format with percentages
                (r'Long[:\s]+(\d+\.?\d+)%', r'Short[:\s]+(\d+\.?\d+)%'),
                # Alternative formats
                (r'long.*?(\d+\.?\d+)', r'short.*?(\d+\.?\d+)'),
            ]
            
            long_value = None
            short_value = None
            
            for long_pattern, short_pattern in patterns:
                if long_value is None:
                    long_match = re.search(long_pattern, page_text, re.IGNORECASE)
                    if long_match:
                        long_value = float(long_match.group(1))
                        # If value > 1, assume it's already a percentage (e.g., 52.34 means 52.34%)
                        if long_value > 1:
                            long_value = long_value / 100.0
                
                if short_value is None:
                    short_match = re.search(short_pattern, page_text, re.IGNORECASE)
                    if short_match:
                        short_value = float(short_match.group(1))
                        if short_value > 1:
                            short_value = short_value / 100.0
                
                if long_value and short_value:
                    break
            
            if long_value and short_value:
                # Normalize to ensure they sum to ~1.0
                total = long_value + short_value
                if abs(total - 1.0) > 0.1:  # If they don't sum to 1, normalize
                    long_value = long_value / total
                    short_value = short_value / total
                
                lsr_data['long_ratio'] = long_value
                lsr_data['short_ratio'] = short_value
                lsr_data['long_short_ratio'] = long_value / short_value if short_value > 0 else 0
                
                logger.info(f"✅ Fetched LSR from CoinGlass: ratio={lsr_data['long_short_ratio']:.4f}, long={long_value:.2%}, short={short_value:.2%}")
                return lsr_data
            else:
                logger.warning("Could not extract LSR values from CoinGlass page")
                return None
                
        except Exception as e:
            logger.error(f"Error fetching LSR from CoinGlass: {e}")
            # Clean up driver on error to prevent leaks
            if driver_created and self.driver:
                try:
                    self.driver.quit()
                    self.driver = None
                    logger.info("Closed browser due to error")
                except:
                    pass
            return None
    
    def append_to_sheet(self, data):
        """Append LSR data to Google Sheets"""
        try:
            row = [
                data['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
                data['exchange'],
                data['symbol'],
                f"{data['long_ratio']:.4f}",
                f"{data['short_ratio']:.4f}",
                f"{data['long_short_ratio']:.4f}",
                f"{data['long_ratio']*100:.2f}",
                f"{data['short_ratio']*100:.2f}",
                datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            ]
            
            self.worksheet.append_row(row, value_input_option='USER_ENTERED')
            logger.info(f"✅ Appended LSR data: ratio={data['long_short_ratio']:.4f}, long={data['long_ratio']*100:.2f}%, short={data['short_ratio']*100:.2f}%")
            return True
        except Exception as e:
            logger.error(f"Error appending to sheet: {e}")
            return False
    
    def run_once(self):
        """Fetch and store LSR data once"""
        try:
            logger.info("Fetching current LSR data from CoinGlass...")
            data = self.fetch_lsr_from_coinglass()
            
            if data and data['long_short_ratio']:
                success = self.append_to_sheet(data)
                if success:
                    logger.info("✅ LSR data updated successfully")
                    return True
            else:
                logger.warning("No LSR data fetched")
                return False
                
        except Exception as e:
            logger.error(f"Error in run_once: {e}")
            return False
        finally:
            # Always clean up driver after each run to prevent resource leaks
            if self.driver:
                try:
                    self.driver.quit()
                    self.driver = None
                    logger.info("Browser cleaned up after run")
                except:
                    pass
    
    def cleanup(self):
        """Clean up resources"""
        if self.driver:
            try:
                self.driver.quit()
                logger.info("Browser closed")
            except:
                pass

def main():
    """Main function for standalone execution"""
    import argparse
    parser = argparse.ArgumentParser(description='CoinGlass LSR Scraper')
    parser.add_argument('--once', action='store_true', help='Run once and exit')
    args = parser.parse_args()
    
    scraper = None
    try:
        scraper = CoinGlassLSRScraper()
        
        if args.once:
            scraper.run_once()
        else:
            # Continuous mode with 5-minute interval
            logger.info("Running in continuous mode (5-minute interval)")
            while True:
                scraper.run_once()
                logger.info("Waiting 5 minutes before next fetch...")
                time.sleep(300)  # 5 minutes
                
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
    finally:
        if scraper:
            scraper.cleanup()

if __name__ == "__main__":
    main()
