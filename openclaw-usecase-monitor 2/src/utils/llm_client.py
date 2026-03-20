"""
MiniMax LLM API client wrapper.
Uses MiniMax's Anthropic-compatible API endpoint with the anthropic SDK.
Used for content classification, scoring, and report generation.

MiniMax API docs: https://platform.minimax.io/docs/api-reference/text-anthropic-api
Compatible endpoint: https://api.minimax.io/anthropic
"""

import os
import json
import re
from anthropic import Anthropic
from ..utils.logger import get_logger

logger = get_logger("llm_client")

# MiniMax Anthropic-compatible endpoint
DEFAULT_BASE_URL = "https://api.minimax.io/anthropic"
# China region alternative: "https://api.minimaxi.com/anthropic"

# Default model - MiniMax M2.5 (latest coding/agent model)
DEFAULT_MODEL = "MiniMax-M2.5"


def get_client() -> Anthropic:
    api_key = os.environ.get("MINIMAX_API_KEY")
    if not api_key:
        raise ValueError("MINIMAX_API_KEY environment variable is not set")

    base_url = os.environ.get("MINIMAX_BASE_URL", DEFAULT_BASE_URL)

    return Anthropic(
        api_key=api_key,
        base_url=base_url,
    )


def call_llm(
    prompt: str,
    system: str = "",
    model: str = "",
    max_tokens: int = 4096,
    temperature: float = 0.7,
) -> str:
    """Send a prompt to MiniMax and return the text response."""
    client = get_client()
    model = model or os.environ.get("LLM_MODEL", DEFAULT_MODEL)

    messages = [{"role": "user", "content": prompt}]
    kwargs = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
        "temperature": temperature,
    }
    if system:
        kwargs["system"] = system

    try:
        response = client.messages.create(**kwargs)
        text = response.content[0].text
        # MiniMax M2.x uses interleaved thinking with <think>...</think> tags
        # Strip thinking content from the output
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        return text
    except Exception as e:
        logger.error(f"MiniMax API call failed: {e}")
        raise


def call_llm_json(
    prompt: str,
    system: str = "",
    model: str = "",
    max_tokens: int = 4096,
) -> dict:
    """Send a prompt to MiniMax and parse the response as JSON."""
    if not system:
        system = "You must respond with valid JSON only. No markdown, no preamble, no explanation."
    else:
        system += "\n\nYou must respond with valid JSON only. No markdown, no preamble, no explanation."

    text = call_llm(prompt, system=system, model=model, max_tokens=max_tokens)

    # Strip potential markdown fences
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:])
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM response as JSON: {e}\nResponse: {text[:500]}")
        raise
