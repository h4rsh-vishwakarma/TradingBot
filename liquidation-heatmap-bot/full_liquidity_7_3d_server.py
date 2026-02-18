Credentials_File={
    "type": "service_account",
    "project_id": "t-isotope-444017-a4",
    "private_key_id": "7c904154fbb69a42945161759e0b2101f8086283",
    "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQC2lw18e96Avkgn\nr8tPkk/XiB351vFz3OQ/RyO4D+0sq7mchuMxreTXLozDnm7fUk11TKNgcQraeBIJ\nmExGOM+q2iWvWLRhYQtTcOu9ONF7OX81+C+BqbQe7XT+6vUXROzqddv/LwYk0dgz\nmR8bMgFUr1VVYoxZUazJoyVvjdOFC6KBazA5dZuzSmigTwW5V8hiLmRx0KBw3pnM\nSyw+oUlvWm+esM3Rx6+l/BV3I7yKT8fQVK9JTY0qfEniU0EuneerlJQsaVmwiLbE\nmFCKESMvB2KJ4O8n/M0VL2EkmWpy8uWx/FF/S3ob8uFvwsKVWzZbkMn4GX3zkKiY\nPkOToGBvAgMBAAECggEAHgATpzBzDpQ1JtArh5dypucmhbZbVb4lgoAdzlBPl9df\nV+iRy8fWocR0PG/7p5XOREejUGVCc0LnM8xiO+d5t4jASF86xAU95yfWk/CR+r0n\nuaZdp+BKSAqb/oZ8XqZkhuF2lCcVy1bvPwsZoU5GCbQFQVI/3S0eRsMXk4yqBGHt\npYu+EKm6b7DR+OsetY7SJIrqC2vt+eMg2hdhXR3ZOwfWcH76KrP3oCnfwpMOVsOq\nAihaVKJsA+35RqyPRn6xL+qYueDwHYMqU9wjV6/OXgKUCN94EsSZ+aBOSOmBqtx4\nIS5C9YHrNAn5b4QQB711TjwOUM1YdTwEc4fqkXUxgQKBgQDtct6GjWS+hOHuXiax\nwdbSNlU0LZ9ey50OHn1hMibS9ax5+VhlSLIx381DFZRBaDTXBRm2tbKwogaFHYDY\nTBBQpx907NyK7mUhVNILEwps+i56Ot/fLtQgC9C29XvYL7AnuYRjF+0dDPzv/i43\nATVDnkfmt5lqfvE9hK0egg0TGwKBgQDE2vleD4q0QYpK2+cZwGgNrN6MK1NEjOKS\n+Oy2ZqYOazMPUGPyYrWUHmWZaFcpf0CUmhq4vkkQHVWAkbYeoxOvA8wGaq8vac+2\nXPtarPdaNHHGLpaIH0bNyr30I+Yp7tv3dvw1EOeqg/8h6FH9CJsta9mEOuXMpHHs\nCcNmpxKpPQKBgQCBVL+/qePloZstqjqJN3s6pD1kXjUf/OdeeVzxQ8/Bt+5pwVZU\nVHQ6lhvHHknSFmAxfaWzzuO1MYs7lgZHyaZZR63qkdjOE2sh7IE7ZvOWx+3oxYiK\nl4cSrVzRSoRaDB92g6WIE9AisqBSV6/0ZcQNQHkJQZdeWiYry8g/hbZ5YQKBgQC6\nWrWA5uOeuwDI1x4SkcOvVnwjY4xjM5/2FHI6RjhjI/ZlQ+wp9GoCuzfhHxaMcSvY\nwX4UcAbIm4xqtwYaQLUMlGKbnHkVQGzjLWjBsUZD/avLOiVE3Z7wiEKEkUt9XOKd\nhOVC8yrskCKBneWnzXLhb9ytwffzX6V9Fs0FK5qN3QKBgD6gSkLh8so8xMQ/CAo1\nQEhvUR6BQENg+OVG/mPFYvi3riMjH8E/nHG+1MfYiQ+0upqdXPEyb+4EpU1nNHAv\nqARVBGrIZ+3nlIKq3YBeomM2R31LXI4kvQzL+eORj2HsLWQ3e/CxcnmFfePN19CA\nze1TTKQ3XR1d7SH8wYBHgf4N\n-----END PRIVATE KEY-----\n",
    "client_email": "newyeartaken@t-isotope-444017-a4.iam.gserviceaccount.com",
    "client_id": "105479795730764346073",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/newyeartaken%40t-isotope-444017-a4.iam.gserviceaccount.com",
    "universe_domain": "googleapis.com"
}
import os
import time
import threading
import logging
import schedule
import numpy as np
import base64
from datetime import datetime
from io import BytesIO
from logging.handlers import RotatingFileHandler

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from PIL import Image
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from google.oauth2.service_account import Credentials as GoogleCredentials
import json

from datetime import datetime
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except ImportError:
    from pytz import timezone as ZoneInfo

# Configuration Constants
LOG_FILE = 'liquidity_scraper_12h.log'
SHEET_ID = "1ZeS5XS-SvnfTpmWQ5KNchV52b5f1X6qBqTWxnYQbBAQ"
BASE_URL = "https://www.coinglass.com/pro/futures/LiquidationHeatMap"

TIME_PERIODS = {
    "12h": {"sheet_name": "12h_data", "interval_minutes": 5, "dropdown_text": "12 hour"},
    "24h": {"sheet_name": "24h_data", "interval_minutes": 5, "dropdown_text": "24 hour"},
    "48h": {"sheet_name": "48h_data", "interval_minutes": 15, "dropdown_text": "48 hour"},
    "3d": {"sheet_name": "3d_data", "interval_minutes": 30, "dropdown_text": "3 day"},
    "1w": {"sheet_name": "1w_data", "interval_minutes": 60, "dropdown_text": "1 week"}
}

# Configure logging
os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(
            filename=f'logs/{LOG_FILE}',
            maxBytes=5*102*1024,
            backupCount=3
        ),
        logging.StreamHandler()
    ]
)

# Global driver manager to avoid multiple installations
driver_manager_lock = threading.Lock()
driver_path = None

# Global Google Sheets client
sheets_client = None
sheets_lock = threading.Lock()

def get_driver_path():
    """Thread-safe driver path initialization"""
    global driver_path
    with driver_manager_lock:
        if driver_path is None:
            cache_dir = os.path.expanduser('~/.wdm')
            os.makedirs(cache_dir, exist_ok=True)
            logging.info("Installing ChromeDriver...")
            driver_path = ChromeDriverManager().install()
            logging.info(f"ChromeDriver installed at: {driver_path}")
    return driver_path

def get_sheets_client():
    """Thread-safe Google Sheets client initialization"""
    global sheets_client
    with sheets_lock:
        if sheets_client is None:
            try:
                logging.info("Initializing Google Sheets client...")
                # Using the newer google-auth library
                scopes = [
                    "https://spreadsheets.google.com/feeds",
                    "https://www.googleapis.com/auth/drive"
                ]
                
                # Convert the dictionary to JSON string and back to handle the private key properly
                creds_dict = Credentials_File.copy()
                # Ensure private key has proper newlines
                if isinstance(creds_dict['private_key'], str):
                    creds_dict['private_key'] = creds_dict['private_key'].replace('\\n', '\n')
                
                credentials = GoogleCredentials.from_service_account_info(
                    creds_dict, 
                    scopes=scopes
                )
                
                sheets_client = gspread.authorize(credentials)
                logging.info("Google Sheets client initialized successfully")
                
            except Exception as e:
                logging.error(f"Failed to initialize Google Sheets client: {str(e)}", exc_info=True)
                raise
    return sheets_client

def setup_driver():
    """Setup Chrome driver with minimal stable options for both Windows and Linux"""
    chrome_options = Options()
    
    # Minimal essential options only - proven to work
    chrome_options.add_argument('--headless=new')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    
    # Disable automation detection
    chrome_options.add_experimental_option('excludeSwitches', ['enable-automation'])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    # Get thread-safe driver path
    service = ChromeService(get_driver_path())
    
    # Add service arguments for stability (Windows only)
    if os.name == "nt":
        try:
            service.creation_flags = 0x08000000  # CREATE_NO_WINDOW flag for Windows
        except Exception:
            pass  # Ignore if unsupported
    
    try:
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.set_page_load_timeout(180)  # Increased to 3 minutes
        driver.set_script_timeout(60)  # Increased to 1 minute
        
        # Test if driver is working
        driver.execute_script("return navigator.userAgent;")
        
        return driver
    except Exception as e:
        logging.error(f"Failed to create Chrome driver: {str(e)}")
        raise


class TooltipIsVisible:
    """Enhanced tooltip visibility checker with multiple criteria"""
    
    def __init__(self, locator):
        self.locator = locator
    
    def __call__(self, driver):
        try:
            elements = driver.find_elements(*self.locator)
            if not elements:
                return False
            
            # Check multiple elements if present
            for element in elements:
                if (element.is_displayed() and 
                    element.size['height'] > 0 and 
                    element.size['width'] > 0):
                    
                    # Additional checks for tooltip content
                    text_content = element.text.strip()
                    if text_content and len(text_content) > 10:  # Ensure meaningful content
                        return element
            
            return False
            
        except Exception:
            return False

def parse_timestamp(timestamp_str):
    """Parses timestamp from format like '21 May 2025, 10:45' (IST) and converts to UTC."""
    try:
        dt = datetime.strptime(timestamp_str, "%d %b %Y, %H:%M")
        # Attach IST timezone
        try:
            ist = ZoneInfo("Asia/Kolkata")
        except Exception:
            from pytz import timezone
            ist = timezone("Asia/Kolkata")
        dt_ist = dt.replace(tzinfo=ist)
        dt_utc = dt_ist.astimezone(ZoneInfo("UTC"))
        return dt_utc.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        logging.warning(f"Could not parse timestamp: {timestamp_str}")
        return timestamp_str

def is_liquidity_color(pixel):
    """Check if the color indicates any level of liquidity data (broader detection)."""
    r, g, b = pixel[:3]
    
    # Detect various liquidity colors:
    # - High liquidity: Yellow/Green (existing logic)
    # - Medium liquidity: Orange/Red tones
    # - Low liquidity: Blue/Purple tones
    # - Exclude pure black/white/gray (background)
    
    # High liquidity (yellow/green)
    if (r >= 150 and g >= 150 and b <= 100) or (r >= 200 and g >= 200 and b <= 50):
        return True
    
    # Medium liquidity (orange/red)
    if (r >= 200 and g >= 100 and b <= 100) or (r >= 150 and 50 <= g <= 150 and b <= 100):
        return True
    
    # Low liquidity (blue/purple)
    if (b >= 100 and r <= 150 and g <= 150):
        return True
    
    # Additional color variations for liquidity data
    if (r >= 100 or g >= 100 or b >= 100) and not (abs(r-g) < 20 and abs(g-b) < 20 and abs(r-b) < 20):
        return True
    
    return False

def get_color_intensity(pixel):
    """Calculate intensity (0-255) of a pixel."""
    return sum(pixel[:3]) / 3  # Average RGB

def select_time_period(driver, period_text):
    """Select specific time period from dropdown"""
    if period_text == "24 hour":
        logging.info("Default period is 24h, no need to change")
        return True
        
    try:
        logging.info(f"Selecting time period: {period_text}")
        time.sleep(2)
        dropdown_xpath = '/html/body/div/div[2]/div/div[2]/div[2]/div[3]/div[4]/div[1]/div/div/div[2]/button'
        WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.XPATH, dropdown_xpath))
        ).click()
        time.sleep(1)
        
        period_to_li = {
            "12 hour": 1, "24 hour": 2, "48 hour": 3, 
            "3 day": 4, "1 week": 5
        }
        
        li_number = period_to_li.get(period_text)
        if not li_number:
            logging.error(f"Unknown period: {period_text}")
            return False
            
        option_xpath = f'/html/body/ul[2]/li[{li_number}]'
        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, option_xpath))
        ).click()
        time.sleep(3)  # Increased wait time
        logging.info(f"Successfully selected period: {period_text}")
        return True
        
    except Exception as e:
        logging.error(f"Failed to select {period_text}: {str(e)}", exc_info=True)
        return False

def find_and_analyze_liquidity(period_key, min_liquidity_threshold=0.5):
    """Enhanced liquidity analysis with improved tooltip handling"""
    driver = None
    try:
        driver = setup_driver()
        logging.info(f"[{period_key}] Driver setup complete")
        
        driver.get(BASE_URL)
        logging.info(f"[{period_key}] Page loaded successfully")
        
        # Increased page load wait time
        WebDriverWait(driver, 60).until(  # Increased to 60 seconds
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        time.sleep(15)  # Increased wait for page to fully render
        
        # Click Symbol button with retry logic
        button_xpath = '/html/body/div/div[2]/div/div/div[2]/div[3]/div[3]/div/button[2]'
        for attempt in range(3):
            try:
                WebDriverWait(driver, 45).until(  # Increased to 45 seconds
                    EC.element_to_be_clickable((By.XPATH, button_xpath))
                ).click()
                time.sleep(4)  # Increased wait time
                logging.info(f"[{period_key}] Symbol button clicked (attempt {attempt + 1})")
                break
            except Exception as e:
                if attempt == 2:
                    raise e
                time.sleep(3)
        
        # Select time period
        period_config = TIME_PERIODS[period_key]
        if not select_time_period(driver, period_config["dropdown_text"]):
            logging.error(f"[{period_key}] Failed to select time period")
            return None
        
        # Wait for chart to fully load after time period change
        time.sleep(6)  # Additional wait for chart re-render
        
        # Extract heatmap data with enhanced canvas detection
        canvas = None
        for attempt in range(3):
            try:
                canvas = WebDriverWait(driver, 60).until(  # Increased to 60 seconds
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".echarts-for-react canvas"))
                )
                # Verify canvas is fully loaded
                canvas_size = driver.execute_script("return [arguments[0].width, arguments[0].height];", canvas)
                if canvas_size[0] > 0 and canvas_size[1] > 0:
                    break
                time.sleep(3)
            except Exception as e:
                if attempt == 2:
                    raise e
                time.sleep(3)
        
        time.sleep(4)  # Increased canvas wait time
        logging.info(f"[{period_key}] Canvas found and verified")
        
        # Extract image with retry
        data_url = None
        for attempt in range(3):
            try:
                data_url = driver.execute_script("return arguments[0].toDataURL('image/png');", canvas)
                if data_url and data_url.startswith('data:image'):
                    break
                time.sleep(2)
            except Exception as e:
                if attempt == 2:
                    raise e
                time.sleep(2)
        
        image = Image.open(BytesIO(base64.b64decode(data_url.split(',')[1])))
        logging.info(f"[{period_key}] Image extracted, size: {image.size}")
        
        # IMPROVED COORDINATE ANALYSIS - Expanded area and better point selection
        width, height = image.size
        all_points = []
        
        # Scan the entire width for complete coverage
        right_corner_start = 0  
        logging.info(f"[{period_key}] Analyzing expanded right area from x={right_corner_start} to x={width}")
        
        # Enhanced liquidity point detection
        for x in range(right_corner_start, width):
            for y in range(height):
                pixel = image.getpixel((x, y))
                if is_liquidity_color(pixel):
                    all_points.append((x, y))
        
        logging.info(f"[{period_key}] Found {len(all_points)} liquidity points in expanded right area")
        
        if not all_points:
            logging.warning(f"[{period_key}] No liquidity points found")
            return None
        
        # IMPROVED POINT GROUPING AND SELECTION
        from collections import defaultdict
        points_by_x = defaultdict(list)
        for x, y in all_points:
            points_by_x[x].append(y)
        
        # Better point selection with reduced spacing for more coverage
        significant_points = []
        for x_coord in sorted(points_by_x.keys(), reverse=True):
            y_coords = sorted(points_by_x[x_coord])
            
            prev_y = -1
            min_spacing = 1  # Reduced spacing: min 3px or 1.25% of height
            
            for y in y_coords:
                if prev_y == -1 or y - prev_y >= min_spacing:
                    significant_points.append((x_coord, y))
                    prev_y = y
            
            # Increased point limit for better data coverage
            if len(significant_points) >= 200:  # Increased from 100 to 200
                break
        
        # Sort by Y-coordinate (price order) and limit to manageable number
        significant_points = sorted(significant_points, key=lambda p: p[1])  # Keep all detected points
        
        logging.info(f"[{period_key}] Selected {len(significant_points)} points for tooltip extraction")
        logging.info(f"[{period_key}] X-coordinates range: {min(x for x, y in significant_points)} to {max(x for x, y in significant_points)}")
        logging.info(f"[{period_key}] Y-coordinates range: {min(y for x, y in significant_points)} to {max(y for x, y in significant_points)}")
        
        # ENHANCED TOOLTIP EXTRACTION WITH ROBUST ERROR HANDLING
        tooltip_data = []
        TOOLTIP_LOCATOR = (By.CSS_SELECTOR, "div[class*='cg-toolti-box']")
        
        successful_extractions = 0
        consecutive_failures = 0
        max_consecutive_failures = 10  # Stop if too many consecutive failures
        
        for i, (x, y) in enumerate(significant_points):
            try:
                # Log progress more frequently
                if i % 5 == 0:
                    success_rate = (successful_extractions / max(1, i)) * 100 if i > 0 else 0
                    logging.info(f"[{period_key}] Processing point {i+1}/{len(significant_points)} "
                               f"({(i/len(significant_points)*100):.1f}%) - Success rate: {success_rate:.1f}%")
                
                # IMPROVED MOUSE HOVER with multiple attempts
                hover_success = False
                for hover_attempt in range(3):  # Try up to 3 times per point
                    try:
                        # Enhanced mouse movement with more precise positioning
                        driver.execute_script(f"""
                            var canvas = arguments[0];
                            var rect = canvas.getBoundingClientRect();
                            
                            // Multiple event types for better compatibility
                            var events = ['mousemove', 'mouseover', 'mouseenter'];
                            
                            events.forEach(function(eventType) {{
                                var event = new MouseEvent(eventType, {{
                                    clientX: rect.left + {x},
                                    clientY: rect.top + {y},
                                    bubbles: true,
                                    cancelable: true,
                                    view: window
                                }});
                                canvas.dispatchEvent(event);
                            }});
                        """, canvas)
                        
                        # Progressive wait times: 1.2s, 1.8s, 2.5s
                        wait_time = 1.2 + (hover_attempt * 0.6)
                        time.sleep(wait_time)
                        
                        # Check if tooltip appeared with increased timeout
                        tooltip = WebDriverWait(driver, 5).until(  # Increased from 2 to 5 seconds
                            TooltipIsVisible(TOOLTIP_LOCATOR)
                        )
                        hover_success = True
                        break
                        
                    except Exception as hover_e:
                        if hover_attempt == 2:  # Last attempt
                            logging.debug(f"[{period_key}] All hover attempts failed at ({x},{y}): {str(hover_e)}")
                        else:
                            time.sleep(0.5)  # Brief pause between hover attempts
                
                if not hover_success:
                    consecutive_failures += 1
                    if consecutive_failures >= max_consecutive_failures:
                        logging.warning(f"[{period_key}] Too many consecutive failures, stopping early")
                        break
                    continue
                
                # Reset consecutive failure counter on success
                consecutive_failures = 0
                
                # Enhanced tooltip parsing
                content = tooltip.text.split('\n')
                logging.debug(f"[{period_key}] Tooltip content at ({x},{y}): {content}")
                
                entry = {
                    'timestamp': None,
                    'price': None,
                    'liquidation': None,
                    'scrape_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    'period': period_key,
                    'x_coord': x,
                    'y_coord': y
                }
                
                # IMPROVED TOOLTIP PARSING with more flexible logic
                for j, line in enumerate(content):
                    line = line.strip()
                    if not line:
                        continue
                    
                    # Enhanced timestamp detection
                    if j == 0 and not entry['timestamp']:
                        if any(month in line for month in ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                                                          'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']):
                            entry['timestamp'] = parse_timestamp(line)
                    
                    # Enhanced price detection - look for various price indicators
                    elif (line in ["Price", "Close", "Current Price"] or "Price" in line) and j + 1 < len(content):
                        next_line = content[j + 1].strip()
                        if next_line and next_line.replace('.', '').replace(',', '').isdigit():
                            entry['price'] = next_line
                    
                    # Enhanced liquidation detection
                    elif ("Liquidation" in line or "Leverage" in line) and j + 1 < len(content):
                        next_line = content[j + 1].strip()
                        if next_line:
                            entry['liquidation'] = next_line
                
                # Accept entry if we have at least timestamp and one data field
                if entry['timestamp'] and (entry['price'] or entry['liquidation']):
                    tooltip_data.append(entry)
                    successful_extractions += 1
                    logging.debug(f"[{period_key}] Successfully parsed tooltip: "
                                f"Price={entry['price']}, Liquidation={entry['liquidation']}")
                else:
                    logging.warning(f"[{period_key}] Incomplete tooltip data at ({x},{y}): {content}")
                
            except Exception as e:
                consecutive_failures += 1
                logging.error(f"[{period_key}] Tooltip extraction failed at ({x},{y}): {str(e)}")
                
                if consecutive_failures >= max_consecutive_failures:
                    logging.warning(f"[{period_key}] Too many consecutive failures, stopping early")
                    break
                continue
        
        final_success_rate = (successful_extractions / len(significant_points)) * 100 if significant_points else 0
        logging.info(f"[{period_key}] Extraction completed: {successful_extractions}/{len(significant_points)} "
                    f"successful ({final_success_rate:.1f}% success rate)")
        logging.info(f"[{period_key}] Total liquidation entries extracted: {len(tooltip_data)}")
        
        return tooltip_data
        
    except Exception as e:
        logging.error(f"[{period_key}] Critical error in enhanced extraction: {str(e)}", exc_info=True)
        return None
    
    finally:
        if driver:
            try:
                driver.quit()
                logging.info(f"[{period_key}] Driver quit successfully")
            except Exception as e:
                logging.error(f"[{period_key}] Error quitting driver: {str(e)}")

def push_to_sheets(sheet_id, sheet_name, data):
    """Push data to Google Sheets with extensive logging"""
    if not data:
        logging.warning(f"No data to push to {sheet_name}")
        return False
        
    try:
        client = get_sheets_client()
        logging.info(f"Opening spreadsheet: {sheet_id}")
        spreadsheet = client.open_by_key(sheet_id)
        
        logging.info(f"Accessing worksheet: {sheet_name}")
        try:
            worksheet = spreadsheet.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            logging.info(f"Worksheet {sheet_name} not found, creating new one")
            worksheet = spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=10)
            # Add headers including coordinate information for debugging
            headers = ["Timestamp", "Price", "Liquidation", "Scrape Time", "Period", "X_Coord", "Y_Coord"]

            worksheet.append_row(headers)
            logging.info(f"Created new worksheet with headers: {headers}")
        
        # Prepare data for insertion
        rows_to_append = []
        for entry in data:
            row = [
                entry.get('timestamp', ''),
                entry.get('price', ''),
                entry.get('liquidation', ''),
                entry.get('scrape_time', ''),
                entry.get('period', ''),
                entry.get('x_coord', ''),  # Add coordinate data
                entry.get('y_coord', '')
            ]
            rows_to_append.append(row)

        
        logging.info(f"Appending {len(rows_to_append)} rows to {sheet_name}")
        
        # Append data
        worksheet.append_rows(rows_to_append)
        
        logging.info(f"Successfully appended {len(rows_to_append)} rows to {sheet_name}")
        
        # Get current row count for logging
        all_values = worksheet.get_all_values()
        logging.info(f"Total rows in {sheet_name} after append: {len(all_values)}")
        
        return True
        
    except Exception as e:
        logging.error(f"Error updating Google Sheets for {sheet_name}: {str(e)}", exc_info=True)
        return False

def scrape_and_save(period_key):
    """Scrape data for a specific period and save to sheets"""
    try:
        logging.info(f"[{period_key}] ====== STARTING SCRAPE ======")
        start_time = time.time()
        
        data = find_and_analyze_liquidity(period_key)
        
        if data:
            logging.info(f"[{period_key}] Data extraction completed, {len(data)} entries found")
            period_config = TIME_PERIODS[period_key]
            
            success = push_to_sheets(SHEET_ID, period_config["sheet_name"], data)
            if success:
                logging.info(f"[{period_key}] Data successfully saved to Google Sheets")
            else:
                logging.error(f"[{period_key}] Failed to save to Google Sheets")
        else:
            logging.warning(f"[{period_key}] No data found during scraping")
            
        end_time = time.time()
        logging.info(f"[{period_key}] ====== SCRAPE COMPLETED in {end_time - start_time:.2f} seconds ======")
        
    except Exception as e:
        logging.error(f"[{period_key}] Error in scrape_and_save: {str(e)}", exc_info=True)

def setup_scheduler():
    """Setup scheduled task **only** for 12h period."""
    logging.info("Setting up scheduler for 12h only...")
    # 12h interval is defined as 5 minutes in TIME_PERIODS
    schedule.every(5).minutes.do(scrape_and_save, "12h")
    logging.info("Scheduled 12h every 5 minutes")

def run_scheduler():
    """Run the scheduler in a loop"""
    logging.info("Starting scheduler loop...")
    while True:
        try:
            schedule.run_pending()
            next_run = schedule.next_run()
            if next_run:
                logging.info(f"Next scheduled run at: {next_run}")
            time.sleep(60)
        except Exception as e:
            logging.error(f"Scheduler error: {str(e)}", exc_info=True)
            time.sleep(60)

def run_initial_scrape():
    """Run initial scrape for all periods with staggered timing"""
    logging.info("===== STARTING INITIAL SCRAPE =====")
    
    # Don't run all threads simultaneously - stagger them
    for i, period_key in enumerate(TIME_PERIODS):
        logging.info(f"Scraping {period_key} ({i+1}/{len(TIME_PERIODS)})")
        scrape_and_save("12h")
        if i < len(TIME_PERIODS) - 1:  # Don't sleep after last period
            logging.info(f"Waiting 30 seconds before next scrape...")
            time.sleep(30)  # 30 seconds between scrapes
    
    logging.info("===== INITIAL SCRAPE COMPLETED =====")

if __name__ == "__main__":
    logging.info("===== SCRIPT STARTED =====")
    # Clear cached drivers
    try:
        import shutil
        cache_path = os.path.expanduser('~/.wdm')
        if os.path.exists(cache_path):
            shutil.rmtree(cache_path)
            logging.info("Cleared WebDriver cache")
    except Exception as e:
        logging.warning(f"Could not clear cache: {e}")

    # Initialize Google Sheets client
    try:
        get_sheets_client()
        logging.info("Google Sheets client initialized successfully")
    except Exception as e:
        logging.error(f"Failed to initialize Google Sheets client: {e}", exc_info=True)
        exit(1)

    # Run only 24h initial scrape and scheduler
    run_initial_scrape()
    setup_scheduler()
    try:
        run_scheduler()
    except KeyboardInterrupt:
        logging.info("Scraper stopped by user")
    except Exception as e:
        logging.error(f"Scheduler error: {str(e)}", exc_info=True)