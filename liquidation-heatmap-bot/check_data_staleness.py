#!/usr/bin/env python3
"""
Data Staleness Monitor
Checks all data feeds and alerts if any exceed thresholds
Runs every minute via cron to catch staleness issues early
"""

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timezone
import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Thresholds (in seconds)
THRESHOLDS = {
    'oi': 90,      # Target: under 90s
    'funding': 90, # Target: under 90s
    'lsr': 90,     # Target: under 90s
    'heatmap': 120 # Heatmap takes longer to scrape
}

# Warning threshold (50% of limit)
WARNING_MULTIPLIER = 0.5

def connect_to_sheets():
    """Connect to Google Sheets"""
    scope = [
        'https://spreadsheets.google.com/feeds',
        'https://www.googleapis.com/auth/drive'
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(
        '/home/ubuntu/trading_bot/credentials.json',
        scope
    )
    return gspread.authorize(creds)

def check_sheet_staleness(client, sheet_key, worksheet_name, timestamp_col='A'):
    """Check staleness of a specific sheet"""
    try:
        sheet = client.open_by_key(sheet_key).worksheet(worksheet_name)
        timestamps = sheet.col_values(1)  # Column A
        
        if not timestamps or len(timestamps) <= 1:
            return None, 0, "NO_DATA"
        
        last_timestamp_str = timestamps[-1]
        
        # Parse timestamp
        try:
            # Try with timezone
            last_timestamp = datetime.fromisoformat(last_timestamp_str.replace('Z', '+00:00'))
            if last_timestamp.tzinfo is None:
                last_timestamp = last_timestamp.replace(tzinfo=timezone.utc)
        except:
            # Try alternative format without timezone
            try:
                last_timestamp = datetime.strptime(last_timestamp_str, '%Y-%m-%d %H:%M:%S')
                last_timestamp = last_timestamp.replace(tzinfo=timezone.utc)
            except:
                # Try with microseconds
                last_timestamp = datetime.strptime(last_timestamp_str.split('.')[0], '%Y-%m-%d %H:%M:%S')
                last_timestamp = last_timestamp.replace(tzinfo=timezone.utc)
        
        now = datetime.now(timezone.utc)
        age_seconds = (now - last_timestamp).total_seconds()
        
        return last_timestamp, age_seconds, "OK"
        
    except Exception as e:
        logger.error(f"Error checking {worksheet_name}: {e}")
        return None, 0, f"ERROR: {str(e)}"

def main():
    logger.info("=" * 70)
    logger.info("DATA STALENESS CHECK - " + datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'))
    logger.info("=" * 70)
    
    try:
        client = connect_to_sheets()
    except Exception as e:
        logger.error(f"❌ Failed to connect to Google Sheets: {e}")
        sys.exit(1)
    
    # Check all feeds
    feeds = [
        {
            'name': 'Open Interest',
            'key': '1ysGcPSyyJrlX3Wo7C4s7TCkRVF-d9YlvG7LbZeNNQ8k',
            'worksheet': 'oi',
            'threshold': THRESHOLDS['oi']
        },
        {
            'name': 'Funding Rate',
            'key': '1ysGcPSyyJrlX3Wo7C4s7TCkRVF-d9YlvG7LbZeNNQ8k',
            'worksheet': 'fr',
            'threshold': THRESHOLDS['funding']
        },
        {
            'name': 'Long/Short Ratio',
            'key': '1ysGcPSyyJrlX3Wo7C4s7TCkRVF-d9YlvG7LbZeNNQ8k',
            'worksheet': 'lsr',
            'threshold': THRESHOLDS['lsr']
        },
        {
            'name': 'Heatmap 24h',
            'key': '1tBXe1xHXa-tT-YL-KLq1iZjnk9xkq60XqDn63f5Uydk',
            'worksheet': '24h',
            'threshold': THRESHOLDS['heatmap']
        }
    ]
    
    issues_found = []
    warnings_found = []
    
    logger.info("\n📊 CHECKING DATA FEED STALENESS:")
    logger.info("-" * 70)
    
    for feed in feeds:
        timestamp, age, status = check_sheet_staleness(
            client,
            feed['key'],
            feed['worksheet']
        )
        
        if status != "OK":
            logger.error(f"❌ {feed['name']}: {status}")
            issues_found.append(f"{feed['name']} - {status}")
            continue
        
        threshold = feed['threshold']
        warning_threshold = threshold * WARNING_MULTIPLIER
        
        if age > threshold:
            logger.error(f"❌ {feed['name']}: {age:.1f}s (EXCEEDS {threshold}s threshold!)")
            logger.error(f"   Last update: {timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}")
            issues_found.append(f"{feed['name']} - {age:.1f}s > {threshold}s")
        elif age > warning_threshold:
            logger.warning(f"⚠️  {feed['name']}: {age:.1f}s (approaching {threshold}s threshold)")
            logger.warning(f"   Last update: {timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}")
            warnings_found.append(f"{feed['name']} - {age:.1f}s")
        else:
            logger.info(f"✅ {feed['name']}: {age:.1f}s (< {threshold}s) ✓")
            logger.info(f"   Last update: {timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    
    logger.info("\n" + "=" * 70)
    
    # Final verdict
    if issues_found:
        logger.error(f"❌ STALENESS CHECK: FAILED ({len(issues_found)} issues)")
        for issue in issues_found:
            logger.error(f"   - {issue}")
        
        logger.error("\n🔧 RECOMMENDED ACTIONS:")
        logger.error("1. Check if scrapers are running: pgrep -a python3 | grep scraper")
        logger.error("2. Check cron jobs: crontab -l")
        logger.error("3. Check scraper logs: tail -50 /home/ubuntu/*.log")
        logger.error("4. Manually run scrapers if needed")
        
        sys.exit(1)
    elif warnings_found:
        logger.warning(f"⚠️  STALENESS CHECK: WARNINGS ({len(warnings_found)} feeds)")
        for warning in warnings_found:
            logger.warning(f"   - {warning}")
        sys.exit(0)
    else:
        logger.info("✅ STALENESS CHECK: PASSED")
        logger.info("All data feeds are fresh and within acceptable limits.")
        sys.exit(0)

if __name__ == "__main__":
    main()
