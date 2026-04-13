"""Build and compile the LangGraph StateGraph.

Simplified architecture (post-refactor):
  Entry → orchestrator_agent → reflect → END

The orchestrator is now a ReAct agent with delegate tools (one per plugin)
and utility tools. Multi-step orchestration happens naturally through
sequential tool calls within the orchestrator's ReAct loop, eliminating
the need for continue_plan nodes and conditional edges.

Self-evolution: after the orchestrator finishes, a reflection node checks
quality, records to event memory, and can trigger auto-repair.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from agents.orchestrator import orchestrator_agent_node
from agents.registry import PluginRegistry
from agents.state import AgentState


def build_graph(
    registry: PluginRegistry,
    llm: Any,
    plugin_llms: dict[str, Any] | None = None,
    services: dict[str, Any] | None = None,
) -> StateGraph:
    """Build the Eventron agent graph.

    Simplified from the old multi-node design to:
      orchestrator_agent → reflect → END

    The orchestrator handles all routing internally via tool calling.

    Args:
        registry: Plugin registry with all active plugins.
        llm: Default LLM for orchestrator (typically fast tier).
        plugin_llms: Optional per-plugin LLM overrides (used by plugins
            internally, not by the graph).
        services: Service dict for reflection validators and utility tools.

    Returns:
        Compiled StateGraph ready for invocation.
    """
    _services = services or {}
    graph = StateGraph(AgentState)

    # ── Orchestrator node (unified ReAct agent) ──────────────────
    async def _orchestrator(state: AgentState) -> dict[str, Any]:
        return await orchestrator_agent_node(
            state, registry, llm, services=_services,
        )

    graph.add_node("orchestrator", _orchestrator)
    graph.set_entry_point("orchestrator")

    # ── Reflection node (self-check + memory + prompt feedback) ──
    async def _reflect(state: AgentState) -> dict[str, Any]:
        """Post-orchestrator reflection: validate, record, learn."""
        plugin_name = state.get("current_plugin", "orchestrator")
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
                            uuid.UUID(event_id),
                        )
                        event_ctx = {
                            "layout_type": ev.layout_type,
                            "status": ev.status,
                        }
                        if _services.get("attendee"):
                            atts = await _services[
                                "attendee"
                            ].list_attendees_for_event(
                                uuid.UUID(event_id),
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

    # ── Simple linear flow ───────────────────────────────────────
    graph.add_edge("orchestrator", "reflect")
    graph.add_edge("reflect", END)

    return graph.compile()
