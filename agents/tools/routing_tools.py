"""Delegate tools for the orchestrator — wraps each plugin as a callable tool.

Each delegate tool:
1. Takes the user's request string
2. Runs the target plugin's handle() with full agent state
3. Captures state side-effects (event_id, tool_calls, parts, etc.)
4. Returns the plugin's text response

This replaces the old intent-classification routing with native
tool-calling, unifying routing and execution into a single ReAct loop.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool


def make_delegate_tools(
    registry: Any,
    state: dict[str, Any],
    services: dict[str, Any],
    accumulated_updates: dict[str, Any],
    accumulated_parts: list[dict[str, Any]],
    accumulated_tool_calls: list[dict[str, Any]],
    *,
    scope: str | None = None,
) -> list[StructuredTool]:
    """Build delegate tools that route user requests to sub-agent plugins.

    Each tool wraps plugin.handle() and captures state side-effects
    into the mutable accumulators provided by the caller.

    Args:
        registry: PluginRegistry with active plugins.
        state: Current AgentState snapshot (read-only reference).
        services: Service dict for experience injection.
        accumulated_updates: Mutable dict to collect state changes
            (event_id, user_profile, quick_replies, etc.).
        accumulated_parts: Mutable list to collect UI card parts.
        accumulated_tool_calls: Mutable list to collect inner tool call logs.
        scope: Optional forced scope — if set, only expose that plugin.

    Returns:
        List of StructuredTool instances, one per eligible plugin.
    """
    _SCOPE_MAP = {
        "badge": "badge",
        "checkin": "checkin",
        "seating": "seating",
        "organizer": "organizer",
        "planner": "planner",
        "pagegen": "pagegen",
    }

    active_plugins = registry.active_plugins

    # Filter by scope: only expose the target plugin
    if scope:
        target = _SCOPE_MAP.get(scope)
        if target:
            active_plugins = [
                p for p in active_plugins if p.name == target
            ]

    user_profile = state.get("user_profile")
    tools: list[StructuredTool] = []

    for plugin in active_plugins:
        # Identity plugin handled separately (pre-check)
        if plugin.name == "identity":
            continue

        # Skip plugins that require identity when user is unknown
        if plugin.requires_identity and not user_profile:
            continue

        # Build delegate tool via closure
        async def _delegate(
            user_request: str, *, _p=plugin,
        ) -> str:
            """Route user request to a specialized sub-agent.

            Args:
                user_request: The user's original request text.
            """
            # Build state for plugin with accumulated side-effects
            current_state = {**state, **accumulated_updates}
            current_state["turn_output"] = None
            current_state["plan_output"] = None

            # Inject relevant experiences from event memory
            eid = current_state.get("event_id")
            if eid:
                try:
                    from agents.memory import get_relevant_experiences
                    from agents.llm_utils import extract_text_content
                    from langchain_core.messages import (
                        HumanMessage as HM,
                    )

                    user_msg = ""
                    for msg in reversed(
                        current_state.get("messages", [])
                    ):
                        if isinstance(msg, HM):
                            user_msg = extract_text_content(msg.content)
                            break
                    exps = get_relevant_experiences(
                        eid, _p.name, user_msg,
                    )
                    if exps:
                        current_state["_experiences"] = exps
                except Exception:
                    pass

            # Run the plugin
            result = await _p.handle(current_state)

            # Capture state side-effects
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

            if result.get("pending_approval"):
                accumulated_updates["pending_approval"] = result[
                    "pending_approval"
                ]

            # Track which plugin was called (for reflection)
            accumulated_updates["current_plugin"] = _p.name

            reply = result.get("turn_output", "操作完成。")

            # Append side-effect hints so the orchestrator LLM
            # knows what context was captured (event_id, etc.)
            hints: list[str] = []
            if result.get("event_id"):
                hints.append(
                    f"[已获取活动ID: {result['event_id']}]"
                )
            if result.get("task_plan"):
                hints.append("[已生成任务计划]")
            if hints:
                reply = reply + "\n" + " ".join(hints)

            return reply

        t = StructuredTool.from_function(
            coroutine=_delegate,
            name=f"delegate_to_{plugin.name}",
            description=(
                f"将任务转交给{plugin.name}专家处理。{plugin.description}"
            ),
        )
        tools.append(t)

    return tools
