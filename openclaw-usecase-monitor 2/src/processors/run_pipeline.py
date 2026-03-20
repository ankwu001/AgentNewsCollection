"""
Processing pipeline: dedup → filter → classify → score.
Reads raw data, processes it, and writes processed data.
Usage: python -m src.processors.run_pipeline
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .dedup import dedup
from .classifier import classify_batch
from .scorer import score_items
from ..utils.logger import get_logger

logger = get_logger("pipeline")

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = BASE_DIR / "config"
DATA_RAW_DIR = BASE_DIR / "data" / "raw"
DATA_PROCESSED_DIR = BASE_DIR / "data" / "processed"


def _load_filters() -> dict:
    with open(CONFIG_DIR / "filters.json") as f:
        return json.load(f)


def _apply_filters(items: list[dict], filters: dict) -> list[dict]:
    """Apply content filters to remove noise."""
    min_len = filters.get("min_content_length", 20)
    max_len = filters.get("max_content_length", 50000)
    exclude_authors = [a.lower() for a in filters.get("exclude_authors", [])]
    exclude_title_pats = [re.compile(p, re.IGNORECASE) for p in filters.get("exclude_title_patterns", [])]
    exclude_content_pats = [p.lower() for p in filters.get("exclude_content_patterns", [])]

    filtered = []
    for item in items:
        content = item.get("content", "")
        title = item.get("title", "")
        author = item.get("author", "").lower()

        # Length check
        if len(content) < min_len:
            continue
        if len(content) > max_len:
            continue

        # Author exclusion
        if author in exclude_authors:
            continue

        # Title pattern exclusion
        if any(pat.search(title) for pat in exclude_title_pats):
            continue

        # Content pattern exclusion
        content_lower = content.lower()
        if any(pat in content_lower for pat in exclude_content_pats):
            continue

        filtered.append(item)

    removed = len(items) - len(filtered)
    if removed > 0:
        logger.info(f"Filters removed {removed} items, {len(filtered)} remaining")

    return filtered


def run():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    raw_path = DATA_RAW_DIR / f"{today}.json"

    if not raw_path.exists():
        logger.error(f"No raw data found for {today} at {raw_path}")
        return

    with open(raw_path, encoding="utf-8") as f:
        raw_data = json.load(f)

    items = raw_data.get("items", [])
    logger.info(f"Loaded {len(items)} raw items for {today}")

    if not items:
        logger.info("No items to process")
        _save_empty(today, raw_data.get("metadata", {}))
        return

    # Step 1: Dedup
    items = dedup(items, today)

    # Step 2: Filter
    filters = _load_filters()
    items = _apply_filters(items, filters)

    # Step 3: Classify
    items = classify_batch(items)

    # Step 4: Score
    items = score_items(items)

    # Save processed data
    processed = {
        "metadata": {
            "date": today,
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "raw_count": raw_data.get("metadata", {}).get("total_items", 0),
            "processed_count": len(items),
            "platforms": raw_data.get("metadata", {}).get("platforms", {}),
        },
        "items": items,
    }

    DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    output_path = DATA_PROCESSED_DIR / f"{today}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(processed, f, ensure_ascii=False, indent=2)

    logger.info(f"Processed data saved to {output_path} ({len(items)} items)")


def _save_empty(today: str, metadata: dict):
    """Save an empty processed file when no data is available."""
    DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    processed = {
        "metadata": {
            "date": today,
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "raw_count": 0,
            "processed_count": 0,
            "platforms": metadata.get("platforms", {}),
        },
        "items": [],
    }
    output_path = DATA_PROCESSED_DIR / f"{today}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(processed, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    run()
