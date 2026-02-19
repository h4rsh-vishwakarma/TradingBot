#!/usr/bin/env python3
"""
CSV Log Rotation Script
Compresses old CSV files and deletes files older than retention period.
Run daily via cron.
"""
import os
import gzip
import shutil
from datetime import datetime, timedelta
from pathlib import Path

# Configuration
CSV_DIR = Path.home() / "trading_bot" / "logs" / "csv"
RETENTION_DAYS = 7  # Keep last 7 days of compressed logs
COMPRESS_AFTER_DAYS = 1  # Compress files older than 1 day

def compress_old_files():
    """Compress CSV files older than COMPRESS_AFTER_DAYS."""
    today = datetime.now().date()
    cutoff = today - timedelta(days=COMPRESS_AFTER_DAYS)
    
    compressed_count = 0
    for csv_file in CSV_DIR.glob("*.csv"):
        # Skip if already compressed
        if csv_file.suffix == ".gz":
            continue
            
        # Parse date from filename (e.g., decisions_20251211.csv)
        try:
            date_str = csv_file.stem.split("_")[-1]  # Get "20251211"
            file_date = datetime.strptime(date_str, "%Y%m%d").date()
        except (ValueError, IndexError):
            print(f"Skipping {csv_file.name} - cannot parse date")
            continue
        
        # Compress if older than cutoff
        if file_date < cutoff:
            gz_path = csv_file.with_suffix(".csv.gz")
            print(f"Compressing {csv_file.name} -> {gz_path.name}")
            
            with open(csv_file, "rb") as f_in:
                with gzip.open(gz_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            # Remove original after successful compression
            csv_file.unlink()
            compressed_count += 1
    
    return compressed_count

def delete_old_archives():
    """Delete compressed files older than RETENTION_DAYS."""
    today = datetime.now().date()
    cutoff = today - timedelta(days=RETENTION_DAYS)
    
    deleted_count = 0
    for gz_file in CSV_DIR.glob("*.csv.gz"):
        try:
            # Parse date from filename (e.g., decisions_20251203.csv.gz)
            stem = gz_file.name.replace(".csv.gz", "")
            date_str = stem.split("_")[-1]
            file_date = datetime.strptime(date_str, "%Y%m%d").date()
        except (ValueError, IndexError):
            print(f"Skipping {gz_file.name} - cannot parse date")
            continue
        
        # Delete if older than retention period
        if file_date < cutoff:
            print(f"Deleting old archive: {gz_file.name} (age: {(today - file_date).days} days)")
            gz_file.unlink()
            deleted_count += 1
    
    return deleted_count

def main():
    print(f"CSV Log Rotation - {datetime.now()}")
    print(f"Directory: {CSV_DIR}")
    print(f"Retention: {RETENTION_DAYS} days")
    print("-" * 60)
    
    # Compress old uncompressed files
    compressed = compress_old_files()
    print(f"Compressed {compressed} files")
    
    # Delete old archives
    deleted = delete_old_archives()
    print(f"Deleted {deleted} old archives")
    
    print("Done")

if __name__ == "__main__":
    main()
