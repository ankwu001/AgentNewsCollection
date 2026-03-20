"""
GitHub scraper using GitHub Search API.
Searches for OpenClaw-related repos, issues, and discussions.
"""

import os
import json
import time
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

from ..utils.unified_schema import ScrapedItem, Metrics
from ..utils.logger import get_logger

logger = get_logger("github_scraper")

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = BASE_DIR / "config"

API_BASE = "https://api.github.com"


def _load_config():
    with open(CONFIG_DIR / "platforms.json") as f:
        platforms = json.load(f)
    with open(CONFIG_DIR / "keywords.json") as f:
        keywords = json.load(f)
    return platforms.get("github", {}), keywords


def _get_headers() -> dict:
    token = os.environ.get("GH_PAT") or os.environ.get("GITHUB_TOKEN")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "openclaw-monitor/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _get_search_keywords(keywords_config: dict) -> list[str]:
    """Build search query strings from keyword groups."""
    queries = []
    for kw in keywords_config.get("core", []):
        queries.append(kw)
    for kw in keywords_config.get("agent_tech", []):
        queries.append(kw)
    return queries


def _search_repos(headers: dict, query: str, since: str, max_results: int) -> list[ScrapedItem]:
    """Search GitHub repos matching the query."""
    items = []
    search_q = f"{query} created:>{since}"
    params = {"q": search_q, "sort": "updated", "order": "desc", "per_page": min(max_results, 30)}

    try:
        resp = requests.get(f"{API_BASE}/search/repositories", headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"GitHub repo search failed for '{query}': {e}")
        return items

    for repo in data.get("items", [])[:max_results]:
        item = ScrapedItem(
            id=f"github_repo_{repo['id']}",
            source="github",
            sub_source=repo.get("full_name", ""),
            title=repo.get("full_name", ""),
            content=repo.get("description", "") or "",
            url=repo.get("html_url", ""),
            author=repo.get("owner", {}).get("login", ""),
            created_at=repo.get("created_at", ""),
            lang=repo.get("language", "") or "unknown",
            metrics=Metrics(
                stars=repo.get("stargazers_count", 0),
                forks=repo.get("forks_count", 0),
            ),
            keywords_matched=[query],
        )
        items.append(item)

    return items


def _search_issues(headers: dict, query: str, since: str, max_results: int) -> list[ScrapedItem]:
    """Search GitHub issues and PRs matching the query."""
    items = []
    search_q = f"{query} created:>{since}"
    params = {"q": search_q, "sort": "created", "order": "desc", "per_page": min(max_results, 30)}

    try:
        resp = requests.get(f"{API_BASE}/search/issues", headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"GitHub issue search failed for '{query}': {e}")
        return items

    for issue in data.get("items", [])[:max_results]:
        # Extract repo name from URL
        repo_url = issue.get("repository_url", "")
        repo_name = "/".join(repo_url.split("/")[-2:]) if repo_url else ""

        item = ScrapedItem(
            id=f"github_issue_{issue['id']}",
            source="github",
            sub_source=repo_name,
            title=issue.get("title", ""),
            content=issue.get("body", "")[:2000] if issue.get("body") else "",
            url=issue.get("html_url", ""),
            author=issue.get("user", {}).get("login", ""),
            created_at=issue.get("created_at", ""),
            metrics=Metrics(
                comments=issue.get("comments", 0),
                reactions=issue.get("reactions", {}).get("total_count", 0) if isinstance(issue.get("reactions"), dict) else 0,
            ),
            keywords_matched=[query],
        )
        items.append(item)

    return items


def _check_official_repos(headers: dict, repos: list[str], since: str) -> list[ScrapedItem]:
    """Check official repos for new releases and notable issues."""
    items = []
    for repo in repos:
        # Check releases
        try:
            resp = requests.get(f"{API_BASE}/repos/{repo}/releases", headers=headers, params={"per_page": 5}, timeout=30)
            if resp.status_code == 200:
                for release in resp.json():
                    pub = release.get("published_at", "")
                    if pub and pub > since:
                        item = ScrapedItem(
                            id=f"github_release_{release['id']}",
                            source="github",
                            sub_source=repo,
                            title=f"[Release] {release.get('name', release.get('tag_name', ''))}",
                            content=release.get("body", "")[:2000] if release.get("body") else "",
                            url=release.get("html_url", ""),
                            author=release.get("author", {}).get("login", ""),
                            created_at=pub,
                            keywords_matched=["openclaw", "product-update"],
                        )
                        items.append(item)
        except Exception as e:
            logger.warning(f"Failed to check releases for {repo}: {e}")

        time.sleep(0.5)

    return items


def scrape() -> list[ScrapedItem]:
    """Main entry point: search GitHub for OpenClaw-related content."""
    config, keywords_config = _load_config()
    if not config.get("enabled", False):
        logger.info("GitHub scraper is disabled, skipping")
        return []

    headers = _get_headers()
    lookback = timedelta(hours=config.get("lookback_hours", 24))
    since = (datetime.now(timezone.utc) - lookback).strftime("%Y-%m-%dT%H:%M:%SZ")
    since_date = (datetime.now(timezone.utc) - lookback).strftime("%Y-%m-%d")
    max_results = config.get("max_results_per_query", 50)

    all_items = []
    seen_ids = set()
    search_keywords = _get_search_keywords(keywords_config)

    for query in search_keywords:
        targets = config.get("search_targets", ["repositories", "issues"])

        if "repositories" in targets:
            for item in _search_repos(headers, query, since_date, max_results):
                if item.id not in seen_ids:
                    seen_ids.add(item.id)
                    all_items.append(item)
            time.sleep(2)  # respect rate limits

        if "issues" in targets or "discussions" in targets:
            for item in _search_issues(headers, query, since, max_results):
                if item.id not in seen_ids:
                    seen_ids.add(item.id)
                    all_items.append(item)
            time.sleep(2)

    # Check official repos
    official = config.get("official_repos", [])
    if official:
        for item in _check_official_repos(headers, official, since):
            if item.id not in seen_ids:
                seen_ids.add(item.id)
                all_items.append(item)

    logger.info(f"GitHub scraper collected {len(all_items)} items")
    return all_items
