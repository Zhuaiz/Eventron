"""Build and compile the LangGraph StateGraph.

Wiring:
  Entry → orchestrator → conditional edge → [plugin nodes | chat] → END

When attachments are present, the orchestrator routes to the planner
plugin first, which analyzes the files and creates a task plan.
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
) -> StateGraph:
    """Build the Eventron agent graph.

    Args:
        registry: Plugin registry with all active plugins.
        llm: Default LLM for orchestrator and chat fallback.
        plugin_llms: Optional per-plugin LLM overrides {plugin_name: llm}.

    Returns:
        Compiled StateGraph ready for invocation.
    """
    graph = StateGraph(AgentState)

    # ── Orchestrator node ────────────────────────────────────
    # ── Scope → plugin name mapping ─────────────────────────
    _SCOPE_MAP = {
        "badge": "badge",
        "checkin": "checkin",
        "seating": "seating",
        "organizer": "organizer",
        "planner": "planner",
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

        # 3) Normal LLM-based intent routing
        return await orchestrator_node(state, registry, llm)

    graph.add_node("orchestrator", _orchestrator)
    graph.set_entry_point("orchestrator")

    # ── Chat fallback node ───────────────────────────────────
    async def _chat(state: AgentState) -> dict[str, Any]:
        return await chat_fallback_node(state, llm)

    graph.add_node("chat", _chat)
    graph.add_edge("chat", END)

    # ── Plugin nodes ─────────────────────────────────────────
    for plugin in registry.active_plugins:
        def _make_plugin_node(p):
            async def _plugin_node(state: AgentState) -> dict[str, Any]:
                return await p.handle(state)
            return _plugin_node

        graph.add_node(plugin.name, _make_plugin_node(plugin))
        graph.add_conditional_edges(
            plugin.name,
            lambda state: (
                END if state.get("turn_output") else "orchestrator"
            ),
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
