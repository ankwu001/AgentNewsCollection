"""
X/Twitter scraper using Playwright browser automation.
Searches X for OpenClaw-related tweets without requiring API access.
"""

import os
import json
import random
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path

from ..utils.unified_schema import ScrapedItem, Metrics
from ..utils.logger import get_logger

logger = get_logger("x_scraper")

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = BASE_DIR / "config"


def _load_config():
    with open(CONFIG_DIR / "platforms.json") as f:
        platforms = json.load(f)
    with open(CONFIG_DIR / "keywords.json") as f:
        keywords = json.load(f)
    return platforms.get("x", {}), keywords


def _build_search_queries(keywords_config: dict, keyword_groups: list[str]) -> list[str]:
    """Build X search query strings from configured keyword groups."""
    queries = []
    for group in keyword_groups:
        for kw in keywords_config.get(group, []):
            queries.append(kw)
    return queries


async def _scrape_async(config: dict, keywords_config: dict) -> list[ScrapedItem]:
    """Async Playwright scraping logic."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("Playwright not installed. Run: pip install playwright && playwright install chromium")
        return []

    items = []
    seen_ids = set()
    keyword_groups = config.get("keyword_groups", ["core", "usecase"])
    queries = _build_search_queries(keywords_config, keyword_groups)
    delay_range = config.get("request_delay_range", [2, 5])
    max_results = config.get("max_results", 50)

    # Load cookies from env
    cookies_json = os.environ.get("X_COOKIES", "")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )

        # Load cookies if available
        if cookies_json:
            try:
                cookies = json.loads(cookies_json)
                await context.add_cookies(cookies)
                logger.info("Loaded X cookies from environment")
            except json.JSONDecodeError:
                logger.warning("Failed to parse X_COOKIES, proceeding without auth")

        page = await context.new_page()

        for query in queries[:10]:  # Limit to 10 query variations
            if len(items) >= max_results:
                break

            search_url = f"https://x.com/search?q={query}&src=typed_query&f=live"
            logger.info(f"Searching X for: {query}")

            try:
                await page.goto(search_url, wait_until="networkidle", timeout=30000)
                await asyncio.sleep(random.uniform(*delay_range))

                # Scroll to load more results
                for _ in range(3):
                    await page.evaluate("window.scrollBy(0, window.innerHeight)")
                    await asyncio.sleep(random.uniform(1, 2))

                # Extract tweet data from the page
                tweets = await page.evaluate("""
                    () => {
                        const articles = document.querySelectorAll('article[data-testid="tweet"]');
                        return Array.from(articles).map(article => {
                            const textEl = article.querySelector('[data-testid="tweetText"]');
                            const userEl = article.querySelector('[data-testid="User-Name"]');
                            const timeEl = article.querySelector('time');
                            const linkEl = article.querySelector('a[href*="/status/"]');

                            // Extract metrics
                            const metricEls = article.querySelectorAll('[data-testid$="-count"]');
                            const metrics = {};
                            metricEls.forEach(el => {
                                const testId = el.getAttribute('data-testid') || '';
                                const val = parseInt(el.textContent.replace(/[^0-9]/g, '')) || 0;
                                if (testId.includes('reply')) metrics.comments = val;
                                if (testId.includes('retweet')) metrics.retweets = val;
                                if (testId.includes('like')) metrics.likes = val;
                            });

                            return {
                                text: textEl ? textEl.textContent : '',
                                author: userEl ? userEl.textContent.split('@').pop()?.split('·')[0]?.trim() : '',
                                time: timeEl ? timeEl.getAttribute('datetime') : '',
                                url: linkEl ? linkEl.href : '',
                                metrics: metrics
                            };
                        });
                    }
                """)

                for tweet in tweets:
                    if not tweet.get("text") or not tweet.get("url"):
                        continue

                    # Extract tweet ID from URL
                    url = tweet["url"]
                    tweet_id = url.split("/status/")[-1].split("?")[0] if "/status/" in url else ""
                    if not tweet_id or tweet_id in seen_ids:
                        continue
                    seen_ids.add(tweet_id)

                    item = ScrapedItem(
                        id=f"x_{tweet_id}",
                        source="x",
                        sub_source="x.com/search",
                        title=tweet["text"][:120],
                        content=tweet["text"],
                        url=url,
                        author=tweet.get("author", ""),
                        created_at=tweet.get("time", ""),
                        metrics=Metrics(
                            comments=tweet.get("metrics", {}).get("comments", 0),
                            retweets=tweet.get("metrics", {}).get("retweets", 0),
                            likes=tweet.get("metrics", {}).get("likes", 0),
                        ),
                        keywords_matched=[query],
                    )
                    items.append(item)

            except Exception as e:
                logger.warning(f"Failed to scrape X for '{query}': {e}")

            await asyncio.sleep(random.uniform(*delay_range))

        await browser.close()

    logger.info(f"X scraper collected {len(items)} items")
    return items


def scrape() -> list[ScrapedItem]:
    """Main entry point: scrape X/Twitter using Playwright."""
    config, keywords_config = _load_config()
    if not config.get("enabled", False):
        logger.info("X scraper is disabled, skipping")
        return []

    return asyncio.run(_scrape_async(config, keywords_config))
