#!/usr/bin/env python3
"""Cleanup old CoinGlass screenshots (older than 1 day)"""

import os
import glob
import time

def cleanup_screenshots():
    """Delete screenshots older than 1 day"""
    base_dir = '/home/ubuntu/trading_bot'
    
    patterns = [
        os.path.join(base_dir, 'coinglass_full_*.png'),
        os.path.join(base_dir, 'coinglass_annotated_*.png')
    ]
    
    cutoff_time = time.time() - (24 * 3600)  # 1 day ago
    deleted_count = 0
    kept_count = 0
    
    for pattern in patterns:
        for filepath in glob.glob(pattern):
            try:
                file_mtime = os.path.getmtime(filepath)
                if file_mtime < cutoff_time:
                    os.remove(filepath)
                    deleted_count += 1
                else:
                    kept_count += 1
            except Exception as e:
                print(f"Failed to delete {filepath}: {e}")
    
    print(f"Cleanup complete: Deleted {deleted_count}, Kept {kept_count}")

if __name__ == '__main__':
    cleanup_screenshots()
