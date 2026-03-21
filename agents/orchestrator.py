"""Orchestrator node — intent classification and plugin routing.

This is the entry point of the LangGraph. It classifies user intent
and routes to the appropriate plugin. NEVER hard-codes plugin names.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from agents.llm_utils import extract_text_content
from agents.registry import PluginRegistry
from agents.state import AgentState

ROUTER_SYSTEM_TEMPLATE = """你是 Eventron 智能路由器。根据用户消息判断该交给哪个 plugin 处理。

今天日期：{today}

可用 plugins：
{plugin_descriptions}

规则：
1. 如果用户身份未确认（user_profile 为空）且目标 plugin 需要身份验证，输出 "identity"。
2. 只输出 plugin 名称（一个词），不要输出其他内容。
3. 如果没有合适的 plugin，输出 "chat"。
4. 用户讨论创建活动、计算会场容量、排座等管理操作 → "organizer"。
5. 用户在对话中已经开始创建活动（有 draft 上下文）→ 继续用 "organizer"。
6. 用户上传了文件（图片/Excel/PDF）或提到"分析"、"规划"、"拆解" → "planner"。
7. 用户说"开始执行"或"执行计划" → "organizer"（按计划执行）。"""


async def classify_intent(
    state: AgentState,
    registry: PluginRegistry,
    llm: Any,
) -> str:
    """Classify user intent using LLM and return plugin name.

    Args:
        state: Current agent state.
        registry: Plugin registry for building routing prompt.
        llm: LangChain LLM instance (any BaseChatModel).

    Returns:
        Plugin name string, or 'chat' for general conversation.
    """
    plugin_descriptions = registry.build_routing_prompt()

    # Use config override if available
    try:
        from app.services.agent_config_service import (
            get_effective_prompt,
        )
        tpl = get_effective_prompt("orchestrator")
        if not tpl:
            tpl = ROUTER_SYSTEM_TEMPLATE
    except Exception:
        tpl = ROUTER_SYSTEM_TEMPLATE

    system_prompt = tpl.format(
        today=date.today().isoformat(),
        plugin_descriptions=plugin_descriptions,
    )

    # Get the last user message (handle multimodal content)
    last_msg = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            last_msg = extract_text_content(msg.content)
            break

    # Add context hints for better routing
    context_hints = []
    if state.get("user_profile"):
        name = state["user_profile"].get("name", "")
        context_hints.append(f"用户已识别: {name}")
    if state.get("event_id"):
        context_hints.append(f"当前活动: {state['event_id']}")

    user_content = last_msg
    if context_hints:
        user_content = (
            f"[上下文: {', '.join(context_hints)}]\n{last_msg}"
        )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    response = await llm.ainvoke(messages)
    intent = response.content.strip().lower()

    # Clean up — LLM might output extra text
    intent = intent.split("\n")[0].strip().strip('"').strip("'")

    # Validate against registered plugins
    if intent != "chat" and registry.get(intent) is None:
        intent = "chat"

    # Identity gate: if plugin requires identity and user is unknown
    if intent not in ("chat", "identity"):
        plugin = registry.get(intent)
        if (
            plugin
            and plugin.requires_identity
            and state.get("user_profile") is None
        ):
            intent = "identity"

    return intent


async def orchestrator_node(
    state: AgentState,
    registry: PluginRegistry,
    llm: Any,
) -> dict[str, Any]:
    """LangGraph node: classify intent and update state.

    Returns dict to merge into AgentState with 'current_plugin' set.
    """
    intent = await classify_intent(state, registry, llm)
    return {"current_plugin": intent}


async def chat_fallback_node(
    state: AgentState, llm: Any
) -> dict[str, Any]:
    """Fallback node for general chat (no specific plugin matched).

    Uses LLM to generate a friendly response in Chinese.
    """
    system = (
        "你是 Eventron 会场智能排座助手。用简洁友好的中文回复。"
        "如果用户的问题和活动管理相关，引导他使用相关功能。"
    )
    msgs = [{"role": "system", "content": system}]
    for msg in state["messages"][-10:]:
        if isinstance(msg, HumanMessage):
            msgs.append({"role": "user", "content": extract_text_content(msg.content)})
        elif isinstance(msg, AIMessage):
            msgs.append({"role": "assistant", "content": msg.content})

    response = await llm.ainvoke(msgs)
    return {
        "messages": [AIMessage(content=response.content)],
        "turn_output": response.content,
    }
