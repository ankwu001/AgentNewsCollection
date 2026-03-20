"""
Report generator.
Reads processed data, loads prompt template, calls Claude to generate
the daily Markdown report, and updates latest.md + index.json.
Usage: python -m src.report_generator
"""

import json
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .utils.llm_client import call_llm
from .utils.logger import get_logger

logger = get_logger("report_generator")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_PROCESSED_DIR = BASE_DIR / "data" / "processed"
PROMPTS_DIR = BASE_DIR / "prompts"
OUTPUTS_DIR = BASE_DIR / "outputs" / "daily-report"


def _load_processed_data(date: str) -> dict:
    path = DATA_PROCESSED_DIR / f"{date}.json"
    if not path.exists():
        logger.error(f"No processed data found for {date}")
        return {"metadata": {"date": date, "processed_count": 0}, "items": []}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _load_prompt_template() -> str:
    path = PROMPTS_DIR / "report_generation.md"
    with open(path, encoding="utf-8") as f:
        return f.read()


def _load_trend_summary(current_date: str) -> str:
    """Load past 7 days of processed data summaries for trend analysis."""
    trend_data = []
    try:
        base_date = datetime.strptime(current_date, "%Y-%m-%d")
    except ValueError:
        return "{}"

    for i in range(1, 8):  # past 7 days
        prev_date = (base_date - timedelta(days=i)).strftime("%Y-%m-%d")
        prev_path = DATA_PROCESSED_DIR / f"{prev_date}.json"
        if prev_path.exists():
            try:
                with open(prev_path, encoding="utf-8") as f:
                    data = json.load(f)
                # Extract summary only (not full items)
                meta = data.get("metadata", {})
                items = data.get("items", [])
                categories = {}
                keywords_freq = {}
                for item in items:
                    cat = item.get("category", "other")
                    categories[cat] = categories.get(cat, 0) + 1
                    for kw in item.get("keywords_matched", []):
                        keywords_freq[kw] = keywords_freq.get(kw, 0) + 1

                trend_data.append({
                    "date": prev_date,
                    "total": meta.get("processed_count", 0),
                    "platforms": meta.get("platforms", {}),
                    "top_categories": dict(sorted(categories.items(), key=lambda x: -x[1])[:5]),
                    "top_keywords": dict(sorted(keywords_freq.items(), key=lambda x: -x[1])[:10]),
                })
            except (json.JSONDecodeError, IOError):
                continue

    return json.dumps(trend_data, ensure_ascii=False, indent=2) if trend_data else "{}"


def _update_latest(date: str):
    """Copy today's report to latest.md."""
    report_path = OUTPUTS_DIR / f"{date}.md"
    latest_path = OUTPUTS_DIR / "latest.md"
    if report_path.exists():
        shutil.copy2(report_path, latest_path)
        logger.info(f"Updated latest.md → {date}")


def _update_index(date: str, metadata: dict):
    """Update the index.json file with today's report metadata."""
    index_path = OUTPUTS_DIR / "index.json"

    # Load existing index
    index = {"latest": date, "reports": []}
    if index_path.exists():
        try:
            with open(index_path, encoding="utf-8") as f:
                index = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    # Remove existing entry for today (if re-running)
    index["reports"] = [r for r in index.get("reports", []) if r.get("date") != date]

    # Determine top category
    items = metadata.get("items", [])
    cat_counts = {}
    for item in items:
        cat = item.get("category", "other")
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
    top_cat = max(cat_counts, key=cat_counts.get) if cat_counts else "none"

    # Add today's entry
    index["latest"] = date
    index["reports"].insert(0, {
        "date": date,
        "file": f"{date}.md",
        "total_items": metadata.get("metadata", {}).get("raw_count", 0),
        "valid_items": metadata.get("metadata", {}).get("processed_count", 0),
        "top_category": top_cat,
    })

    # Keep last 90 days
    index["reports"] = index["reports"][:90]

    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    logger.info(f"Updated index.json (total {len(index['reports'])} reports)")


def generate():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    logger.info(f"Generating report for {today}")

    # Load data
    processed = _load_processed_data(today)
    prompt_template = _load_prompt_template()
    trend_summary = _load_trend_summary(today)

    # Build prompt
    # Only send top 20 items to keep prompt manageable
    items_for_prompt = processed.get("items", [])[:20]
    prompt_data = {
        "metadata": processed.get("metadata", {}),
        "items": items_for_prompt,
    }

    prompt = prompt_template.replace(
        "{processed_data}", json.dumps(prompt_data, ensure_ascii=False, indent=2)
    ).replace(
        "{trend_summary}", trend_summary
    )

    # Call Claude
    system = (
        "你是 OpenClaw 生态的技术分析师。输出高质量中文分析报告，结论先行，bullet-point 格式。"
        "直接输出 Markdown，不要加任何包裹标记。"
    )

    try:
        report = call_llm(prompt, system=system, max_tokens=8192, temperature=0.7)
    except Exception as e:
        logger.error(f"Report generation failed: {e}")
        report = _generate_fallback_report(today, processed)

    # Save report
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUTS_DIR / f"{today}.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    logger.info(f"Report saved to {report_path}")

    # Update latest.md and index.json
    _update_latest(today)
    _update_index(today, processed)

    return report_path


def _generate_fallback_report(date: str, processed: dict) -> str:
    """Generate a minimal report when LLM is unavailable."""
    meta = processed.get("metadata", {})
    items = processed.get("items", [])
    top5 = items[:5]

    lines = [
        f"# OpenClaw Use Case Daily Report — {date}",
        "",
        "> **今日概览**",
        f"> - 共抓取 {meta.get('raw_count', 0)} 条内容，筛选出 {meta.get('processed_count', 0)} 条有效 use case",
        f"> - ⚠️ LLM 报告生成失败，以下为自动汇总",
        "",
        "---",
        "",
        "## Top Use Cases（按评分排序）",
        "",
    ]

    for i, item in enumerate(top5, 1):
        bd = item.get("score_breakdown", {})
        lines.extend([
            f"### {i}. {item.get('title', 'Untitled')[:100]}",
            "",
            f"- **来源**：{item.get('source', '')} {item.get('sub_source', '')}",
            f"- **链接**：[原文]({item.get('url', '')})",
            f"- **分类**：{item.get('category', 'other')}",
            f"- **综合评分**：{item.get('score', 0)}/5.0（热度 {bd.get('heat', '-')} / 创新 {bd.get('innovation', '-')} / 实用 {bd.get('practicality', '-')}）",
            f"- **内容**：{item.get('content', '')[:200]}",
            "",
        ])

    return "\n".join(lines)


if __name__ == "__main__":
    generate()
