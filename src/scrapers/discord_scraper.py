"""
Discord scraper using Playwright browser automation.
Navigates to Discord channels and extracts recent messages.
"""

import os
import json
import random
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path

from ..utils.unified_schema import ScrapedItem, Metrics
from ..utils.logger import get_logger

logger = get_logger("discord_scraper")

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = BASE_DIR / "config"


def _load_config():
    with open(CONFIG_DIR / "platforms.json") as f:
        platforms = json.load(f)
    with open(CONFIG_DIR / "keywords.json") as f:
        keywords = json.load(f)
    return platforms.get("discord", {}), keywords


async def _scrape_async(config: dict, keywords_config: dict) -> list[ScrapedItem]:
    """Async Playwright scraping logic for Discord."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("Playwright not installed. Run: pip install playwright && playwright install chromium")
        return []

    items = []
    seen_ids = set()
    delay_range = config.get("request_delay_range", [2, 5])

    # Discord token/cookies from env
    discord_token = os.environ.get("DISCORD_TOKEN", "")
    if not discord_token:
        logger.warning("DISCORD_TOKEN not set, Discord scraping will likely fail (auth required)")

    all_keywords = []
    for group in ["core", "usecase", "agent_tech"]:
        all_keywords.extend([kw.lower() for kw in keywords_config.get(group, [])])

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
        )

        # Inject Discord token via localStorage
        page = await context.new_page()

        if discord_token:
            await page.goto("https://discord.com/login", wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)

            # Inject token
            await page.evaluate(f"""
                (token) => {{
                    // Set token in localStorage for Discord auth
                    window.localStorage.setItem('token', '"' + token + '"');
                }}
            """, discord_token)

            # Reload to apply auth
            await page.goto("https://discord.com/channels/@me", wait_until="networkidle", timeout=30000)
            await asyncio.sleep(3)

        for server_cfg in config.get("servers", []):
            server_name = server_cfg.get("name", "")
            channels = server_cfg.get("channels", [])

            for channel in channels:
                logger.info(f"Scraping Discord: {server_name} / #{channel}")

                try:
                    # Note: In practice, you'd need the channel URL/ID
                    # This is a template - actual channel navigation needs
                    # server-specific URLs like https://discord.com/channels/{server_id}/{channel_id}
                    # For now, log a placeholder
                    logger.info(
                        f"Discord channel scraping requires server/channel IDs. "
                        f"Configure actual URLs in platforms.json for {server_name}/#{channel}"
                    )

                    # Placeholder: extract messages from current page
                    messages = await page.evaluate("""
                        () => {
                            const msgEls = document.querySelectorAll('[class*="message-"]');
                            return Array.from(msgEls).slice(-50).map(msg => {
                                const contentEl = msg.querySelector('[class*="messageContent-"]');
                                const authorEl = msg.querySelector('[class*="username-"]');
                                const timeEl = msg.querySelector('time');
                                const reactionEls = msg.querySelectorAll('[class*="reaction-"]');

                                return {
                                    text: contentEl ? contentEl.textContent : '',
                                    author: authorEl ? authorEl.textContent : '',
                                    time: timeEl ? timeEl.getAttribute('datetime') : '',
                                    reactions: reactionEls ? reactionEls.length : 0,
                                    id: msg.id || ''
                                };
                            });
                        }
                    """)

                    for msg in messages:
                        if not msg.get("text"):
                            continue

                        msg_id = msg.get("id", "")
                        if msg_id in seen_ids:
                            continue
                        seen_ids.add(msg_id)

                        # Keyword matching
                        text_lower = msg["text"].lower()
                        matched = [kw for kw in all_keywords if kw in text_lower]
                        if not matched:
                            continue

                        item = ScrapedItem(
                            id=f"discord_{msg_id}",
                            source="discord",
                            sub_source=f"{server_name}/#{channel}",
                            title=msg["text"][:120],
                            content=msg["text"],
                            url=f"https://discord.com/channels/{server_name}/{channel}",
                            author=msg.get("author", ""),
                            created_at=msg.get("time", ""),
                            metrics=Metrics(
                                reactions=msg.get("reactions", 0),
                            ),
                            keywords_matched=matched,
                        )
                        items.append(item)

                except Exception as e:
                    logger.warning(f"Failed to scrape Discord {server_name}/#{channel}: {e}")

                await asyncio.sleep(random.uniform(*delay_range))

        await browser.close()

    logger.info(f"Discord scraper collected {len(items)} items")
    return items


def scrape() -> list[ScrapedItem]:
    """Main entry point: scrape Discord using Playwright."""
    config, keywords_config = _load_config()
    if not config.get("enabled", False):
        logger.info("Discord scraper is disabled, skipping")
        return []

    return asyncio.run(_scrape_async(config, keywords_config))
