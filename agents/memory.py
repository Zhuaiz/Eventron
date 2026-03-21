"""Event-level memory — per-event interaction history and experience retrieval.

Each event accumulates interaction records with outcomes (success/failure,
tool calls, user feedback). Future interactions on similar events can
retrieve relevant past experiences to guide the agent.

Storage: JSON files under ``data/agent_memory/{event_id}/``.
No DB dependency — pure filesystem. Can migrate to PostgreSQL later.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

MEMORY_ROOT = Path("data/agent_memory")


@dataclass
class InteractionRecord:
    """A single agent interaction record for memory."""
    timestamp: float
    event_id: str
    plugin: str
    user_msg: str               # user's request (text only)
    agent_reply: str            # agent's response
    tool_calls: list[dict]      # tool call log
    reflection_score: float     # 0.0 ~ 1.0
    reflection_issues: list[str]
    user_feedback: int | None = None  # +1 / -1 / None
    event_context: dict = field(default_factory=dict)  # event metadata snapshot
    tags: list[str] = field(default_factory=list)  # extracted keywords


@dataclass
class EventMemory:
    """Accumulated memory for a single event."""
    event_id: str
    interactions: list[InteractionRecord] = field(default_factory=list)
    # Aggregated stats
    total_interactions: int = 0
    avg_score: float = 0.0
    positive_feedback: int = 0
    negative_feedback: int = 0
    # Learned preferences (extracted from successful interactions)
    preferences: dict[str, Any] = field(default_factory=dict)

    def add(self, record: InteractionRecord) -> None:
        """Add an interaction and update aggregated stats."""
        self.interactions.append(record)
        self.total_interactions = len(self.interactions)
        scores = [r.reflection_score for r in self.interactions]
        self.avg_score = sum(scores) / len(scores) if scores else 0.0
        self.positive_feedback = sum(
            1 for r in self.interactions if r.user_feedback == 1
        )
        self.negative_feedback = sum(
            1 for r in self.interactions if r.user_feedback == -1
        )


# ── Persistence ────────────────────────────────────────────────

def _event_memory_path(event_id: str) -> Path:
    """Get the memory file path for an event."""
    d = MEMORY_ROOT / event_id
    d.mkdir(parents=True, exist_ok=True)
    return d / "memory.json"


def load_event_memory(event_id: str) -> EventMemory:
    """Load event memory from disk. Returns empty if none exists."""
    p = _event_memory_path(event_id)
    if p.exists():
        try:
            data = json.loads(p.read_text())
            mem = EventMemory(event_id=event_id)
            for rec_data in data.get("interactions", []):
                rec = InteractionRecord(**rec_data)
                mem.interactions.append(rec)
            mem.total_interactions = len(mem.interactions)
            scores = [r.reflection_score for r in mem.interactions]
            mem.avg_score = (
                sum(scores) / len(scores) if scores else 0.0
            )
            mem.positive_feedback = data.get("positive_feedback", 0)
            mem.negative_feedback = data.get("negative_feedback", 0)
            mem.preferences = data.get("preferences", {})
            return mem
        except Exception:
            pass
    return EventMemory(event_id=event_id)


def save_event_memory(mem: EventMemory) -> None:
    """Persist event memory to disk."""
    p = _event_memory_path(mem.event_id)
    data = {
        "event_id": mem.event_id,
        "total_interactions": mem.total_interactions,
        "avg_score": mem.avg_score,
        "positive_feedback": mem.positive_feedback,
        "negative_feedback": mem.negative_feedback,
        "preferences": mem.preferences,
        "interactions": [asdict(r) for r in mem.interactions[-100:]],
    }
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def record_interaction(
    event_id: str,
    plugin: str,
    user_msg: str,
    agent_reply: str,
    tool_calls: list[dict],
    reflection_score: float,
    reflection_issues: list[str],
    event_context: dict | None = None,
) -> InteractionRecord:
    """Create and persist an interaction record."""
    record = InteractionRecord(
        timestamp=time.time(),
        event_id=event_id,
        plugin=plugin,
        user_msg=user_msg[:500],
        agent_reply=agent_reply[:500],
        tool_calls=tool_calls[:20],
        reflection_score=reflection_score,
        reflection_issues=reflection_issues,
        event_context=event_context or {},
        tags=_extract_tags(user_msg, plugin, tool_calls),
    )
    mem = load_event_memory(event_id)
    mem.add(record)
    save_event_memory(mem)
    return record


def record_user_feedback(
    event_id: str,
    feedback: int,
    interaction_index: int = -1,
) -> None:
    """Record user feedback (+1/-1) on the latest interaction."""
    mem = load_event_memory(event_id)
    if mem.interactions:
        idx = interaction_index if interaction_index >= 0 else -1
        if abs(idx) <= len(mem.interactions):
            mem.interactions[idx].user_feedback = feedback
            # Update counts
            mem.positive_feedback = sum(
                1 for r in mem.interactions if r.user_feedback == 1
            )
            mem.negative_feedback = sum(
                1 for r in mem.interactions if r.user_feedback == -1
            )
            save_event_memory(mem)


# ── Experience retrieval ───────────────────────────────────────

def get_relevant_experiences(
    event_id: str,
    plugin: str,
    user_msg: str,
    max_results: int = 3,
) -> list[dict[str, Any]]:
    """Retrieve relevant past experiences for context injection.

    Returns successful interactions from this event (or similar events)
    that are relevant to the current request.
    """
    mem = load_event_memory(event_id)
    if not mem.interactions:
        return []

    # Filter to same plugin, scored > 0.6, and not negatively rated
    candidates = [
        r for r in mem.interactions
        if r.plugin == plugin
        and r.reflection_score >= 0.6
        and r.user_feedback != -1
    ]

    # Sort by relevance: prefer recent + high-score + positive feedback
    def _relevance(r: InteractionRecord) -> float:
        recency = min(1.0, (time.time() - r.timestamp) / 86400)
        fb_bonus = 0.2 if r.user_feedback == 1 else 0.0
        return r.reflection_score + fb_bonus - recency * 0.1

    candidates.sort(key=_relevance, reverse=True)

    results = []
    for r in candidates[:max_results]:
        results.append({
            "user_msg": r.user_msg,
            "action_summary": _summarize_tools(r.tool_calls),
            "score": r.reflection_score,
            "feedback": r.user_feedback,
        })
    return results


def get_event_stats(event_id: str) -> dict[str, Any]:
    """Get aggregated stats for an event's agent interactions."""
    mem = load_event_memory(event_id)
    if not mem.interactions:
        return {"total": 0}

    plugin_counts: dict[str, int] = {}
    for r in mem.interactions:
        plugin_counts[r.plugin] = plugin_counts.get(r.plugin, 0) + 1

    return {
        "total": mem.total_interactions,
        "avg_score": round(mem.avg_score, 2),
        "positive_feedback": mem.positive_feedback,
        "negative_feedback": mem.negative_feedback,
        "plugins_used": plugin_counts,
        "preferences": mem.preferences,
    }


# ── Cross-event experience (find similar events) ──────────────

def find_similar_event_experiences(
    event_context: dict[str, Any],
    plugin: str,
    max_results: int = 3,
) -> list[dict[str, Any]]:
    """Search across all events for relevant experiences.

    Matches by: layout_type, attendee count range, plugin type.
    """
    if not MEMORY_ROOT.exists():
        return []

    layout = event_context.get("layout_type", "")
    att_count = event_context.get("attendee_count", 0)
    results: list[dict[str, Any]] = []

    for event_dir in MEMORY_ROOT.iterdir():
        if not event_dir.is_dir():
            continue
        mem = load_event_memory(event_dir.name)
        for r in mem.interactions:
            if r.plugin != plugin or r.reflection_score < 0.7:
                continue
            if r.user_feedback == -1:
                continue

            # Similarity scoring
            ctx = r.event_context
            sim = 0.0
            if ctx.get("layout_type") == layout:
                sim += 0.4
            ctx_count = ctx.get("attendee_count", 0)
            if ctx_count and att_count:
                ratio = min(ctx_count, att_count) / max(
                    ctx_count, att_count, 1
                )
                sim += ratio * 0.3
            if r.user_feedback == 1:
                sim += 0.3

            if sim >= 0.3:
                results.append({
                    "event_id": r.event_id,
                    "user_msg": r.user_msg,
                    "action_summary": _summarize_tools(r.tool_calls),
                    "score": r.reflection_score,
                    "similarity": round(sim, 2),
                    "context": ctx,
                })

    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:max_results]


# ── Helpers ────────────────────────────────────────────────────

def _extract_tags(
    user_msg: str, plugin: str, tool_calls: list[dict]
) -> list[str]:
    """Extract searchable tags from an interaction."""
    tags = [plugin]
    tool_names = {tc.get("tool_name", "") for tc in tool_calls}
    tags.extend(tool_names - {""})

    keywords = [
        "排座", "座位", "布局", "分区", "铭牌", "胸牌", "桌签",
        "签到", "导入", "Excel", "PDF", "模板", "zone",
    ]
    for kw in keywords:
        if kw.lower() in user_msg.lower():
            tags.append(kw)
    return list(set(tags))


def _summarize_tools(tool_calls: list[dict]) -> str:
    """Summarize tool calls into a brief string."""
    if not tool_calls:
        return "（无工具调用）"
    parts = []
    for tc in tool_calls[:5]:
        name = tc.get("tool_name", "?")
        status = "✓" if tc.get("status") == "success" else "✗"
        parts.append(f"{status}{name}")
    suffix = f" +{len(tool_calls) - 5}" if len(tool_calls) > 5 else ""
    return ", ".join(parts) + suffix
