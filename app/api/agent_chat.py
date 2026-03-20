"""Agent chat API — routes through the real LangGraph multi-agent graph.

Supports both text-only and multimodal (file upload) conversations.

Every message enters the LangGraph StateGraph:
  orchestrator → intent classify → route to plugin → plugin.handle() → END

Multimodal flow:
  Upload files → planner extracts info → decomposes sub-tasks →
  user confirms → orchestrator dispatches to plugins.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

from app.api.auth import get_current_organizer
from app.deps import (
    get_attendee_service,
    get_event_service,
    get_seating_service,
)
from app.services.attendee_service import AttendeeService
from app.services.event_service import EventService
from app.services.seating_service import SeatingService

router = APIRouter()

# Upload directory for agent chat files
UPLOAD_DIR = Path("/tmp/eventron_uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    event_id: str | None = None
    action_taken: str | None = None
    task_plan: list[dict] | None = None


# ── Session store ──────────────────────────────────────────────
_sessions: dict[str, dict[str, Any]] = {}


def _get_session(session_id: str | None) -> tuple[str, dict]:
    sid = session_id or str(uuid.uuid4())
    if sid not in _sessions:
        _sessions[sid] = {
            "messages": [],
            "event_id": None,
            "user_profile": None,
            "task_plan": [],
            "attachments": [],
        }
    return sid, _sessions[sid]


# ── Service + graph helpers ────────────────────────────────────
def _build_services(
    event_svc: EventService,
    att_svc: AttendeeService,
    seat_svc: SeatingService,
) -> dict[str, Any]:
    """Build the services dict that plugins receive."""
    from app.llm_factory import get_llm
    return {
        "event": event_svc,
        "seating": seat_svc,
        "attendee": att_svc,
        "llm_factory": get_llm,
    }


def _get_graph(services: dict[str, Any]):
    """Build the compiled LangGraph with service-injected plugins."""
    from agents.graph import build_graph
    from agents.plugins import ALL_PLUGINS
    from agents.registry import PluginRegistry
    from app.llm_factory import get_llm

    registry = PluginRegistry()
    for plugin_cls in ALL_PLUGINS:
        plugin = plugin_cls(services=services)
        registry.register(plugin)

    orchestrator_llm = get_llm("fast")
    plugin_llms = {}
    for p in registry.active_plugins:
        if p.llm_model:
            plugin_llms[p.name] = get_llm(p.llm_model)

    return build_graph(registry, orchestrator_llm, plugin_llms)


async def _save_upload(file: UploadFile) -> dict[str, Any]:
    """Save uploaded file and return attachment metadata."""
    from tools.file_extract import detect_file_type

    ext = Path(file.filename or "file").suffix
    uid = uuid.uuid4().hex[:8]
    filename = f"{uid}{ext}"
    filepath = UPLOAD_DIR / filename

    with open(filepath, "wb") as f:
        content = await file.read()
        f.write(content)

    file_type = detect_file_type(file.filename or "")

    return {
        "filename": file.filename,
        "path": str(filepath),
        "type": file_type,
        "content_type": file.content_type,
        "size": len(content),
    }


# ── Text-only endpoint (backward compatible) ──────────────────
@router.post("/chat", response_model=ChatResponse)
async def agent_chat(
    message: str = Form(...),
    event_id: str | None = Form(None),
    session_id: str | None = Form(None),
    scope: str | None = Form(None),
    files: list[UploadFile] = File(default=[]),
    organizer=Depends(get_current_organizer),
    event_svc: EventService = Depends(get_event_service),
    att_svc: AttendeeService = Depends(get_attendee_service),
    seat_svc: SeatingService = Depends(get_seating_service),
):
    """Chat with Eventron AI agent — supports text and file uploads.

    Accepts multipart/form-data:
    - message: User message text
    - event_id: Optional event context
    - session_id: Optional session continuity
    - scope: Optional plugin scope (badge/checkin/seating/organizer)
    - files: Optional file attachments (images, Excel, PDF)
    """
    sid, session = _get_session(session_id)
    msg = message.strip()

    if event_id:
        session["event_id"] = event_id

    # Process file uploads
    new_attachments = []
    for f in files:
        if f.filename:
            att = await _save_upload(f)
            new_attachments.append(att)

    # Build user message content
    if new_attachments:
        session["attachments"] = new_attachments
        # Enhance message with file context
        file_desc = ", ".join(
            f"{a['filename']}({a['type']})" for a in new_attachments
        )
        if msg:
            enhanced_msg = f"[附件: {file_desc}]\n{msg}"
        else:
            enhanced_msg = f"[附件: {file_desc}]\n请分析这些文件并制定活动计划"
    else:
        enhanced_msg = msg

    user_msg = HumanMessage(content=enhanced_msg)
    session["messages"].append(user_msg)

    # Build services and graph
    services = _build_services(event_svc, att_svc, seat_svc)
    try:
        graph = _get_graph(services)
    except ValueError as e:
        return ChatResponse(
            reply=f"LLM 未配置：{e}",
            session_id=sid,
            event_id=session.get("event_id"),
        )

    # Build initial state for LangGraph
    initial_state = {
        "messages": list(session["messages"][-20:]),
        "current_plugin": "",
        "user_profile": session.get("user_profile"),
        "event_id": session.get("event_id"),
        "pending_approval": None,
        "turn_output": None,
        "attachments": session.get("attachments", []),
        "task_plan": session.get("task_plan", []),
        "scope": scope,
    }

    # Run the graph
    try:
        result = await graph.ainvoke(initial_state)
    except Exception as e:
        reply = f"Agent 执行出错：{e}"
        session["messages"].append(AIMessage(content=reply))
        return ChatResponse(
            reply=reply,
            session_id=sid,
            event_id=session.get("event_id"),
        )

    # Extract results
    reply_text = result.get("turn_output", "")
    if not reply_text:
        for m in reversed(result.get("messages", [])):
            if isinstance(m, AIMessage):
                reply_text = m.content
                break
    if not reply_text:
        reply_text = "抱歉，我没有理解您的意思，能再说一次吗？"

    # Update session state
    if result.get("event_id"):
        session["event_id"] = result["event_id"]
    if result.get("user_profile"):
        session["user_profile"] = result["user_profile"]
    if result.get("task_plan"):
        session["task_plan"] = result["task_plan"]

    # Clear attachments after processing
    if new_attachments:
        session["attachments"] = []

    session["messages"].append(AIMessage(content=reply_text))

    action_taken = _detect_action(reply_text)
    task_plan = session.get("task_plan") or None

    return ChatResponse(
        reply=reply_text,
        session_id=sid,
        event_id=session.get("event_id"),
        action_taken=action_taken,
        task_plan=task_plan,
    )


# ── JSON-only endpoint (simple text chat, no files) ───────────
@router.post("/chat/text", response_model=ChatResponse)
async def agent_chat_text(
    body: dict,
    organizer=Depends(get_current_organizer),
    event_svc: EventService = Depends(get_event_service),
    att_svc: AttendeeService = Depends(get_attendee_service),
    seat_svc: SeatingService = Depends(get_seating_service),
):
    """Simple text-only chat endpoint (JSON body, no file upload).

    Backward compatible for clients that don't need file upload.
    """
    message = body.get("message", "").strip()
    if not message:
        return ChatResponse(
            reply="请输入消息",
            session_id=body.get("session_id") or str(uuid.uuid4()),
        )

    sid, session = _get_session(body.get("session_id"))

    if body.get("event_id"):
        session["event_id"] = body["event_id"]

    user_msg = HumanMessage(content=message)
    session["messages"].append(user_msg)

    services = _build_services(event_svc, att_svc, seat_svc)
    try:
        graph = _get_graph(services)
    except ValueError as e:
        return ChatResponse(
            reply=f"LLM 未配置：{e}",
            session_id=sid,
        )

    initial_state = {
        "messages": list(session["messages"][-20:]),
        "current_plugin": "",
        "user_profile": session.get("user_profile"),
        "event_id": session.get("event_id"),
        "pending_approval": None,
        "turn_output": None,
        "attachments": [],
        "task_plan": session.get("task_plan", []),
    }

    try:
        result = await graph.ainvoke(initial_state)
    except Exception as e:
        reply = f"Agent 执行出错：{e}"
        session["messages"].append(AIMessage(content=reply))
        return ChatResponse(reply=reply, session_id=sid)

    reply_text = result.get("turn_output", "")
    if not reply_text:
        for m in reversed(result.get("messages", [])):
            if isinstance(m, AIMessage):
                reply_text = m.content
                break
    if not reply_text:
        reply_text = "抱歉，我没有理解您的意思，能再说一次吗？"

    if result.get("event_id"):
        session["event_id"] = result["event_id"]
    if result.get("user_profile"):
        session["user_profile"] = result["user_profile"]
    if result.get("task_plan"):
        session["task_plan"] = result["task_plan"]

    session["messages"].append(AIMessage(content=reply_text))

    return ChatResponse(
        reply=reply_text,
        session_id=sid,
        event_id=session.get("event_id"),
        action_taken=_detect_action(reply_text),
        task_plan=session.get("task_plan") or None,
    )


def _detect_action(reply: str) -> str | None:
    """Detect what action was taken from the reply text."""
    if "已创建" in reply and "活动" in reply:
        return "event_created"
    if "已生成" in reply and "座位" in reply:
        return "seats_generated"
    if "排座完成" in reply:
        return "seats_assigned"
    if "签到成功" in reply:
        return "checkin_done"
    if "任务计划" in reply:
        return "plan_created"
    return None
