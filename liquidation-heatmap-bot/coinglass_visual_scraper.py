"""
CoinGlass Visual Scraper - Screenshot + Color Analysis
Extracts liquidation data by analyzing heatmap colors and positions
No OCR needed - uses computer vision to detect liquidation zones
"""

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from PIL import Image
import io
import time
import numpy as np
import pandas as pd
from datetime import datetime, timezone
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import cv2
import logging
import os

# Configure logging
logger = logging.getLogger(__name__)
if not logger.handlers:
    log_dir = os.path.join(os.getcwd(), 'logs')
    os.makedirs(log_dir, exist_ok=True)
    fh = logging.FileHandler(os.path.join(log_dir, 'coinglass_scraper.log'))
    fh.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    logger.setLevel(logging.INFO)

class CoinGlassVisualScraper:
    """Extract liquidation data from CoinGlass using visual heatmap analysis"""
    
    def __init__(self, emitter=None):
        self.url = "https://www.coinglass.com/pro/futures/LiquidationHeatMap"
        self.driver = None
        self.emitter = emitter
        self.run_id = f"scraper_{int(datetime.now(timezone.utc).timestamp())}"
        logger.info(f"CoinGlassVisualScraper initialized with run_id: {self.run_id}")
        
    def setup_driver(self, max_retries=3):
        """Initialize undetected Chrome with retry logic"""
        print("[INFO] Starting Chrome browser...")
        logger.info("Starting Chrome browser for scraping")
        
        options = uc.ChromeOptions()
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        # Enable GPU/WebGL for proper heatmap rendering
        options.add_argument('--ignore-gpu-blacklist')
        options.add_argument('--enable-webgl')
        options.add_argument('--enable-accelerated-2d-canvas')
        options.add_argument('--use-gl=egl')  # or 'desktop' on Windows
        options.add_argument('--disable-software-rasterizer')
        options.add_argument('--headless=new')
        # Larger window for full heatmap capture
        options.add_argument('--window-size=2560,1440')
        options.add_argument('--force-device-scale-factor=1')
        options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        # Add timeout and connection settings
        options.add_argument('--disable-extensions')
        options.add_argument('--disable-logging')
        options.add_argument('--log-level=3')
        options.page_load_strategy = 'eager'  # Don't wait for full page load
        
        # Retry logic for connection issues
        for attempt in range(max_retries):
            try:
                # Auto-detect chromedriver (works on both Windows and Linux)
                self.driver = uc.Chrome(
                    options=options,
                    version_main=143
                )
                # Set page load timeout
                self.driver.set_page_load_timeout(30)
                print("[OK] Chrome started with GPU/WebGL enabled")
                logger.info("Chrome browser started successfully with GPU/WebGL")
                return
            except Exception as e:
                logger.warning(f"Chrome setup attempt {attempt + 1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2)  # Wait before retry
                    continue
                else:
                    logger.error(f"Failed to start Chrome after {max_retries} attempts")
                    raise
        
    def extract_lsr_data(self):
        """Extract Long/Short Ratio data from CoinGlass LSR page"""
        try:
            print("[INFO] Extracting LSR data from CoinGlass LSR page...")
            logger.info("Navigating to CoinGlass LSR page")
            
            # Navigate to CoinGlass Long/Short Ratio page
            lsr_url = "https://www.coinglass.com/LongShortRatio"
            self.driver.get(lsr_url)
            time.sleep(5)  # Wait for page to load
            
            lsr_data = {
                'timestamp': datetime.now(timezone.utc),
                'exchange': 'CoinGlass',
                'symbol': 'BTCUSDT',
                'long_ratio': None,
                'short_ratio': None,
                'long_short_ratio': None
            }
            
            # Get page source and look for LSR data
            page_text = self.driver.page_source
            import re
            
            # Try multiple patterns to extract LSR data
            # Pattern 1: Look for percentage values in specific sections
            # CoinGlass shows: "Long 52.34%" and "Short 47.66%"
            long_patterns = [
                r'"long"[^}]*?"value":\s*"?(\d+\.?\d*)',
                r'Long.*?(\d+\.?\d+)%',
                r'long.*?(\d+\.?\d+)',
            ]
            short_patterns = [
                r'"short"[^}]*?"value":\s*"?(\d+\.?\d*)',
                r'Short.*?(\d+\.?\d+)%',
                r'short.*?(\d+\.?\d+)',
            ]
            
            long_value = None
            short_value = None
            
            # Try to find long percentage
            for pattern in long_patterns:
                match = re.search(pattern, page_text, re.IGNORECASE)
                if match:
                    long_value = float(match.group(1))
                    if long_value > 1:  # If it's a percentage > 100%, divide by 100
                        long_value = long_value / 100.0
                    break
            
            # Try to find short percentage
            for pattern in short_patterns:
                match = re.search(pattern, page_text, re.IGNORECASE)
                if match:
                    short_value = float(match.group(1))
                    if short_value > 1:
                        short_value = short_value / 100.0
                    break
            
            if long_value and short_value:
                lsr_data['long_ratio'] = long_value
                lsr_data['short_ratio'] = short_value
                lsr_data['long_short_ratio'] = long_value / short_value if short_value > 0 else 0
                print(f"[OK] Extracted LSR from CoinGlass: Long={lsr_data['long_ratio']:.2%}, Short={lsr_data['short_ratio']:.2%}, Ratio={lsr_data['long_short_ratio']:.4f}")
                logger.info(f"LSR extracted from CoinGlass: {lsr_data['long_short_ratio']:.4f}")
                return lsr_data
            
            print("[WARN] Could not extract LSR from CoinGlass LSR page")
            logger.warning("LSR extraction failed - data not found on page")
            return None
            
        except Exception as e:
            print(f"[ERROR] LSR extraction failed: {e}")
            logger.error(f"LSR extraction error: {e}")
            return None
        finally:
            # Navigate back to liquidation heatmap page
            try:
                self.driver.get(self.url)
                time.sleep(3)
            except:
                pass
    
    def push_lsr_to_sheet(self, lsr_data, spreadsheet_key='1ysGcPSyyJrlX3Wo7C4s7TCkRVF-d9YlvG7LbZeNNQ8k'):
        """Push LSR data to Google Sheets"""
        if not lsr_data or lsr_data['long_short_ratio'] is None:
            return False
            
        try:
            print("[INFO] Pushing LSR data to Google Sheets...")
            scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
            creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
            client = gspread.authorize(creds)
            sheet = client.open_by_key(spreadsheet_key)
            worksheet = sheet.worksheet('lsr')
            
            row = [
                lsr_data['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
                lsr_data['exchange'],
                lsr_data['symbol'],
                f"{lsr_data['long_ratio']:.4f}",
                f"{lsr_data['short_ratio']:.4f}",
                f"{lsr_data['long_short_ratio']:.4f}",
                f"{lsr_data['long_ratio']*100:.2f}",
                f"{lsr_data['short_ratio']*100:.2f}",
                datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            ]
            
            worksheet.append_row(row, value_input_option='USER_ENTERED')
            print(f"[OK] LSR data pushed to sheet: {lsr_data['long_short_ratio']:.4f}")
            logger.info(f"LSR data pushed: {lsr_data['long_short_ratio']:.4f}")
            return True
            
        except Exception as e:
            print(f"[ERROR] Failed to push LSR to sheet: {e}")
            logger.error(f"LSR sheet push error: {e}")
            return False
    
    def load_page(self, max_retries=2):
        """Load CoinGlass page with retry logic"""
        for attempt in range(max_retries):
            try:
                print(f"[INFO] Loading {self.url}... (attempt {attempt + 1}/{max_retries})")
                logger.info(f"Loading CoinGlass page: {self.url} (attempt {attempt + 1})")
                
                self.driver.get(self.url)
                
                # Initial wait for page structure
                print("[INFO] Waiting for initial page load (10 seconds)...")
                time.sleep(10)
                
                # Trigger heatmap rendering with interactions
                try:
                    print("[INFO] Triggering heatmap rendering...")
                    # Scroll to load lazy content
                    self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
                    time.sleep(2)
                    self.driver.execute_script("window.scrollTo(0, 0);")
                    time.sleep(2)
                    
                    # Click timeframe buttons to ensure all data loads
                    try:
                        # Try clicking different timeframe buttons to trigger full render
                        buttons = self.driver.find_elements(By.CSS_SELECTOR, "button, [role='button']")
                        for btn in buttons[:5]:  # Try first 5 buttons
                            try:
                                if btn.is_displayed():
                                    btn.click()
                                    time.sleep(0.5)
                            except:
                                pass
                    except:
                        pass
                        
                    print("[INFO] Forcing canvas/SVG render...")
                    # Force re-render of canvas/SVG elements
                    self.driver.execute_script("""
                        document.querySelectorAll('canvas').forEach(c => {
                            c.style.display = 'none';
                            c.offsetHeight; // trigger reflow
                            c.style.display = 'block';
                        });
                    """)
                    time.sleep(2)
                except Exception as e:
                    print(f"[WARN] Interaction triggers failed: {e}")
                
                # Final wait for heatmap to fully render
                print("[INFO] Final wait for heatmap rendering (15 seconds)...")
                for i in range(15):
                    time.sleep(1)
                    if (i + 1) % 5 == 0:
                        print(f"       ... {i + 1}/15 seconds")
                
                # Try canvas capture first (better for WebGL/canvas heatmaps)
                screenshot_path = f"coinglass_full_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                print("[INFO] Attempting canvas capture...")
                logger.info("Attempting canvas.toDataURL capture")
                
                canvas_png = self._capture_canvas_as_png()
                if canvas_png:
                    # Save canvas PNG
                    with open(screenshot_path, 'wb') as f:
                        f.write(canvas_png)
                    print(f"[OK] Canvas captured: {screenshot_path} ({len(canvas_png)} bytes)")
                    logger.info(f"Canvas captured: {len(canvas_png)} bytes")
                    return screenshot_path
                else:
                    print("[WARN] Canvas capture failed, falling back to screenshot")
                    logger.warning("Canvas capture failed, using fallback screenshot")
                
                # Fallback: traditional screenshot
                print("[INFO] Capturing full page screenshot...")
                logger.info("Capturing page screenshot")
                self.driver.save_screenshot(screenshot_path)
                print(f"[OK] Screenshot saved: {screenshot_path}")
                logger.info(f"Screenshot saved: {screenshot_path}")
                
                # Verify file exists and has content
                if os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 10000:
                    print(f"[OK] Screenshot verified ({os.path.getsize(screenshot_path)} bytes)")
                    logger.info(f"Screenshot verified: {os.path.getsize(screenshot_path)} bytes")
                    
                    # Cleanup old screenshots (older than 1 day)
                    self._cleanup_old_screenshots()
                    
                    return screenshot_path
                else:
                    print(f"[ERROR] Screenshot too small or missing")
                    logger.error("Screenshot too small or missing")
                    self._emit_error("Screenshot verification failed")
                    return None
                        
            except Exception as e:
                error_str = str(e).lower()
                if 'connection' in error_str or 'remote end closed' in error_str:
                    # Connection error - retry if attempts remain
                    print(f"[WARN] Connection error on attempt {attempt + 1}: {e}")
                    logger.warning(f"Connection error on load_page attempt {attempt + 1}: {e}")
                    if attempt < max_retries - 1:
                        print(f"[INFO] Retrying in 3 seconds...")
                        time.sleep(3)
                        continue
                    else:
                        print(f"[ERROR] Failed after {max_retries} attempts")
                        return None
                else:
                    # Other error - fail immediately
                    print(f"[ERROR] Failed to capture: {e}")
                    logger.error(f"Failed to capture screenshot: {e}")
                    self._emit_error(f"Screenshot capture failed: {e}")
                    import traceback
                    traceback.print_exc()
                    return None
        
        # If we get here, all retries failed
        return None
    
    def analyze_heatmap(self, screenshot_path):
        """Analyze heatmap colors to extract liquidation levels
        
        Returns:
            tuple: (liquidation_zones list, image_height int)
        """
        print("[INFO] Analyzing heatmap colors...")
        
        try:
            # Load image
            img = cv2.imread(screenshot_path)
            if img is None:
                print("[ERROR] Could not load screenshot")
                return [], None
            
            img_height, img_width = img.shape[:2]
            print(f"[OK] Image loaded: {img_width}x{img_height} pixels")
            
            # Apply CLAHE contrast enhancement on LAB color space
            print("[INFO] Applying CLAHE contrast enhancement...")
            lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
            cl = clahe.apply(l)
            enhanced_lab = cv2.merge((cl, a, b))
            img_enhanced = cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2BGR)
            
            # Convert to HSV for better color detection
            hsv = cv2.cvtColor(img_enhanced, cv2.COLOR_BGR2HSV)
            
            # Define color ranges for liquidation intensity (more relaxed for headless)
            # Red zones = high liquidation density
            # Orange/Yellow = medium density
            # Green = low density
            
            red_ranges = [
                ((0, 50, 80), (10, 255, 255)),     # Red 1 (relaxed saturation)
                ((170, 50, 80), (180, 255, 255))   # Red 2 (relaxed saturation)
            ]
            
            orange_ranges = [
                ((10, 50, 80), (25, 255, 255))     # Orange (relaxed)
            ]
            
            yellow_ranges = [
                ((25, 50, 80), (40, 255, 255))     # Yellow (wider range)
            ]
            
            green_ranges = [
                ((40, 50, 80), (80, 255, 255))     # Green (for low density)
            ]
            
            liquidation_zones = []
            
            # Apply morphological closing to join fragmented zones
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
            
            # Detect red zones (strongest liquidations)
            for lower, upper in red_ranges:
                mask = cv2.inRange(hsv, np.array(lower), np.array(upper))
                # Morphological closing to join nearby regions
                mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
                contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                
                for contour in contours:
                    area = cv2.contourArea(contour)
                    if area > 100:  # Filter small noise
                        M = cv2.moments(contour)
                        if M["m00"] != 0:
                            cx = int(M["m10"] / M["m00"])
                            cy = int(M["m01"] / M["m00"])
                            
                            liquidation_zones.append({
                                'x': cx,
                                'y': cy,
                                'area': area,
                                'intensity': 'high',
                                'color': 'red'
                            })
            
            # Detect orange zones (medium liquidations)
            for lower, upper in orange_ranges:
                mask = cv2.inRange(hsv, np.array(lower), np.array(upper))
                mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
                contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                
                for contour in contours:
                    area = cv2.contourArea(contour)
                    if area > 100:  # Reduced threshold
                        M = cv2.moments(contour)
                        if M["m00"] != 0:
                            cx = int(M["m10"] / M["m00"])
                            cy = int(M["m01"] / M["m00"])
                            
                            liquidation_zones.append({
                                'x': cx,
                                'y': cy,
                                'area': area,
                                'intensity': 'medium',
                                'color': 'orange'
                            })
            
            # Detect yellow zones (medium-low liquidations)
            for lower, upper in yellow_ranges:
                mask = cv2.inRange(hsv, np.array(lower), np.array(upper))
                mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
                contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                
                for contour in contours:
                    area = cv2.contourArea(contour)
                    if area > 100:
                        M = cv2.moments(contour)
                        if M["m00"] != 0:
                            cx = int(M["m10"] / M["m00"])
                            cy = int(M["m01"] / M["m00"])
                            
                            liquidation_zones.append({
                                'x': cx,
                                'y': cy,
                                'area': area,
                                'intensity': 'medium',
                                'color': 'yellow'
                            })
            
            # Detect green zones (low liquidations)
            for lower, upper in green_ranges:
                mask = cv2.inRange(hsv, np.array(lower), np.array(upper))
                mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
                contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                mask = cv2.inRange(hsv, np.array(lower), np.array(upper))
                contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                
                for contour in contours:
                    area = cv2.contourArea(contour)
                    if area > 150:  # Larger threshold for green
                        M = cv2.moments(contour)
                        if M["m00"] != 0:
                            cx = int(M["m10"] / M["m00"])
                            cy = int(M["m01"] / M["m00"])
                            
                            liquidation_zones.append({
                                'x': cx,
                                'y': cy,
                                'area': area,
                                'intensity': 'low',
                                'color': 'green'
                            })
            
            print(f"[OK] Detected {len(liquidation_zones)} liquidation zones")
            logger.info(f"Detected {len(liquidation_zones)} liquidation zones")
            
            if len(liquidation_zones) == 0:
                print("[WARN] No color zones detected, trying looser thresholds...")
                logger.warning("No color zones detected, trying looser thresholds")
                # Try with lower saturation threshold
                for lower, upper in red_ranges:
                    lower_loose = (lower[0], 50, 50)  # Lower saturation
                    mask = cv2.inRange(hsv, np.array(lower_loose), np.array(upper))
                    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    
                    for contour in contours:
                        area = cv2.contourArea(contour)
                        if area > 50:
                            M = cv2.moments(contour)
                            if M["m00"] != 0:
                                cx = int(M["m10"] / M["m00"])
                                cy = int(M["m01"] / M["m00"])
                                
                                liquidation_zones.append({
                                    'x': cx,
                                    'y': cy,
                                    'area': area,
                                    'intensity': 'medium',
                                    'color': 'red'
                                })
                
                print(f"[INFO] After loose detection: {len(liquidation_zones)} zones")
            
            # Save annotated image
            annotated = img.copy()
            for zone in liquidation_zones:
                color = (0, 0, 255) if zone['color'] == 'red' else (0, 165, 255)
                cv2.circle(annotated, (zone['x'], zone['y']), 10, color, -1)
                # Add text label
                cv2.putText(annotated, zone['intensity'][:1].upper(), 
                           (zone['x']-5, zone['y']-15), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            
            annotated_path = f"coinglass_annotated_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            cv2.imwrite(annotated_path, annotated)
            print(f"[DEBUG] Annotated image saved: {annotated_path}")
            
            return liquidation_zones, img_height
            
        except Exception as e:
            print(f"[ERROR] Heatmap analysis failed: {e}")
            logger.error(f"Heatmap analysis failed: {e}")
            self._emit_error(f"Heatmap analysis failed: {e}")
            import traceback
            traceback.print_exc()
            return [], None
    
    def estimate_liquidation_prices(self, zones, current_price=89000, img_height=None):
        """Estimate liquidation prices from visual zones
        
        Args:
            zones: Detected liquidation zones with x,y coordinates
            current_price: Current BTC price
            img_height: Actual image height (will be auto-detected from zones if not provided)
        """
        print(f"[INFO] Estimating liquidation prices from {len(zones)} zones...")
        print(f"[INFO] Using current BTC price: ${current_price:,.2f}")
        
        liquidations = []
        
        # Assume y-axis represents price (top = higher price, bottom = lower price)
        # Chart typically shows ±10% range
        
        if not zones:
            print("[WARN] No zones to process")
            return liquidations
        
        # Get image height - if not provided, infer from zones
        # Use reasonable default range for heatmap (not just max zone position!)
        if img_height is None:
            y_positions = [z['y'] for z in zones]
            if y_positions:
                # Assume zones span middle 60% of heatmap, extrapolate full height
                min_y, max_y = min(y_positions), max(y_positions)
                y_span = max_y - min_y
                # Assume detected zones represent ~60% of chart height
                img_height = int(y_span / 0.6) if y_span > 100 else 1440
                # Ensure reasonable bounds
                img_height = max(800, min(img_height, 2000))
            else:
                img_height = 1440  # Default for 2560x1440 window
        
        print(f"[DEBUG] Using image height: {img_height}px")
        y_positions = [z['y'] for z in zones]
        if y_positions:
            print(f"[DEBUG] Zone Y-positions range: {min(y_positions)} to {max(y_positions)}")
        
        # Map y-coordinates to prices
        for zone in zones:
            y = zone['y']
            
            # Normalize y position (0 = top, 1 = bottom)
            y_norm = y / img_height
            
            # Map to price range (assuming ±10% range)
            # top (y=0) = current_price * 1.10
            # middle (y=0.5) = current_price
            # bottom (y=1) = current_price * 0.90
            
            price_range = current_price * 0.20  # ±10%
            estimated_price = current_price * 1.10 - (y_norm * price_range)
            
            # Estimate leverage from intensity
            if zone['intensity'] == 'high':
                leverage_range = ['100x', '125x', '50x']
            elif zone['intensity'] == 'medium':
                leverage_range = ['25x', '20x', '30x']
            else:
                leverage_range = ['10x', '15x', '5x']
            
            liquidations.append({
                'price': current_price,
                'liquidation': round(estimated_price, 2),
                'type': 'LONG' if estimated_price < current_price else 'SHORT',
                'leverage': leverage_range[0],
                'distance_pct': round(abs((estimated_price - current_price) / current_price * 100), 2),
                'intensity': zone['intensity'],
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
        
        # Sort by distance
        liquidations.sort(key=lambda x: x['distance_pct'])
        
        # Limit to 20 levels
        liquidations = liquidations[:20]
        
        print(f"[OK] Estimated {len(liquidations)} liquidation levels")
        logger.info(f"Estimated {len(liquidations)} liquidation levels from {len(zones)} zones")
        return liquidations
    
    def get_current_btc_price(self):
        """Get current BTC price from CoinGlass page"""
        print("[INFO] Extracting current BTC price...")
        
        try:
            # Try multiple selectors
            price_selectors = [
                "[class*='price']",
                "[class*='current']",
                "h1", "h2", "h3",
                "[data-v-*]"
            ]
            
            for selector in price_selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for elem in elements:
                        text = elem.text
                        # Look for price pattern
                        import re
                        match = re.search(r'[\$]?(\d{1,3}[,]?\d{3}[.,]\d{2})', text)
                        if match:
                            price_str = match.group(1).replace(',', '')
                            price = float(price_str)
                            if 10000 <= price <= 200000:
                                print(f"[OK] Current BTC price: ${price:,.2f}")
                                return price
                except:
                    continue
            
            # Fallback to API
            print("[WARN] Could not extract price from page, using API fallback")
            import requests
            resp = requests.get('https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT', timeout=5)
            data = resp.json()
            price = float(data['markPrice'])
            print(f"[OK] Current BTC price (API): ${price:,.2f}")
            return price
            
        except Exception as e:
            print(f"[WARN] Price extraction failed: {e}, using default")
            return 89000
    
    def upload_to_sheets(self, liquidations):
        """Upload to Google Sheets"""
        print("[INFO] Uploading to Google Sheets...")
        
        try:
            scope = ['https://spreadsheets.google.com/feeds',
                    'https://www.googleapis.com/auth/drive']
            
            # Use correct path relative to script location
            script_dir = os.path.dirname(os.path.abspath(__file__))
            credentials_path = os.path.join(script_dir, 'credentials.json')
            
            creds = ServiceAccountCredentials.from_json_keyfile_name(
                credentials_path, scope)
            client = gspread.authorize(creds)
            
            sheet = client.open_by_key('1ZeS5XS-SvnfTpmWQ5KNchV52b5f1X6qBqTWxnYQbBAQ')
            
            worksheets = {
                '12h_data': 1.5,
                '24h_data': 2.5,
                '48h_data': 4.0,
                '3d_data': 6.0,
                '1w_data': 10.0
            }
            
            upload_count = 0
            
            for ws_name, max_distance in worksheets.items():
                try:
                    worksheet = sheet.worksheet(ws_name)
                    filtered = [liq for liq in liquidations if liq['distance_pct'] <= max_distance]
                    
                    if filtered:
                        rows = []
                        for liq in filtered:
                            # CRITICAL FIX: Bot expects 'price' column to be liquidation price, NOT current price!
                            # Swap price and liquidation columns to match bot's expectations
                            rows.append([
                                liq['liquidation'],  # LIQUIDATION PRICE (was liq['price'])
                                liq['price'],        # CURRENT BTC PRICE (was liq['liquidation'])
                                liq['type'],
                                liq['leverage'],
                                liq['distance_pct'],
                                liq['timestamp']
                            ])
                        
                        # APPEND data instead of clearing - keep historical liquidation levels
                        # Check if sheet has headers, if not add them
                        try:
                            existing_data = worksheet.get_all_values()
                            if not existing_data or existing_data[0][0] != 'price':
                                # No headers, clear and add headers
                                worksheet.clear()
                                worksheet.update(values=[['price', 'liquidation', 'type', 'leverage', 'distance_pct', 'timestamp']], range_name='A1:F1')
                                next_row = 2
                            else:
                                # Headers exist, find next empty row
                                next_row = len(existing_data) + 1
                                # Keep only last 100 rows to prevent sheet bloat
                                if next_row > 100:
                                    # Keep headers + last 50 rows + new data
                                    keep_rows = [existing_data[0]] + existing_data[-50:]
                                    worksheet.clear()
                                    worksheet.update(values=keep_rows, range_name=f'A1:F{len(keep_rows)}')
                                    next_row = len(keep_rows) + 1
                        except Exception as e:
                            print(f"[WARN] Could not check existing data: {e}, clearing sheet")
                            worksheet.clear()
                            worksheet.update(values=[['price', 'liquidation', 'type', 'leverage', 'distance_pct', 'timestamp']], range_name='A1:F1')
                            next_row = 2
                        
                        # Append new rows
                        worksheet.update(values=rows, range_name=f'A{next_row}:F{next_row+len(rows)-1}')
                        
                        print(f"[OK] Uploaded {len(rows)} levels to {ws_name}")
                        upload_count += len(rows)
                        
                except Exception as e:
                    print(f"[ERROR] Failed to update {ws_name}: {e}")
            
            print(f"[OK] Total uploaded: {upload_count} entries")
            logger.info(f"Successfully uploaded {upload_count} entries to Google Sheets")
            return True
            
        except Exception as e:
            print(f"[ERROR] Google Sheets upload failed: {e}")
            logger.error(f"Google Sheets upload failed: {e}")
            self._emit_error(f"Sheets upload failed: {e}")
            return False
    
    def run(self):
        """Main execution"""
        print("\n" + "="*70)
        print("COINGLASS VISUAL SCRAPER - ENHANCED VERSION")
        print("Method: Screenshot + Computer Vision (Color Detection + LSR)")
        print("="*70 + "\n")
        
        start_time = time.time()
        
        try:
            print("[STEP 1/7] Setting up Chrome browser...")
            self.setup_driver()
            
            print("\n[STEP 2/7] Loading CoinGlass page...")
            screenshot_path = self.load_page()
            if not screenshot_path:
                print("[ERROR] Failed to capture screenshot")
                return False
            
            print("\n[STEP 3/7] Extracting current BTC price...")
            current_price = self.get_current_btc_price()
            
            print(f"\n[STEP 4/7] Extracting LSR data...")
            lsr_data = self.extract_lsr_data()
            if lsr_data:
                self.push_lsr_to_sheet(lsr_data)
            else:
                print("[WARN] LSR extraction skipped (data not available)")
            
            print(f"\n[STEP 5/7] Analyzing heatmap colors...")
            zones, img_height = self.analyze_heatmap(screenshot_path)
            
            if not zones:
                print("\n[ERROR] No liquidation zones detected")
                print("[INFO] Troubleshooting steps:")
                print("        1. Check screenshot: {screenshot_path}")
                print("        2. Verify heatmap is visible")
                print("        3. Try adjusting color thresholds")
                print(f"        4. Page may need more load time")
                return False
            
            print(f"\n[STEP 6/7] Estimating liquidation prices...")
            liquidations = self.estimate_liquidation_prices(zones, current_price, img_height)
            
            if not liquidations:
                print("[ERROR] Could not estimate liquidation prices")
                return False
            
            print(f"\n[STEP 7/7] Uploading to Google Sheets...")
            success = self.upload_to_sheets(liquidations)
            
            elapsed = time.time() - start_time
            
            if success:
                print("\n" + "="*70)
                print("✅ COINGLASS SCREENSHOT SCRAPING SUCCESSFUL")
                print("="*70)
                print(f"Method: Screenshot + OpenCV Color Analysis")
                print(f"Execution Time: {elapsed:.1f} seconds")
                print(f"Total Levels: {len(liquidations)}")
                print(f"Zones Detected: {len(zones)}")
                print(f"Current BTC: ${current_price:,.2f}")
                print(f"Source: CoinGlass Liquidation Heatmap")
                print(f"Screenshots: {screenshot_path}")
                print("="*70 + "\n")
                
                # Emit success health event
                self._emit_health(coinglass_ok=True, heatmap_age_s=0)
            else:
                # Emit failure health event
                self._emit_health(coinglass_ok=False, heatmap_age_s=-1)
            
            return success
            
        except Exception as e:
            # Check if it's a connection error
            error_str = str(e).lower()
            if 'connection' in error_str or 'remote end closed' in error_str or 'remotedisconnected' in error_str:
                print(f"[WARN] Connection issue detected: {e}")
                logger.warning(f"Connection error during scraping: {e}")
                # Emit degraded health but don't fail completely
                self._emit_health(coinglass_ok=False, heatmap_age_s=-1)
            else:
                print(f"[ERROR] Scraper failed: {e}")
                logger.error(f"Scraper failed with error: {e}")
                import traceback
                traceback.print_exc()
            return False
            
        finally:
            if self.driver:
                try:
                    self.driver.quit()
                    logger.info("Chrome driver closed successfully")
                except (OSError, Exception) as e:
                    # Suppress handle errors during cleanup - this is expected behavior
                    if "handle is invalid" in str(e).lower() or "winerror 6" in str(e).lower():
                        pass  # Expected cleanup error on Windows
                    else:
                        print(f"[WARN] Driver cleanup warning: {e}")
                        logger.warning(f"Driver cleanup warning: {e}")
                finally:
                    self.driver = None  # Clear reference to prevent double cleanup
    
    def _capture_canvas_as_png(self):
        """Capture canvas element directly as PNG using toDataURL"""
        try:
            import base64
            # Try to find canvas element and extract as PNG
            dataurl = self.driver.execute_script("""
                let canvases = document.querySelectorAll('canvas');
                if (canvases.length === 0) return null;
                
                // Find largest canvas (likely the heatmap)
                let largest = canvases[0];
                let maxArea = 0;
                for (let c of canvases) {
                    let area = c.width * c.height;
                    if (area > maxArea) {
                        maxArea = area;
                        largest = c;
                    }
                }
                
                if (maxArea < 100) return null;  // Too small
                return largest.toDataURL('image/png');
            """)
            
            if not dataurl or not dataurl.startswith('data:image/png;base64,'):
                return None
            
            # Extract base64 data
            _, b64_data = dataurl.split(',', 1)
            png_bytes = base64.b64decode(b64_data)
            
            if len(png_bytes) < 5000:  # Too small to be real heatmap
                return None
                
            return png_bytes
            
        except Exception as e:
            logger.warning(f"Canvas capture failed: {e}")
            return None
    
    def _emit_error(self, error_msg: str):
        """Emit error event if emitter is available"""
        if self.emitter and hasattr(self.emitter, 'insert_error'):
            try:
                self.emitter.insert_error({
                    'ts': datetime.now(timezone.utc).isoformat(),
                    'run_id': self.run_id,
                    'session_id': self.run_id,
                    'component': 'coinglass_scraper',
                    'message': error_msg,
                    'severity': 'error'
                })
            except Exception as e:
                logger.warning(f"Failed to emit error event: {e}")
    
    def _emit_health(self, coinglass_ok: bool, heatmap_age_s: int = 0):
        """Emit health status if emitter is available"""
        if self.emitter and hasattr(self.emitter, 'insert_health'):
            try:
                self.emitter.insert_health({
                    'ts': datetime.now(timezone.utc).isoformat(),
                    'run_id': self.run_id,
                    'session_id': self.run_id,
                    'coinglass_ok': coinglass_ok,
                    'heatmap_age_s': heatmap_age_s,
                    'price_age_s': 0,
                    'ws_connected': True,
                    'positions_open': 0,
                    'risk_used_pct': 0.0,
                    'daily_cap_hit': False
                })
            except Exception as e:
                logger.warning(f"Failed to emit health event: {e}")
    
    def _cleanup_old_screenshots(self):
        """Delete screenshots older than 1 day"""
        try:
            import glob
            from pathlib import Path
            
            # Get current working directory
            base_dir = os.getcwd()
            
            # Find all coinglass screenshot files
            patterns = [
                os.path.join(base_dir, 'coinglass_full_*.png'),
                os.path.join(base_dir, 'coinglass_annotated_*.png')
            ]
            
            cutoff_time = time.time() - (24 * 3600)  # 1 day ago
            deleted_count = 0
            
            for pattern in patterns:
                for filepath in glob.glob(pattern):
                    try:
                        # Check file modification time
                        file_mtime = os.path.getmtime(filepath)
                        if file_mtime < cutoff_time:
                            os.remove(filepath)
                            deleted_count += 1
                    except Exception as e:
                        logger.warning(f"Failed to delete {filepath}: {e}")
            
            if deleted_count > 0:
                print(f"[INFO] Cleaned up {deleted_count} old screenshots (>1 day)")
                logger.info(f"Cleaned up {deleted_count} old screenshots")
        
        except Exception as e:
            logger.warning(f"Screenshot cleanup failed: {e}")

if __name__ == "__main__":
    scraper = CoinGlassVisualScraper()
    scraper.run()
