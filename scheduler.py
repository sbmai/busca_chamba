"""
Daily job scraper scheduler
============================
Runs scraper.py automatically every day at 08:00.

Usage:
    python scheduler.py              # starts the scheduler (keep terminal open)
    python scheduler.py --now        # run one scrape immediately, then schedule daily

Keep this process running (e.g. in a dedicated terminal, or as a background
service). On Windows you can also use Task Scheduler instead — see README.md.
"""

import argparse
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import schedule
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("scheduler")

SCRIPT_DIR = Path(__file__).parent.resolve()
SCRAPER = str(SCRIPT_DIR / "scraper.py")
RUN_TIME = "08:00"


def run_scraper():
    logger.info(f"Starting scrape at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ...")
    try:
        result = subprocess.run(
            [sys.executable, SCRAPER],
            cwd=str(SCRIPT_DIR),
        )
        if result.returncode == 0:
            logger.info("Scrape completed successfully.")
        else:
            logger.error(f"Scraper exited with code {result.returncode}")
    except Exception as e:
        logger.error(f"Failed to launch scraper: {e}")


def main():
    parser = argparse.ArgumentParser(description="Peru Job Scraper — Daily Scheduler")
    parser.add_argument(
        "--now",
        action="store_true",
        help="Run one scrape immediately before entering the daily schedule",
    )
    parser.add_argument(
        "--time",
        default=RUN_TIME,
        metavar="HH:MM",
        help=f"Daily run time in 24h format (default: {RUN_TIME})",
    )
    args = parser.parse_args()

    run_time = args.time
    schedule.every().day.at(run_time).do(run_scraper)
    logger.info(f"Scheduler started — scraper.py will run daily at {run_time}.")
    logger.info("Press Ctrl+C to stop.")

    if args.now:
        logger.info("--now flag detected, running immediately...")
        run_scraper()

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
