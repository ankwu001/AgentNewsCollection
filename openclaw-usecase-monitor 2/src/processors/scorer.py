"""
Value scorer.
Uses Claude to score items on three dimensions:
- Community heat (30%): based on engagement metrics
- Technical innovation (40%): novelty of approach
- Practicality (30%): real-world applicability
"""

import json
import math

from ..utils.llm_client import call_llm_json
from ..utils.logger import get_logger

logger = get_logger("scorer")

WEIGHTS = {
    "heat": 0.30,
    "innovation": 0.40,
    "practicality": 0.30,
}


def _compute_heat_score(item: dict, all_items: list[dict]) -> float:
    """
    Compute heat score based on engagement metrics.
    Uses percentile ranking within the day's dataset to normalize across platforms.
    """
    metrics = item.get("metrics", {})
    source = item.get("source", "")

    # Collect comparable metrics from same platform
    same_platform = [i for i in all_items if i.get("source") == source]
    if not same_platform:
        return 2.5  # neutral default

    # Platform-specific engagement metric
    if source == "reddit":
        val = (metrics.get("upvotes") or 0) + (metrics.get("comments") or 0) * 2
        all_vals = [
            (i.get("metrics", {}).get("upvotes") or 0)
            + (i.get("metrics", {}).get("comments") or 0) * 2
            for i in same_platform
        ]
    elif source == "github":
        val = (metrics.get("stars") or 0) * 2 + (metrics.get("forks") or 0) + (metrics.get("comments") or 0)
        all_vals = [
            (i.get("metrics", {}).get("stars") or 0) * 2
            + (i.get("metrics", {}).get("forks") or 0)
            + (i.get("metrics", {}).get("comments") or 0)
            for i in same_platform
        ]
    elif source == "x":
        val = (metrics.get("likes") or 0) + (metrics.get("retweets") or 0) * 3 + (metrics.get("comments") or 0) * 2
        all_vals = [
            (i.get("metrics", {}).get("likes") or 0)
            + (i.get("metrics", {}).get("retweets") or 0) * 3
            + (i.get("metrics", {}).get("comments") or 0) * 2
            for i in same_platform
        ]
    elif source == "discord":
        val = (metrics.get("reactions") or 0) + 1
        all_vals = [(i.get("metrics", {}).get("reactions") or 0) + 1 for i in same_platform]
    else:
        return 2.5

    # Percentile ranking → 1-5 score
    if len(all_vals) <= 1:
        return 3.0
    sorted_vals = sorted(all_vals)
    rank = sorted_vals.index(val) if val in sorted_vals else 0
    percentile = rank / (len(sorted_vals) - 1)
    return round(1 + percentile * 4, 1)


def _score_with_llm(items: list[dict]) -> list[dict]:
    """
    Use Claude to score items on innovation and practicality.
    Processes in batches for efficiency.
    """
    batch_size = 10
    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        summaries = []
        for idx, item in enumerate(batch):
            summaries.append({
                "idx": idx,
                "title": item.get("title", "")[:200],
                "content": item.get("content", "")[:500],
                "category": item.get("category", "other"),
                "source": item.get("source", ""),
            })

        prompt = f"""Score each item on two dimensions (1-5 scale, can use decimals like 3.5):

1. **innovation** (技术创新性): Is this a novel approach, creative use of OpenClaw, or interesting technical combination? 
   - 1 = basic/common usage, 5 = highly creative and novel
2. **practicality** (实用性): Is this reproducible? Does it solve a real problem? Does it have broad applicability?
   - 1 = toy example only, 5 = immediately applicable to real workflows

Items:
{json.dumps(summaries, ensure_ascii=False)}

Return a JSON array:
[{{"idx": 0, "innovation": 3.5, "practicality": 4.0, "reason": "一句话理由"}}, ...]"""

        try:
            result = call_llm_json(prompt)
            if isinstance(result, list):
                score_map = {r["idx"]: r for r in result if "idx" in r}
                for idx, item in enumerate(batch):
                    scores = score_map.get(idx, {})
                    item["score_breakdown"] = {
                        "innovation": scores.get("innovation", 2.5),
                        "practicality": scores.get("practicality", 2.5),
                        "reason": scores.get("reason", ""),
                    }
        except Exception as e:
            logger.warning(f"LLM scoring failed for batch {i}: {e}")
            for item in batch:
                item["score_breakdown"] = {
                    "innovation": 2.5,
                    "practicality": 2.5,
                    "reason": "LLM scoring unavailable",
                }

    return items


def score_items(items: list[dict]) -> list[dict]:
    """
    Score all items and compute weighted total.
    """
    if not items:
        return items

    # Step 1: Compute heat scores (metric-based, no LLM needed)
    for item in items:
        heat = _compute_heat_score(item, items)
        if "score_breakdown" not in item:
            item["score_breakdown"] = {}
        item["score_breakdown"]["heat"] = heat

    # Step 2: LLM-based innovation + practicality scores
    items = _score_with_llm(items)

    # Step 3: Compute weighted total
    for item in items:
        bd = item.get("score_breakdown", {})
        total = (
            bd.get("heat", 2.5) * WEIGHTS["heat"]
            + bd.get("innovation", 2.5) * WEIGHTS["innovation"]
            + bd.get("practicality", 2.5) * WEIGHTS["practicality"]
        )
        item["score"] = round(total, 2)

    # Sort by score descending
    items.sort(key=lambda x: x.get("score", 0), reverse=True)

    logger.info(f"Scored {len(items)} items. Top score: {items[0]['score'] if items else 'N/A'}")
    return items
