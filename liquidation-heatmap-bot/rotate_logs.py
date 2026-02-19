#!/usr/bin/env python3
"""
Comprehensive Log Rotation Script
Rotates JSONL event logs, CSV files, and regular log files.
Run daily via cron at midnight.
"""
import os
import gzip
import shutil
from datetime import datetime, timedelta
from pathlib import Path

# Configuration
# Auto-detect if running from workspace or server
SCRIPT_DIR = Path(__file__).parent.resolve()
if (SCRIPT_DIR / "logs").exists():
    # Running from workspace directory
    BASE_DIR = SCRIPT_DIR
else:
    # Running from server home directory
    BASE_DIR = Path.home() / "trading_bot"

LOGS_DIR = BASE_DIR / "logs"
EVENTS_DIR = LOGS_DIR / "events"
CSV_DIR = LOGS_DIR / "csv"

# Retention policies (days)
JSONL_RETENTION = 30  # Keep 30 days of compressed event logs
CSV_RETENTION = 7     # Keep 7 days of compressed CSV logs
BACKTEST_RETENTION = 14  # Keep 14 days of backtest logs

# File patterns to rotate
JSONL_FILES = [
    "decision.jsonl",
    "health.jsonl",
    "prediction.jsonl",
    "veto.jsonl",
    "order.jsonl",
    "fill.jsonl",
    "error.jsonl",
    "guard.jsonl",
    "custom_event.jsonl",
    "session.jsonl"
]

def rotate_jsonl_files():
    """Rotate JSONL event files daily."""
    if not EVENTS_DIR.exists():
        print(f"Events directory not found: {EVENTS_DIR}")
        return 0
    
    today = datetime.now()
    date_suffix = today.strftime("%Y%m%d")
    rotated_count = 0
    
    for jsonl_file in JSONL_FILES:
        source_path = EVENTS_DIR / jsonl_file
        
        if not source_path.exists():
            continue
        
        # Check file size - only rotate if > 1KB
        file_size = source_path.stat().st_size
        if file_size < 1024:
            print(f"Skipping {jsonl_file} (size: {file_size} bytes < 1KB)")
            continue
        
        # Create rotated filename with date
        rotated_name = f"{source_path.stem}_{date_suffix}.jsonl"
        rotated_path = EVENTS_DIR / rotated_name
        
        # If rotated file already exists, append timestamp
        if rotated_path.exists():
            timestamp = today.strftime("%Y%m%d_%H%M%S")
            rotated_name = f"{source_path.stem}_{timestamp}.jsonl"
            rotated_path = EVENTS_DIR / rotated_name
        
        # Copy current file to dated filename (instead of move)
        print(f"Rotating {jsonl_file} -> {rotated_name} ({file_size / 1024:.1f} KB)")
        shutil.copy2(str(source_path), str(rotated_path))
        
        # Truncate original file instead of creating new one
        # This preserves the inode so open file handles remain valid
        with open(source_path, 'w') as f:
            pass  # Truncate to 0 bytes
        
        rotated_count += 1
        
        # Compress the rotated file
        compressed_path = rotated_path.with_suffix(".jsonl.gz")
        print(f"  Compressing -> {compressed_path.name}")
        with open(rotated_path, "rb") as f_in:
            with gzip.open(compressed_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        
        # Remove uncompressed rotated file
        rotated_path.unlink()
    
    return rotated_count

def cleanup_old_jsonl():
    """Delete compressed JSONL files older than retention period."""
    if not EVENTS_DIR.exists():
        return 0
    
    today = datetime.now().date()
    cutoff = today - timedelta(days=JSONL_RETENTION)
    deleted_count = 0
    
    for gz_file in EVENTS_DIR.glob("*.jsonl.gz"):
        try:
            # Parse date from filename (e.g., decision_20251203.jsonl.gz)
            stem = gz_file.name.replace(".jsonl.gz", "")
            parts = stem.split("_")
            
            # Handle both formats: file_20251203 and file_20251203_123456
            date_str = None
            for part in reversed(parts):
                if len(part) == 8 and part.isdigit():
                    date_str = part
                    break
            
            if not date_str:
                print(f"Skipping {gz_file.name} - cannot parse date")
                continue
            
            file_date = datetime.strptime(date_str, "%Y%m%d").date()
        except (ValueError, IndexError) as e:
            print(f"Skipping {gz_file.name} - error parsing: {e}")
            continue
        
        # Delete if older than retention period
        age_days = (today - file_date).days
        if file_date < cutoff:
            print(f"Deleting old JSONL archive: {gz_file.name} (age: {age_days} days)")
            gz_file.unlink()
            deleted_count += 1
    
    return deleted_count

def rotate_csv_files():
    """Rotate CSV files - compress files older than 1 day."""
    if not CSV_DIR.exists():
        print(f"CSV directory not found: {CSV_DIR}")
        return 0
    
    today = datetime.now().date()
    cutoff = today - timedelta(days=1)
    compressed_count = 0
    
    for csv_file in CSV_DIR.glob("*.csv"):
        # Skip if already compressed
        if csv_file.suffix == ".gz":
            continue
        
        # Get file modification time
        mtime = datetime.fromtimestamp(csv_file.stat().st_mtime).date()
        
        # Compress if older than 1 day
        if mtime < cutoff:
            gz_path = csv_file.with_suffix(".csv.gz")
            file_size = csv_file.stat().st_size
            print(f"Compressing {csv_file.name} -> {gz_path.name} ({file_size / 1024:.1f} KB)")
            
            with open(csv_file, "rb") as f_in:
                with gzip.open(gz_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            # Remove original after successful compression
            csv_file.unlink()
            compressed_count += 1
    
    return compressed_count

def cleanup_old_csv():
    """Delete compressed CSV files older than retention period."""
    if not CSV_DIR.exists():
        return 0
    
    today = datetime.now().date()
    cutoff = today - timedelta(days=CSV_RETENTION)
    deleted_count = 0
    
    for gz_file in CSV_DIR.glob("*.csv.gz"):
        # Get file modification time
        mtime = datetime.fromtimestamp(gz_file.stat().st_mtime).date()
        age_days = (today - mtime).days
        
        # Delete if older than retention period
        if mtime < cutoff:
            print(f"Deleting old CSV archive: {gz_file.name} (age: {age_days} days)")
            gz_file.unlink()
            deleted_count += 1
    
    return deleted_count

def cleanup_backtest_logs():
    """Clean up old backtest logs."""
    backtest_dir = LOGS_DIR / "backtests"
    if not backtest_dir.exists():
        return 0
    
    today = datetime.now().date()
    cutoff = today - timedelta(days=BACKTEST_RETENTION)
    deleted_count = 0
    
    for log_file in backtest_dir.glob("*.log"):
        mtime = datetime.fromtimestamp(log_file.stat().st_mtime).date()
        age_days = (today - mtime).days
        
        if mtime < cutoff:
            print(f"Deleting old backtest log: {log_file.name} (age: {age_days} days)")
            log_file.unlink()
            deleted_count += 1
    
    return deleted_count

def cleanup_old_binance_csv():
    """Delete old Binance liquidation/LS ratio CSV files (>7 days)."""
    if not BASE_DIR.exists():
        return 0
    
    today = datetime.now().date()
    cutoff = today - timedelta(days=7)
    deleted_count = 0
    
    # Pattern: binance_liquidations_20251212_*.csv and binance_ls_ratio_20251212_*.csv
    for csv_file in BASE_DIR.glob("binance_*.csv"):
        # Get file modification time
        mtime = datetime.fromtimestamp(csv_file.stat().st_mtime).date()
        age_days = (today - mtime).days
        
        if mtime < cutoff:
            print(f"Deleting old Binance CSV: {csv_file.name} (age: {age_days} days)")
            csv_file.unlink()
            deleted_count += 1
    
    return deleted_count

def cleanup_old_screenshots():
    """Delete old CoinGlass screenshot PNG files (>7 days)."""
    if not BASE_DIR.exists():
        return 0
    
    today = datetime.now().date()
    cutoff = today - timedelta(days=7)
    deleted_count = 0
    
    # Pattern: coinglass_*.png
    for png_file in BASE_DIR.glob("coinglass_*.png"):
        # Get file modification time
        mtime = datetime.fromtimestamp(png_file.stat().st_mtime).date()
        age_days = (today - mtime).days
        
        if mtime < cutoff:
            print(f"Deleting old screenshot: {png_file.name} (age: {age_days} days)")
            png_file.unlink()
            deleted_count += 1
    
    return deleted_count

def cleanup_old_bot_logs():
    """Delete old bot log files (>7 days) and compress large active logs."""
    if not BASE_DIR.exists():
        return 0
    
    today = datetime.now().date()
    cutoff = today - timedelta(days=7)
    deleted_count = 0
    compressed_count = 0
    
    # Clean up old log files
    for log_file in BASE_DIR.glob("*.log"):
        # Skip the main active bot.log
        if log_file.name == "bot.log":
            # Check if it needs rotation (>10MB)
            file_size = log_file.stat().st_size
            max_size = 10 * 1024 * 1024  # 10 MB
            
            if file_size > max_size:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                rotated_name = f"bot_{timestamp}.log"
                rotated_path = BASE_DIR / rotated_name
                
                print(f"Rotating bot.log -> {rotated_name} ({file_size / 1024 / 1024:.1f} MB)")
                shutil.move(str(log_file), str(rotated_path))
                
                # Compress it
                compressed_path = rotated_path.with_suffix(".log.gz")
                with open(rotated_path, "rb") as f_in:
                    with gzip.open(compressed_path, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
                rotated_path.unlink()
                log_file.touch()
                compressed_count += 1
            continue
        
        # Delete old log files
        mtime = datetime.fromtimestamp(log_file.stat().st_mtime).date()
        age_days = (today - mtime).days
        
        if mtime < cutoff:
            print(f"Deleting old log: {log_file.name} (age: {age_days} days)")
            log_file.unlink()
            deleted_count += 1
    
    # Clean up old compressed log archives (>14 days)
    cutoff_gz = today - timedelta(days=14)
    for gz_file in BASE_DIR.glob("*.log.gz"):
        mtime = datetime.fromtimestamp(gz_file.stat().st_mtime).date()
        age_days = (today - mtime).days
        
        if mtime < cutoff_gz:
            print(f"Deleting old log archive: {gz_file.name} (age: {age_days} days)")
            gz_file.unlink()
            deleted_count += 1
    
    return deleted_count, compressed_count

def rotate_bot_log():
    """Deprecated - use cleanup_old_bot_logs instead."""
    return False

def main():
    print("=" * 80)
    print(f"LOG ROTATION - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    print(f"Base directory: {BASE_DIR}")
    print(f"Retention: JSONL={JSONL_RETENTION}d, CSV={CSV_RETENTION}d, Backtest={BACKTEST_RETENTION}d")
    print()
    
    # 1. Rotate JSONL event logs
    print("[1/9] Rotating JSONL event logs...")
    jsonl_rotated = rotate_jsonl_files()
    print(f"  ✓ Rotated {jsonl_rotated} JSONL files")
    print()
    
    # 2. Clean up old JSONL archives
    print("[2/9] Cleaning up old JSONL archives...")
    jsonl_deleted = cleanup_old_jsonl()
    print(f"  ✓ Deleted {jsonl_deleted} old JSONL archives")
    print()
    
    # 3. Compress old CSV files
    print("[3/9] Compressing CSV files...")
    csv_compressed = rotate_csv_files()
    print(f"  ✓ Compressed {csv_compressed} CSV files")
    print()
    
    # 4. Clean up old CSV archives
    print("[4/9] Cleaning up old CSV archives...")
    csv_deleted = cleanup_old_csv()
    print(f"  ✓ Deleted {csv_deleted} old CSV archives")
    print()
    
    # 5. Clean up backtest logs
    print("[5/9] Cleaning up backtest logs...")
    backtest_deleted = cleanup_backtest_logs()
    print(f"  ✓ Deleted {backtest_deleted} old backtest logs")
    print()
    
    # 6. Clean up Binance CSV files
    print("[6/9] Cleaning up Binance CSV files...")
    binance_deleted = cleanup_old_binance_csv()
    print(f"  ✓ Deleted {binance_deleted} old Binance CSV files")
    print()
    
    # 7. Clean up CoinGlass screenshots
    print("[7/9] Cleaning up CoinGlass screenshots...")
    screenshots_deleted = cleanup_old_screenshots()
    print(f"  ✓ Deleted {screenshots_deleted} old screenshots")
    print()
    
    # 8. Clean up bot logs
    print("[8/9] Cleaning up bot logs...")
    logs_deleted, logs_compressed = cleanup_old_bot_logs()
    print(f"  ✓ Deleted {logs_deleted} old logs, compressed {logs_compressed} large logs")
    print()
    
    # 9. Check bot.log rotation (deprecated, now handled in step 8)
    print("[9/9] Bot log rotation...")
    print("  ✓ Handled in step 8")
    print()
    
    print("=" * 80)
    print("ROTATION COMPLETE")
    total_deleted = jsonl_deleted + csv_deleted + binance_deleted + screenshots_deleted + logs_deleted
    print(f"Summary: {jsonl_rotated} JSONL rotated, {total_deleted} files deleted, {csv_compressed + logs_compressed} files compressed")
    print("=" * 80)

if __name__ == "__main__":
    main()
