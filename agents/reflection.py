"""Reflection layer — post-action self-checking and auto-repair.

After each plugin execution, the reflection layer:
1. Validates the result against domain-specific rules
2. Scores the quality of the interaction
3. Auto-retries with corrective hints if validation fails

This is the "self-check" part of the self-evolution system.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from agents.llm_utils import extract_json, extract_text_content


@dataclass
class ReflectionResult:
    """Result of a reflection check on a plugin's output."""
    passed: bool
    score: float          # 0.0 ~ 1.0
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


# ── Domain-specific validators ─────────────────────────────────

async def validate_seating_result(
    event_id: str | None,
    reply: str,
    tool_calls: list[dict],
    services: dict[str, Any],
) -> ReflectionResult:
    """Validate seating plugin results.

    Checks:
    - Seats were actually created (not just described)
    - No orphaned attendees (assigned to non-existent seats)
    - Seat utilization rate is reasonable
    - All zones have at least one seat assigned
    """
    issues: list[str] = []
    suggestions: list[str] = []
    metrics: dict[str, Any] = {}
    score = 1.0

    if not event_id:
        return ReflectionResult(
            passed=True, score=0.5,
            issues=["无活动上下文，跳过座位验证"],
        )

    import uuid
    seat_svc = services.get("seating")
    att_svc = services.get("attendee")

    if seat_svc and att_svc:
        try:
            eid = uuid.UUID(event_id)
            seats = await seat_svc.get_seats(eid)
            attendees = await att_svc.list_attendees_for_event(eid)
            active_att = [
                a for a in attendees if a.status != "cancelled"
            ]

            normal_seats = [
                s for s in seats
                if s.seat_type not in ("disabled", "aisle")
            ]
            assigned = [s for s in normal_seats if s.attendee_id]

            metrics["total_seats"] = len(normal_seats)
            metrics["assigned_seats"] = len(assigned)
            metrics["total_attendees"] = len(active_att)

            if normal_seats:
                util_rate = len(assigned) / len(normal_seats)
                metrics["utilization_rate"] = round(util_rate, 2)

                if util_rate < 0.3 and len(active_att) > 5:
                    issues.append(
                        f"座位利用率仅 {util_rate:.0%}，"
                        f"{len(normal_seats)} 个座位只分配了 "
                        f"{len(assigned)} 个"
                    )
                    suggestions.append("建议运行 auto_assign 自动排座")
                    score -= 0.3

            # Check for attendees without seats
            seated_ids = {s.attendee_id for s in assigned}
            unseated = [
                a for a in active_att if a.id not in seated_ids
            ]
            if unseated and normal_seats:
                metrics["unseated_attendees"] = len(unseated)
                if len(unseated) > len(active_att) * 0.5:
                    issues.append(
                        f"{len(unseated)}/{len(active_att)} 位参会人"
                        "未分配座位"
                    )
                    score -= 0.2

            # Check zone coverage
            zones = {s.zone for s in normal_seats if s.zone}
            empty_zones = []
            for z in zones:
                zone_seats = [s for s in assigned if s.zone == z]
                if not zone_seats:
                    empty_zones.append(z)
            if empty_zones:
                issues.append(
                    f"分区 {', '.join(empty_zones)} 没有任何人入座"
                )
                score -= 0.1

        except Exception as e:
            issues.append(f"验证出错: {e}")
            score -= 0.1

    # Check that tool calls actually happened (not just talk)
    action_tools = [
        tc for tc in tool_calls
        if tc.get("tool_name") in (
            "create_layout", "create_custom_layout",
            "auto_assign", "set_zone",
            "swap_two_attendees", "reassign_attendee_seat",
            "unassign_attendee",
        )
    ]
    if not action_tools and any(
        kw in reply for kw in ("座位", "排座", "布局", "layout", "换座", "swap")
    ):
        issues.append("回复提到了排座但未实际调用工具")
        suggestions.append("应调用 create_layout 或 auto_assign")
        score -= 0.3

    # Hallucination guard for destructive operations: agent claimed it
    # deleted/cleared something without calling the matching tool.
    delete_kws = ("已删除", "已清空", "已清除", "已删完", "全部删除", "已重新生成")
    delete_tools = {
        "delete_attendee_by_name",
        "delete_all_attendees",
        "regenerate_roster_from_excel",
        "delete_area",
    }
    called = {tc.get("tool_name") for tc in tool_calls}
    if any(kw in reply for kw in delete_kws) and not (called & delete_tools):
        issues.append(
            "回复声称完成了删除/清空操作，但没有调用 delete_* / "
            "regenerate_roster_from_excel — 严重幻觉"
        )
        suggestions.append(
            "如果用户要删除参会者，调 delete_all_attendees(confirm=True) "
            "或 delete_attendee_by_name；要重新生成调 "
            "regenerate_roster_from_excel(confirm=True)。"
        )
        score -= 0.5

    return ReflectionResult(
        passed=len(issues) == 0,
        score=max(0.0, score),
        issues=issues,
        suggestions=suggestions,
        metrics=metrics,
    )


async def validate_badge_result(
    event_id: str | None,
    reply: str,
    tool_calls: list[dict],
    services: dict[str, Any],
) -> ReflectionResult:
    """Validate badge plugin results.

    Checks:
    - Template was actually created (not just described)
    - PDF generation includes download link
    - All roles are covered when generating per-role badges
    """
    issues: list[str] = []
    suggestions: list[str] = []
    metrics: dict[str, Any] = {}
    score = 1.0

    action_tools = [
        tc for tc in tool_calls
        if tc.get("tool_name") in (
            "create_template", "generate_badges_pdf",
            "generate_badges_for_role",
        )
    ]
    metrics["tool_calls_count"] = len(action_tools)

    if not action_tools:
        if any(kw in reply for kw in ("模板", "设计", "生成", "铭牌")):
            issues.append("回复提到了铭牌操作但未调用任何工具")
            score -= 0.4
    else:
        # Verify successful tool calls
        errors = [
            tc for tc in action_tools if tc.get("status") == "error"
        ]
        if errors:
            issues.append(
                f"{len(errors)} 个工具调用失败: "
                + ", ".join(tc.get("summary", "") for tc in errors)
            )
            score -= 0.3

    # Check PDF link presence
    if "generate_badges" in str(tool_calls):
        if "/export/badges" not in reply and "下载" not in reply:
            issues.append("生成了铭牌但回复中没有下载链接")
            suggestions.append("确保回复包含 PDF 下载链接")
            score -= 0.2

    return ReflectionResult(
        passed=len(issues) == 0,
        score=max(0.0, score),
        issues=issues,
        suggestions=suggestions,
        metrics=metrics,
    )


async def validate_generic_result(
    reply: str,
    tool_calls: list[dict],
) -> ReflectionResult:
    """Generic validation for any plugin output."""
    issues: list[str] = []
    score = 1.0

    if not reply or len(reply.strip()) < 5:
        issues.append("回复内容过短或为空")
        score -= 0.5

    error_tools = [
        tc for tc in tool_calls if tc.get("status") == "error"
    ]
    if error_tools:
        ratio = len(error_tools) / max(len(tool_calls), 1)
        if ratio > 0.5:
            issues.append(
                f"超过半数工具调用失败 ({len(error_tools)}/{len(tool_calls)})"
            )
            score -= 0.3

    return ReflectionResult(
        passed=len(issues) == 0,
        score=max(0.0, score),
        issues=issues,
        metrics={"tool_errors": len(error_tools)},
    )


# ── Router: pick the right validator ───────────────────────────

_VALIDATORS = {
    "seating": validate_seating_result,
    "badge": validate_badge_result,
}


async def reflect_on_result(
    plugin_name: str,
    event_id: str | None,
    reply: str,
    tool_calls: list[dict],
    services: dict[str, Any],
) -> ReflectionResult:
    """Run domain-specific reflection on a plugin's output.

    Called after each plugin execution in the graph to check quality.
    """
    validator = _VALIDATORS.get(plugin_name)
    if validator:
        return await validator(event_id, reply, tool_calls, services)
    return await validate_generic_result(reply, tool_calls)


# ── LLM-based deep reflection (for complex cases) ─────────────

_REFLECTION_PROMPT = """你是 Eventron 质量审查员。评估以下 Agent 交互的质量。

## 用户请求
{user_msg}

## Agent 回复
{agent_reply}

## 工具调用记录
{tool_log}

## 评估标准
1. **完成度** — 用户请求是否被完整执行（不是只说"我来做"而没做）
2. **准确性** — 工具调用参数是否正确，结果是否合理
3. **有效性** — 是否有冗余或无效的工具调用
4. **用户体验** — 回复是否清晰、有用、包含必要链接/数据

## 输出格式（纯JSON）
{{
  "score": 0.0到1.0,
  "passed": true或false,
  "issues": ["问题1", "问题2"],
  "improvement_hints": ["改进建议1"]
}}"""


async def deep_reflect(
    user_msg: str,
    agent_reply: str,
    tool_calls: list[dict],
    llm: Any,
) -> ReflectionResult:
    """Use LLM to do a deeper quality assessment.

    Only called for important interactions (e.g., first-time operations
    on an event, or when rule-based reflection finds issues).
    """
    tool_log = "\n".join(
        f"- {tc.get('tool_name', '?')}: {tc.get('status', '?')} "
        f"— {tc.get('summary', '')}"
        for tc in tool_calls
    ) or "（无工具调用）"

    prompt = _REFLECTION_PROMPT.format(
        user_msg=user_msg[:500],
        agent_reply=agent_reply[:500],
        tool_log=tool_log,
    )

    try:
        response = await llm.ainvoke([
            {"role": "system", "content": prompt},
        ])
        data = extract_json(response.content)
        return ReflectionResult(
            passed=data.get("passed", True),
            score=float(data.get("score", 0.7)),
            issues=data.get("issues", []),
            suggestions=data.get("improvement_hints", []),
        )
    except Exception:
        return ReflectionResult(passed=True, score=0.5)
