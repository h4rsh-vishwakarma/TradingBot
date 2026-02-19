#!/usr/bin/env python3
"""
Cron Health Monitoring Script
Verifies all required scrapers are scheduled and running
Sends alerts if any critical components are missing
"""

import subprocess
import sys
from datetime import datetime
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

REQUIRED_CRON_JOBS = [
    {
        'name': 'OI/Funding Scraper',
        'script': 'collect_oi_funding.py',
        'required': True,
        'expected_interval': '*/1 * * * *'  # Every minute
    },
    {
        'name': 'Coinglass Heatmap Scraper',
        'script': 'coinglass_visual_scraper.py',
        'required': True,
        'expected_interval': '*/1 * * * *'  # Every minute
    },
    {
        'name': 'LSR Scraper',
        'script': 'coinglass_lsr_scraper.py',
        'required': True,
        'expected_interval': '*/1 * * * *'  # Every minute
    },
    {
        'name': 'Log Rotation',
        'script': 'rotate_logs.py',
        'required': True,
        'expected_interval': '0 0 * * *'  # Daily midnight
    }
]

def get_current_crontab():
    """Get current user's crontab"""
    try:
        result = subprocess.run(
            ['crontab', '-l'],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to read crontab: {e}")
        return ""

def check_cron_job(job_config, crontab_content):
    """Check if a specific cron job is present"""
    script_name = job_config['script']
    is_present = script_name in crontab_content
    
    status = {
        'name': job_config['name'],
        'script': script_name,
        'present': is_present,
        'required': job_config['required']
    }
    
    if is_present:
        # Extract the cron line
        for line in crontab_content.split('\n'):
            if script_name in line and not line.strip().startswith('#'):
                status['cron_line'] = line.strip()
                break
    
    return status

def check_scraper_processes():
    """Check if scraper processes are running"""
    try:
        result = subprocess.run(
            ['pgrep', '-a', 'python3'],
            capture_output=True,
            text=True
        )
        
        processes = result.stdout
        running_scrapers = []
        
        for job in REQUIRED_CRON_JOBS:
            if job['script'] in processes:
                running_scrapers.append(job['name'])
        
        return running_scrapers
    except Exception as e:
        logger.error(f"Failed to check processes: {e}")
        return []

def main():
    logger.info("=" * 70)
    logger.info("CRON HEALTH CHECK - " + datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    logger.info("=" * 70)
    
    crontab_content = get_current_crontab()
    
    if not crontab_content:
        logger.error("❌ CRITICAL: Unable to read crontab!")
        sys.exit(1)
    
    all_ok = True
    missing_jobs = []
    
    logger.info("\n📋 CHECKING REQUIRED CRON JOBS:")
    logger.info("-" * 70)
    
    for job in REQUIRED_CRON_JOBS:
        status = check_cron_job(job, crontab_content)
        
        if status['present']:
            logger.info(f"✅ {status['name']}: PRESENT")
            logger.info(f"   └─ {status.get('cron_line', 'N/A')}")
        else:
            if status['required']:
                logger.error(f"❌ {status['name']}: MISSING (REQUIRED!)")
                missing_jobs.append(status['name'])
                all_ok = False
            else:
                logger.warning(f"⚠️  {status['name']}: MISSING (optional)")
    
    logger.info("\n" + "=" * 70)
    
    # Check running processes
    logger.info("\n🔄 CHECKING ACTIVE SCRAPER PROCESSES:")
    logger.info("-" * 70)
    running = check_scraper_processes()
    if running:
        for scraper in running:
            logger.info(f"✅ {scraper}: RUNNING")
    else:
        logger.warning("⚠️  No scraper processes currently running (may be between cron intervals)")
    
    logger.info("\n" + "=" * 70)
    
    # Final verdict
    if all_ok:
        logger.info("✅ CRON HEALTH CHECK: PASSED")
        logger.info("All required cron jobs are properly scheduled.")
        sys.exit(0)
    else:
        logger.error("❌ CRON HEALTH CHECK: FAILED")
        logger.error(f"Missing required jobs: {', '.join(missing_jobs)}")
        logger.error("\nTO FIX: Run the following commands to add missing jobs:")
        
        for job in REQUIRED_CRON_JOBS:
            status = check_cron_job(job, crontab_content)
            if not status['present'] and status['required']:
                logger.error(f"\n# Add {job['name']}:")
                logger.error(f"crontab -l > /tmp/crontab.txt")
                logger.error(f"echo '{job['expected_interval']} cd /home/ubuntu/trading_bot && "
                           f"/home/ubuntu/trading_bot/venv/bin/python3 {job['script']} >> "
                           f"/home/ubuntu/{job['script'].replace('.py', '.log')} 2>&1' >> /tmp/crontab.txt")
                logger.error(f"crontab /tmp/crontab.txt")
        
        sys.exit(1)

if __name__ == "__main__":
    main()
