"""
Reddit scraper using Reddit's OAuth2 API.
Searches target subreddits for OpenClaw-related content.
"""

import os
import json
import time
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

from ..utils.unified_schema import ScrapedItem, Metrics
from ..utils.logger import get_logger

logger = get_logger("reddit_scraper")

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = BASE_DIR / "config"


def _load_config():
    with open(CONFIG_DIR / "platforms.json") as f:
        platforms = json.load(f)
    with open(CONFIG_DIR / "keywords.json") as f:
        keywords = json.load(f)
    return platforms.get("reddit", {}), keywords


def _get_access_token() -> str:
    """Get Reddit OAuth2 access token using client credentials."""
    client_id = os.environ.get("REDDIT_CLIENT_ID")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise ValueError("REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET must be set")

    auth = requests.auth.HTTPBasicAuth(client_id, client_secret)
    headers = {"User-Agent": "openclaw-monitor/1.0"}
    data = {"grant_type": "client_credentials"}

    resp = requests.post(
        "https://www.reddit.com/api/v1/access_token",
        auth=auth,
        headers=headers,
        data=data,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _get_all_keywords(keywords_config: dict) -> list[str]:
    """Flatten all keyword groups into a single list."""
    all_kw = []
    for group in ["core", "usecase", "agent_tech", "comparison"]:
        all_kw.extend(keywords_config.get(group, []))
    return [kw.lower() for kw in all_kw]


def _matches_keywords(title: str, selftext: str, keywords: list[str]) -> list[str]:
    """Return list of matched keywords in the given text."""
    text = f"{title} {selftext}".lower()
    return [kw for kw in keywords if kw in text]


def _post_to_item(post: dict, subreddit: str, matched_kw: list[str]) -> ScrapedItem:
    """Convert a Reddit API post object to our unified ScrapedItem."""
    data = post.get("data", post)
    created_utc = data.get("created_utc", 0)
    created_dt = datetime.fromtimestamp(created_utc, tz=timezone.utc).isoformat()

    return ScrapedItem(
        id=f"reddit_{data.get('id', '')}",
        source="reddit",
        sub_source=f"r/{subreddit}",
        title=data.get("title", ""),
        content=data.get("selftext", "")[:2000] or data.get("title", ""),
        url=f"https://reddit.com{data.get('permalink', '')}",
        author=data.get("author", "[deleted]"),
        created_at=created_dt,
        lang="en",
        metrics=Metrics(
            upvotes=data.get("ups", 0),
            comments=data.get("num_comments", 0),
        ),
        keywords_matched=matched_kw,
    )


def scrape() -> list[ScrapedItem]:
    """Main entry point: scrape all configured subreddits and return items."""
    config, keywords_config = _load_config()
    if not config.get("enabled", False):
        logger.info("Reddit scraper is disabled, skipping")
        return []

    all_keywords = _get_all_keywords(keywords_config)
    exclude_patterns = [p.lower() for p in keywords_config.get("exclude_patterns", [])]
    lookback = timedelta(hours=config.get("lookback_hours", 24))
    cutoff = datetime.now(timezone.utc) - lookback
    max_per_sub = config.get("max_per_subreddit", 100)

    try:
        token = _get_access_token()
    except Exception as e:
        logger.error(f"Failed to get Reddit access token: {e}")
        return []

    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "openclaw-monitor/1.0",
    }

    items = []
    seen_ids = set()

    for sub_cfg in config.get("subreddits", []):
        sub_name = sub_cfg["name"]
        needs_filter = sub_cfg.get("keyword_filter", False)
        logger.info(f"Scraping r/{sub_name} (keyword_filter={needs_filter})")

        for sort in config.get("sort_modes", ["new", "hot"]):
            try:
                url = f"https://oauth.reddit.com/r/{sub_name}/{sort}"
                params = {"limit": min(max_per_sub, 100), "t": "day"}
                resp = requests.get(url, headers=headers, params=params, timeout=30)
                resp.raise_for_status()
                posts = resp.json().get("data", {}).get("children", [])
            except Exception as e:
                logger.warning(f"Failed to fetch r/{sub_name}/{sort}: {e}")
                continue

            for post in posts:
                data = post.get("data", {})
                post_id = data.get("id", "")

                # Skip duplicates
                if post_id in seen_ids:
                    continue
                seen_ids.add(post_id)

                # Skip old posts
                created_utc = data.get("created_utc", 0)
                created_dt = datetime.fromtimestamp(created_utc, tz=timezone.utc)
                if created_dt < cutoff:
                    continue

                title = data.get("title", "")
                selftext = data.get("selftext", "")

                # Skip excluded content
                combined = f"{title} {selftext}".lower()
                if any(pat in combined for pat in exclude_patterns):
                    continue

                # Keyword filtering for non-core subreddits
                if needs_filter:
                    matched = _matches_keywords(title, selftext, all_keywords)
                    if not matched:
                        continue
                else:
                    # Core subreddits: still tag keywords but don't filter
                    matched = _matches_keywords(title, selftext, all_keywords)
                    if not matched:
                        matched = ["openclaw"]  # default for core subreddits

                item = _post_to_item(post, sub_name, matched)
                items.append(item)

            # Rate limiting
            time.sleep(1)

    logger.info(f"Reddit scraper collected {len(items)} items")
    return items
