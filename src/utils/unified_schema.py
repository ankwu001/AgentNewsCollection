"""
Unified data schema for all scraped items.
Every scraper must output items conforming to this schema.
"""

import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Metrics:
    upvotes: Optional[int] = None
    comments: Optional[int] = None
    stars: Optional[int] = None
    forks: Optional[int] = None
    retweets: Optional[int] = None
    likes: Optional[int] = None
    reactions: Optional[int] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items()}


@dataclass
class ScrapedItem:
    id: str
    source: str                     # reddit | github | x | discord
    sub_source: str                 # e.g. r/openclaw, owner/repo, channel name
    title: str
    content: str
    url: str
    author: str
    created_at: str                 # ISO 8601
    scraped_at: str = ""            # ISO 8601, auto-filled
    lang: str = "en"
    metrics: Metrics = field(default_factory=Metrics)
    keywords_matched: list = field(default_factory=list)
    content_hash: str = ""
    category: str = ""              # filled by classifier
    score: float = 0.0              # filled by scorer
    score_breakdown: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.scraped_at:
            self.scraped_at = datetime.now(timezone.utc).isoformat()
        if not self.content_hash:
            self.content_hash = self._compute_hash()
        # Truncate content to 500 chars for storage efficiency
        if len(self.content) > 2000:
            self.content = self.content[:2000] + "..."

    def _compute_hash(self) -> str:
        text = f"{self.url}|{self.title}|{self.content[:500]}"
        return f"sha256:{hashlib.sha256(text.encode()).hexdigest()[:16]}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["metrics"] = self.metrics.to_dict()
        return d


@dataclass
class DailyData:
    date: str
    scrape_time: str
    total_items: int = 0
    platforms: dict = field(default_factory=dict)
    items: list = field(default_factory=list)

    def add_item(self, item: ScrapedItem):
        self.items.append(item)
        self.total_items = len(self.items)
        src = item.source
        self.platforms[src] = self.platforms.get(src, 0) + 1

    def to_dict(self) -> dict:
        return {
            "metadata": {
                "date": self.date,
                "scrape_time": self.scrape_time,
                "total_items": self.total_items,
                "platforms": self.platforms,
            },
            "items": [item.to_dict() for item in self.items],
        }


def validate_item(data: dict) -> bool:
    """Validate that a dict has all required fields for a ScrapedItem."""
    required = ["id", "source", "sub_source", "title", "content", "url", "author", "created_at"]
    return all(k in data and data[k] for k in required)
