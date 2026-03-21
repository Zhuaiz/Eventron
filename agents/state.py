"""Shared agent state — the single TypedDict passed through the LangGraph."""

from __future__ import annotations

from typing import Annotated, Any

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class SubTask(TypedDict, total=False):
    """A sub-task created by the planner for parallel execution."""
    id: str                    # e.g. "venue", "badge", "checkin"
    plugin: str                # target plugin name
    description: str           # what to do
    status: str                # pending | in_progress | done | error
    result: str | None         # result summary


class AgentState(TypedDict):
    """Shared state flowing through the LangGraph StateGraph.

    Fields:
        messages: Conversation history (auto-merged by LangGraph).
        current_plugin: Which plugin the orchestrator routed to.
        user_profile: Identified user info, or None if unknown.
        event_id: Currently active event UUID (string).
        pending_approval: HITL interrupt data for change plugin.
        turn_output: Final response text for this turn.
        attachments: Uploaded files [{filename, content_type, path, extracted_text?}].
        task_plan: Planner's decomposed task plan (list of SubTask).
        event_draft: Structured event info extracted by planner (passed to organizer).
        scope: Optional forced plugin scope (badge/checkin/seating/organizer).
        reflection: Post-execution self-check result (set by reflect node).
    """

    messages: Annotated[list[BaseMessage], add_messages]
    current_plugin: str
    user_profile: dict[str, Any] | None
    event_id: str | None
    pending_approval: dict[str, Any] | None
    turn_output: str | None
    attachments: list[dict[str, Any]]
    task_plan: list[SubTask]
    event_draft: dict[str, Any] | None
    scope: str | None
    tool_calls: list[dict[str, Any]]
    reflection: dict[str, Any] | None
