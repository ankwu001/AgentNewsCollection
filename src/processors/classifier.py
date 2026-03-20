"""
Content classifier.
Uses Claude to categorize items into predefined use case types.
Falls back to keyword-based classification if LLM is unavailable.
"""

import json

from ..utils.llm_client import call_llm_json
from ..utils.logger import get_logger

logger = get_logger("classifier")

CATEGORIES = [
    "ai-coding",
    "agent-workflow",
    "mcp-integration",
    "content-generation",
    "data-analysis",
    "devtools",
    "product-update",
    "ecosystem",
    "comparison",
    "other",
]

# Simple keyword-based fallback mapping
KEYWORD_CATEGORY_MAP = {
    "ai-coding": ["coding", "code", "programming", "developer", "IDE", "vscode", "编程", "写代码"],
    "agent-workflow": ["agent", "workflow", "automation", "自动化", "工作流"],
    "mcp-integration": ["mcp", "server", "integration", "plugin"],
    "content-generation": ["content", "writing", "blog", "文案", "生成"],
    "data-analysis": ["data", "analysis", "csv", "chart", "数据", "分析"],
    "devtools": ["tool", "extension", "plugin", "cli", "sdk", "工具"],
    "product-update": ["release", "update", "version", "changelog", "发布", "更新"],
    "ecosystem": ["tutorial", "course", "guide", "community", "教程", "社区"],
    "comparison": ["vs", "versus", "compare", "alternative", "对比", "替代"],
}


def _classify_by_keywords(title: str, content: str) -> str:
    """Fallback: classify using simple keyword matching."""
    text = f"{title} {content}".lower()
    scores = {}
    for cat, keywords in KEYWORD_CATEGORY_MAP.items():
        scores[cat] = sum(1 for kw in keywords if kw.lower() in text)
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "other"


def classify_batch(items: list[dict]) -> list[dict]:
    """
    Classify a batch of items using Claude.
    Falls back to keyword-based classification on failure.
    """
    if not items:
        return items

    # Batch classify with LLM (up to 20 at a time to manage token usage)
    batch_size = 20
    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        summaries = []
        for idx, item in enumerate(batch):
            summaries.append({
                "idx": idx,
                "title": item.get("title", "")[:200],
                "content": item.get("content", "")[:300],
                "source": item.get("source", ""),
            })

        prompt = f"""Classify each item into exactly ONE category from this list:
{json.dumps(CATEGORIES)}

Items to classify:
{json.dumps(summaries, ensure_ascii=False)}

Return a JSON array of objects with "idx" and "category" fields.
Example: [{{"idx": 0, "category": "ai-coding"}}, {{"idx": 1, "category": "agent-workflow"}}]"""

        try:
            result = call_llm_json(prompt)
            if isinstance(result, list):
                cat_map = {r["idx"]: r["category"] for r in result if "idx" in r and "category" in r}
                for idx, item in enumerate(batch):
                    cat = cat_map.get(idx, "")
                    item["category"] = cat if cat in CATEGORIES else _classify_by_keywords(
                        item.get("title", ""), item.get("content", "")
                    )
            else:
                raise ValueError("Unexpected response format")
        except Exception as e:
            logger.warning(f"LLM classification failed, falling back to keywords: {e}")
            for item in batch:
                item["category"] = _classify_by_keywords(
                    item.get("title", ""), item.get("content", "")
                )

    classified_counts = {}
    for item in items:
        cat = item.get("category", "other")
        classified_counts[cat] = classified_counts.get(cat, 0) + 1
    logger.info(f"Classification results: {classified_counts}")

    return items
