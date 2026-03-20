"""
Deduplication processor.
Removes duplicate items based on URL and content hash,
including cross-day dedup using memory/seen_urls.json.
"""

import json
from pathlib import Path

from ..utils.logger import get_logger

logger = get_logger("dedup")

BASE_DIR = Path(__file__).resolve().parent.parent.parent
MEMORY_DIR = BASE_DIR / "memory"
SEEN_FILE = MEMORY_DIR / "seen_urls.json"

# Keep 30 days of history
MAX_HISTORY_DAYS = 30


def _load_seen() -> dict:
    """Load seen URLs from memory file. Format: {url: date_first_seen}"""
    if SEEN_FILE.exists():
        try:
            with open(SEEN_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def _save_seen(seen: dict):
    """Save seen URLs to memory file."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)


def _prune_old_entries(seen: dict, current_date: str) -> dict:
    """Remove entries older than MAX_HISTORY_DAYS."""
    from datetime import datetime, timedelta
    try:
        cutoff = datetime.strptime(current_date, "%Y-%m-%d") - timedelta(days=MAX_HISTORY_DAYS)
        cutoff_str = cutoff.strftime("%Y-%m-%d")
        return {url: date for url, date in seen.items() if date >= cutoff_str}
    except ValueError:
        return seen


def dedup(items: list[dict], current_date: str) -> list[dict]:
    """
    Remove duplicates from items list.
    Uses both URL-based and content-hash-based dedup.
    Updates memory/seen_urls.json for cross-day dedup.
    """
    seen = _load_seen()
    seen = _prune_old_entries(seen, current_date)

    unique = []
    seen_in_batch = set()

    for item in items:
        url = item.get("url", "")
        content_hash = item.get("content_hash", "")

        # Skip if already seen in this batch
        dedup_key = url or content_hash
        if dedup_key in seen_in_batch:
            continue
        seen_in_batch.add(dedup_key)

        # Skip if seen in previous days
        if url and url in seen:
            continue
        if content_hash and content_hash in seen:
            continue

        unique.append(item)

        # Record as seen
        if url:
            seen[url] = current_date
        if content_hash:
            seen[content_hash] = current_date

    removed = len(items) - len(unique)
    if removed > 0:
        logger.info(f"Dedup removed {removed} duplicates, {len(unique)} remaining")

    _save_seen(seen)
    return unique
