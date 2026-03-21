"""LLM output utilities — shared helpers for parsing LLM responses.

Pure functions. No DB, no HTTP, no state.
"""

from __future__ import annotations

import json
import re
from typing import Any


def extract_text_content(content: str | list[dict[str, Any]]) -> str:
    """Extract plain text from a HumanMessage content field.

    LangChain HumanMessage.content can be:
    - A plain string (normal text message)
    - A list of dicts (multimodal message with images + text)

    This helper always returns the text portion as a string.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        return "\n".join(parts) if parts else ""
    return str(content)


def extract_json(text: str) -> Any:
    """Robustly extract JSON from LLM response text.

    Handles:
    - Pure JSON
    - ```json ... ``` code blocks
    - ``` ... ``` code blocks (no language tag)
    - JSON embedded in prose (finds first { or [ and last } or ])
    - Multiple code blocks (tries each)

    Raises ValueError if no valid JSON found.
    """
    text = text.strip()

    # 1. Try direct parse (pure JSON)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Try extracting from markdown code blocks
    code_block_re = re.compile(r'```(?:json)?\s*\n?(.*?)\n?```', re.DOTALL)
    for m in code_block_re.finditer(text):
        block = m.group(1).strip()
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            continue

    # 3. Try finding JSON object/array in prose
    for start_char, end_char in [('{', '}'), ('[', ']')]:
        start = text.find(start_char)
        if start == -1:
            continue
        end = text.rfind(end_char)
        if end <= start:
            continue
        candidate = text[start:end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    raise ValueError(
        f"No valid JSON found in LLM response ({len(text)} chars)"
    )
