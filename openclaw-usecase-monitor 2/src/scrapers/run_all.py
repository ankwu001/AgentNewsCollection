"""
Run all scrapers and merge results into a single daily raw data file.
Usage: python -m src.scrapers.run_all
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from ..utils.unified_schema import DailyData
from ..utils.logger import get_logger

logger = get_logger("run_all")

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_RAW_DIR = BASE_DIR / "data" / "raw"
DATA_ERROR_DIR = BASE_DIR / "data" / "errors"


def run():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_iso = datetime.now(timezone.utc).isoformat()

    daily = DailyData(date=today, scrape_time=now_iso)
    errors = []

    # Import and run each scraper independently
    scrapers = [
        ("reddit", "src.scrapers.reddit_scraper"),
        ("github", "src.scrapers.github_scraper"),
        ("x", "src.scrapers.x_scraper"),
        ("discord", "src.scrapers.discord_scraper"),
    ]

    for name, module_path in scrapers:
        logger.info(f"--- Running {name} scraper ---")
        try:
            mod = __import__(module_path, fromlist=["scrape"])
            items = mod.scrape()
            for item in items:
                daily.add_item(item)
            logger.info(f"{name}: collected {len(items)} items")
        except Exception as e:
            error_msg = f"{name} scraper failed: {e}"
            logger.error(error_msg)
            errors.append(error_msg)

    # Save raw data
    DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
    output_path = DATA_RAW_DIR / f"{today}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(daily.to_dict(), f, ensure_ascii=False, indent=2)
    logger.info(f"Raw data saved to {output_path} ({daily.total_items} items)")

    # Save errors if any
    if errors:
        DATA_ERROR_DIR.mkdir(parents=True, exist_ok=True)
        error_path = DATA_ERROR_DIR / f"{today}.log"
        with open(error_path, "w") as f:
            f.write("\n".join(errors))
        logger.warning(f"Errors logged to {error_path}")

    return daily


if __name__ == "__main__":
    run()
