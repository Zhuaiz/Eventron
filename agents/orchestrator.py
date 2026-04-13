"""Orchestrator node — unified ReAct agent with tool-calling routing.

Replaces the old two-phase design (intent classification → plugin dispatch)
with a single ReAct agent whose tools include:
  1. Delegate tools — one per active plugin (delegate_to_seating, etc.)
  2. Utility tools — lightweight queries (list_events, describe_capabilities)

The orchestrator LLM decides WHEN and WHICH tools to call. Multi-step
orchestration (planner → organizer → seating) happens naturally through
sequential tool calls within the same ReAct loop.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from agents.llm_utils import extract_text_content
from agents.registry import PluginRegistry
from agents.state import AgentState

# Exported for agent_config_defaults.py — the orchestrator's system prompt
# is built dynamically at runtime, but we expose a static template so
# admins can view/edit the default in the config UI.
ORCHESTRATOR_DEFAULT_PROMPT = """\
你是 Eventron 会场智能排座系统的主控 Agent。理解用户意图，选择合适的工具完成任务。

## 决策规则
1. Meta 问题（"你能做什么"、"有什么功能"）→ 调 describe_capabilities
2. 活动查询（"有什么活动"）→ 调 list_events
3. 活动详情 → 调 get_event_detail 或 get_event_summary
4. 复杂操作（创建活动、排座、铭牌、签到页等）→ 调对应的 delegate_to_xxx
5. 文件/图片分析 → 先调 delegate_to_planner
6. 多步骤任务：按逻辑顺序调用多个代理
7. 打招呼/闲聊 → 直接回复

## 重要
- 操作性请求优先调用 delegate 工具，不要只回复文字
- 调用 delegate 时传入用户原始请求全文
- 绝对不要在用户问"你有什么工具"时调 list_events
- 回复使用简洁友好的中文"""


def _build_system_prompt(
    registry: PluginRegistry,
    state: AgentState,
    *,
    scope: str | None = None,
) -> str:
    """Build the orchestrator's system prompt with delegate descriptions."""
    # Build delegate tool descriptions
    delegate_lines: list[str] = []
    for p in registry.active_plugins:
        if p.name == "identity":
            continue
        if scope and p.name != scope:
            continue
        delegate_lines.append(
            f"- delegate_to_{p.name}: {p.description}"
        )
    delegate_desc = "\n".join(delegate_lines) if delegate_lines else "（无可用代理）"

    # Context hints
    context_parts: list[str] = []
    if state.get("user_profile"):
        name = state["user_profile"].get("name", "")
        if name:
            context_parts.append(f"当前用户: {name}")
    if state.get("event_id"):
        context_parts.append(f"当前活动ID: {state['event_id']}")
    attachments = state.get("attachments") or []
    if attachments:
        fnames = [a.get("filename", "file") for a in attachments]
        context_parts.append(f"用户上传了文件: {', '.join(fnames)}")

    context_str = "\n".join(context_parts) if context_parts else "无特殊上下文"

    # Scope-specific instruction
    scope_instruction = ""
    if scope:
        scope_names = {
            "seating": "排座", "badge": "铭牌设计",
            "checkin": "签到", "pagegen": "签到页设计",
            "organizer": "活动管理", "planner": "任务规划",
        }
        scope_zh = scope_names.get(scope, scope)
        scope_instruction = (
            f"\n## 当前模式\n"
            f"你正在 **{scope_zh}** 专用面板中。"
            f"请直接使用 delegate_to_{scope} 处理用户请求，"
            f"不要引导用户去其他功能。\n"
        )

    return f"""\
你是 Eventron 会场智能排座系统的主控 Agent。理解用户意图，选择合适的工具完成任务。

今天日期：{date.today().isoformat()}

## 当前上下文
{context_str}
{scope_instruction}
## 专家代理（处理复杂任务）
{delegate_desc}

## 通用工具（直接查询）
- describe_capabilities: 介绍系统功能（用户问"你能做什么"时使用）
- list_events: 列出所有活动
- get_event_detail: 查看活动详情（需要活动ID）
- get_event_summary: 活动统计概览

## 决策规则
1. Meta 问题（"你能做什么"、"有什么功能"、"帮助"、"你是谁"）→ 调 describe_capabilities
2. 活动查询（"有什么活动"、"活动列表"）→ 调 list_events
3. 活动详情/统计 → 调 get_event_detail 或 get_event_summary
4. 复杂操作（创建活动、排座、铭牌、签到页等）→ 调对应的 delegate_to_xxx
5. 文件/图片分析 → 先调 delegate_to_planner
6. 多步骤任务：按逻辑顺序调用多个代理（如：planner → organizer → seating）
7. 打招呼/闲聊 → 直接友好回复

## 重要
- 操作性请求优先调用 delegate 工具，不要只回复文字
- 调用 delegate 时，传入用户的**原始请求全文**
- delegate 返回的活动ID等上下文会自动传递给后续调用，无需手动处理
- 如果代理返回错误，向用户说明并建议解决方案
- 不要重复调用已经成功的代理
- 回复使用简洁友好的中文
- **绝对不要**在用户问"你有什么工具"时调 list_events——那是列活动，不是介绍自己"""


async def orchestrator_agent_node(
    state: AgentState,
    registry: PluginRegistry,
    llm: Any,
    services: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """LangGraph node: unified orchestrator as ReAct tool-calling agent.

    Builds delegate tools (one per plugin) + utility tools, then runs
    a ReAct loop. The LLM naturally routes to the right plugin via
    tool calling, and can chain multiple plugins for complex tasks.

    Args:
        state: Current agent state.
        registry: Plugin registry with all active plugins.
        llm: LangChain LLM for the orchestrator (typically fast tier).
        services: Service dict for utility tools and experience injection.

    Returns:
        Dict to merge into AgentState with turn_output, messages,
        tool_calls, parts, and any side-effects from delegate tools.
    """
    from agents.react import react_loop
    from agents.tools.general_tools import make_general_tools
    from agents.tools.routing_tools import make_delegate_tools

    _services = services or {}
    scope = state.get("scope")

    # Identity pre-check: if user unknown and needed, handle identity first
    user_profile = state.get("user_profile")
    if not user_profile:
        identity_plugin = registry.get("identity")
        if identity_plugin and identity_plugin.enabled:
            # Check if any plugins need identity
            needs_identity = any(
                p.requires_identity
                for p in registry.active_plugins
                if p.name != "identity"
            )
            if needs_identity:
                try:
                    result = await identity_plugin.handle(state)
                    if result.get("user_profile"):
                        # Identity resolved — continue with updated state
                        state = {**state, **result}
                        user_profile = result["user_profile"]
                    else:
                        # Identity not resolved — return identity prompt
                        return result
                except Exception:
                    pass  # Fall through to normal flow

    # Mutable accumulators for delegate side-effects
    accumulated_updates: dict[str, Any] = {}
    accumulated_parts: list[dict[str, Any]] = []
    accumulated_tool_calls: list[dict[str, Any]] = []

    # ── Hard guard: attachments present → direct planner call ───
    # Weak LLMs (deepseek-chat) can't reliably route file uploads
    # to the planner via tool-calling. Bypass ReAct for this case.
    attachments = state.get("attachments") or []
    task_plan = state.get("task_plan") or []
    if attachments and not task_plan and not scope:
        planner = registry.get("planner")
        if planner and planner.enabled:
            try:
                result = await planner.handle(state)
                # Capture side-effects
                for key in (
                    "event_id", "user_profile", "event_draft",
                    "task_plan",
                ):
                    if result.get(key) is not None:
                        accumulated_updates[key] = result[key]
                if result.get("tool_calls"):
                    accumulated_tool_calls.extend(result["tool_calls"])
                if result.get("parts"):
                    accumulated_parts.extend(result["parts"])
                accumulated_updates["current_plugin"] = "planner"

                reply = result.get("turn_output", "文件分析完成。")
                return {
                    "messages": [AIMessage(content=reply)],
                    "turn_output": reply,
                    "tool_calls": accumulated_tool_calls,
                    "parts": accumulated_parts,
                    **accumulated_updates,
                }
            except Exception:
                pass  # Fall through to normal ReAct flow

    # ── Hard guard: scope forcing → direct plugin call ──────────
    # SubAgentPanel sends scope="seating" etc. For focused panels,
    # skip the orchestrator's routing and call the plugin directly.
    if scope:
        _SCOPE_MAP = {
            "badge": "badge", "checkin": "checkin",
            "seating": "seating", "organizer": "organizer",
            "planner": "planner", "pagegen": "pagegen",
        }
        target_name = _SCOPE_MAP.get(scope)
        target_plugin = registry.get(target_name) if target_name else None
        if target_plugin and target_plugin.enabled:
            try:
                # Inject experiences
                eid = state.get("event_id")
                if eid:
                    try:
                        from agents.memory import get_relevant_experiences
                        user_msg = ""
                        for msg in reversed(state["messages"]):
                            if isinstance(msg, HumanMessage):
                                user_msg = extract_text_content(
                                    msg.content,
                                )
                                break
                        exps = get_relevant_experiences(
                            eid, target_name, user_msg,
                        )
                        if exps:
                            state = {**state, "_experiences": exps}
                    except Exception:
                        pass

                result = await target_plugin.handle(state)
                for key in (
                    "event_id", "user_profile", "event_draft",
                ):
                    if result.get(key) is not None:
                        accumulated_updates[key] = result[key]
                if result.get("tool_calls"):
                    accumulated_tool_calls.extend(result["tool_calls"])
                if result.get("parts"):
                    accumulated_parts.extend(result["parts"])
                if result.get("quick_replies"):
                    accumulated_updates["quick_replies"] = result[
                        "quick_replies"
                    ]
                accumulated_updates["current_plugin"] = target_name

                reply = result.get("turn_output", "操作完成。")
                return {
                    "messages": [AIMessage(content=reply)],
                    "turn_output": reply,
                    "tool_calls": accumulated_tool_calls,
                    "parts": accumulated_parts,
                    **accumulated_updates,
                }
            except Exception:
                pass  # Fall through to ReAct

    # ── Normal ReAct flow ───────────────────────────────────────

    # Build delegate tools (one per plugin)
    delegate_tools = make_delegate_tools(
        registry=registry,
        state=state,
        services=_services,
        accumulated_updates=accumulated_updates,
        accumulated_parts=accumulated_parts,
        accumulated_tool_calls=accumulated_tool_calls,
    )

    # Build utility tools
    utility_tools: list = []
    if _services.get("event"):
        utility_tools = make_general_tools(
            event_svc=_services["event"],
            attendee_svc=_services.get("attendee"),
            seat_svc=_services.get("seating"),
        )

    all_tools = delegate_tools + utility_tools

    # Use config override for system prompt if available
    try:
        from app.services.agent_config_service import (
            get_effective_prompt,
        )
        custom_prompt = get_effective_prompt("orchestrator")
    except Exception:
        custom_prompt = None

    system_prompt = custom_prompt or _build_system_prompt(
        registry, state,
    )

    # Build message history for the ReAct loop
    msgs: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
    ]
    for msg in state["messages"][-20:]:
        if isinstance(msg, HumanMessage):
            msgs.append({
                "role": "user",
                "content": extract_text_content(msg.content),
            })
        elif isinstance(msg, AIMessage):
            msgs.append({
                "role": "assistant",
                "content": msg.content or "",
            })

    # Set up parts accumulator so utility tools can push cards
    from agents.message_parts import PARTS_ACCUMULATOR
    parts_token = PARTS_ACCUMULATOR.set(accumulated_parts)

    # Run the orchestrator's ReAct loop
    try:
        if all_tools:
            llm_with_tools = llm.bind_tools(all_tools)
            result_msg = await react_loop(
                llm_with_tools, msgs, all_tools, max_iter=15,
            )
        else:
            # No tools available — just chat
            response = await llm.ainvoke(msgs)
            result_msg = response
    finally:
        PARTS_ACCUMULATOR.reset(parts_token)

    reply = result_msg.content or "操作完成。"

    # Merge tool call logs: inner (from plugins) + outer (from orchestrator)
    all_tool_calls = list(accumulated_tool_calls)
    outer_log = getattr(result_msg, "tool_call_log", [])
    if outer_log:
        # Filter out delegate_to_xxx from outer log — those are routing
        # metadata, not useful for the user. Keep utility tool calls.
        for tc in outer_log:
            name = tc.get("tool_name", "")
            if not name.startswith("delegate_to_"):
                all_tool_calls.append(tc)

    # Build return state
    output: dict[str, Any] = {
        "messages": [AIMessage(content=reply)],
        "turn_output": reply,
        "tool_calls": all_tool_calls,
        "parts": accumulated_parts,
    }

    # Merge accumulated side-effects
    for key in (
        "event_id", "user_profile", "event_draft",
        "current_plugin", "quick_replies", "pending_approval",
    ):
        if key in accumulated_updates:
            output[key] = accumulated_updates[key]

    return output
