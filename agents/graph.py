"""Build and compile the LangGraph StateGraph.

Wiring:
  Entry → orchestrator → conditional edge → [plugin nodes | chat] → END

When attachments are present, the orchestrator routes to the planner
plugin first, which analyzes the files and creates a task plan.

Self-evolution: after each plugin, a reflection node checks quality,
records to event memory, and can trigger auto-repair.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from agents.orchestrator import chat_fallback_node, orchestrator_node
from agents.registry import PluginRegistry
from agents.state import AgentState


def build_graph(
    registry: PluginRegistry,
    llm: Any,
    plugin_llms: dict[str, Any] | None = None,
    services: dict[str, Any] | None = None,
) -> StateGraph:
    """Build the Eventron agent graph.

    Args:
        registry: Plugin registry with all active plugins.
        llm: Default LLM for orchestrator and chat fallback.
        plugin_llms: Optional per-plugin LLM overrides {plugin_name: llm}.
        services: Service dict for reflection validators.

    Returns:
        Compiled StateGraph ready for invocation.
    """
    _services = services or {}
    graph = StateGraph(AgentState)

    # ── Orchestrator node ────────────────────────────────────
    # ── Scope → plugin name mapping ─────────────────────────
    _SCOPE_MAP = {
        "badge": "badge",
        "checkin": "checkin",
        "seating": "seating",
        "organizer": "organizer",
        "planner": "planner",
        "pagegen": "pagegen",
    }

    # Confirmation keywords that mean "go ahead with the plan"
    _CONTINUE_KEYWORDS = {
        "继续", "开始", "执行", "创建", "好", "好的", "可以",
        "开始执行", "继续创建", "继续吧", "创建吧", "执行计划",
        "是", "是的", "没问题", "确认", "ok", "go",
    }

    async def _orchestrator(state: AgentState) -> dict[str, Any]:
        # 1) Forced scope → route directly to that plugin
        scope = state.get("scope")
        if scope:
            target = _SCOPE_MAP.get(scope)
            if target and registry.get(target) is not None:
                return {"current_plugin": target}

        # 2) Attachments present and no plan yet → planner
        attachments = state.get("attachments") or []
        task_plan = state.get("task_plan") or []
        if attachments and not task_plan:
            if registry.get("planner") is not None:
                return {"current_plugin": "planner"}

        # 3) Active task_plan/event_draft + confirmation → organizer
        event_draft = state.get("event_draft")
        if task_plan or event_draft:
            from langchain_core.messages import HumanMessage as HM
            from agents.llm_utils import extract_text_content
            last_msg = ""
            for msg in reversed(state["messages"]):
                if isinstance(msg, HM):
                    last_msg = extract_text_content(
                        msg.content
                    ).strip()
                    break
            clean = last_msg
            if clean.startswith("["):
                clean = clean.split("]", 1)[-1].strip()
            if clean.lower() in _CONTINUE_KEYWORDS:
                if registry.get("organizer") is not None:
                    return {"current_plugin": "organizer"}
            if event_draft and registry.get("organizer") is not None:
                return {"current_plugin": "organizer"}

        # 4) Normal LLM-based intent routing
        return await orchestrator_node(state, registry, llm)

    graph.add_node("orchestrator", _orchestrator)
    graph.set_entry_point("orchestrator")

    # ── Chat fallback node ───────────────────────────────────
    async def _chat(state: AgentState) -> dict[str, Any]:
        return await chat_fallback_node(state, llm)

    graph.add_node("chat", _chat)
    graph.add_edge("chat", END)

    # ── Reflection node (self-check + memory + prompt feedback) ──
    async def _reflect(state: AgentState) -> dict[str, Any]:
        """Post-plugin reflection: validate, record, learn."""
        plugin_name = state.get("current_plugin", "")
        event_id = state.get("event_id")
        reply = state.get("turn_output", "")
        tool_calls = state.get("tool_calls") or []

        if not reply:
            return {}

        try:
            from agents.reflection import reflect_on_result
            reflection = await reflect_on_result(
                plugin_name=plugin_name,
                event_id=event_id,
                reply=reply,
                tool_calls=tool_calls,
                services=_services,
            )

            # Record to event memory
            if event_id:
                from agents.memory import record_interaction
                from agents.llm_utils import extract_text_content
                from langchain_core.messages import HumanMessage as HM

                user_msg = ""
                for msg in reversed(state["messages"]):
                    if isinstance(msg, HM):
                        user_msg = extract_text_content(msg.content)
                        break

                # Build event context snapshot
                event_ctx: dict[str, Any] = {}
                if _services.get("event"):
                    try:
                        import uuid
                        ev = await _services["event"].get_event(
                            uuid.UUID(event_id)
                        )
                        event_ctx = {
                            "layout_type": ev.layout_type,
                            "status": ev.status,
                        }
                        if _services.get("attendee"):
                            atts = await _services[
                                "attendee"
                            ].list_attendees_for_event(
                                uuid.UUID(event_id)
                            )
                            event_ctx["attendee_count"] = len(atts)
                    except Exception:
                        pass

                record_interaction(
                    event_id=event_id,
                    plugin=plugin_name,
                    user_msg=user_msg[:500],
                    agent_reply=reply[:500],
                    tool_calls=tool_calls[:20],
                    reflection_score=reflection.score,
                    reflection_issues=reflection.issues,
                    event_context=event_ctx,
                )

            # Record outcome for prompt version tracking
            prompt_version = state.get("_prompt_version")
            if prompt_version and plugin_name:
                from agents.prompt_evolution import (
                    record_prompt_outcome,
                )
                record_prompt_outcome(
                    plugin=plugin_name,
                    version=prompt_version,
                    score=reflection.score,
                )

            # Store reflection metadata for API response
            return {
                "reflection": {
                    "score": reflection.score,
                    "passed": reflection.passed,
                    "issues": reflection.issues,
                    "suggestions": reflection.suggestions,
                    "metrics": reflection.metrics,
                },
            }
        except Exception:
            # Reflection failure should never break the main flow
            return {}

    graph.add_node("reflect", _reflect)
    graph.add_edge("reflect", END)

    # ── Plugin nodes ─────────────────────────────────────────
    for plugin in registry.active_plugins:
        def _make_plugin_node(p):
            async def _plugin_node(
                state: AgentState,
            ) -> dict[str, Any]:
                # Inject relevant experiences into state
                event_id = state.get("event_id")
                if event_id:
                    try:
                        from agents.memory import (
                            get_relevant_experiences,
                        )
                        from agents.llm_utils import (
                            extract_text_content,
                        )
                        from langchain_core.messages import (
                            HumanMessage as HM,
                        )
                        user_msg = ""
                        for msg in reversed(state["messages"]):
                            if isinstance(msg, HM):
                                user_msg = extract_text_content(
                                    msg.content
                                )
                                break
                        exps = get_relevant_experiences(
                            event_id, p.name, user_msg
                        )
                        if exps:
                            state["_experiences"] = exps
                    except Exception:
                        pass
                return await p.handle(state)
            return _plugin_node

        graph.add_node(plugin.name, _make_plugin_node(plugin))
        # Plugin → conditional: if turn_output → reflect → END
        # else → orchestrator (loop)
        graph.add_conditional_edges(
            plugin.name,
            lambda state: (
                "reflect" if state.get("turn_output")
                else "orchestrator"
            ),
            {"reflect": "reflect", "orchestrator": "orchestrator"},
        )

    # ── Conditional routing from orchestrator ────────────────
    def _route(state: AgentState) -> str:
        target = state.get("current_plugin", "chat")
        if target == "chat":
            return "chat"
        if registry.get(target) is not None:
            return target
        return "chat"

    route_map = {"chat": "chat"}
    for p in registry.active_plugins:
        route_map[p.name] = p.name

    graph.add_conditional_edges("orchestrator", _route, route_map)

    return graph.compile()
