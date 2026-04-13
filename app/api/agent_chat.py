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
    get_badge_template_service,
    get_checkin_service,
    get_event_service,
    get_seating_service,
)
from app.services.attendee_service import AttendeeService
from app.services.badge_template_service import BadgeTemplateService
from app.services.checkin_service import CheckinService
from app.services.event_service import EventService
from app.services.seating_service import SeatingService

router = APIRouter()

# Upload directory for agent chat files
UPLOAD_DIR = Path("/tmp/eventron_uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


class ToolCallInfo(BaseModel):
    """Info about a tool call the agent made during this turn."""
    tool_name: str
    tool_name_zh: str  # Chinese display name
    status: str  # "success" | "error"
    summary: str  # brief result summary


class ReflectionInfo(BaseModel):
    """Self-check result from the reflection layer."""
    score: float
    passed: bool
    issues: list[str] = []
    suggestions: list[str] = []
    metrics: dict[str, Any] = {}


class QuickReplyItem(BaseModel):
    """A HITL quick-reply button for the frontend."""
    label: str
    value: str
    style: str = "default"  # "primary" | "default" | "danger"


class MessagePart(BaseModel):
    """A structured UI card part for rich frontend rendering."""
    type: str  # seat_map, attendee_table, event_card, page_preview, etc.
    # Remaining fields vary by type — stored as extra kwargs
    model_config = {"extra": "allow"}


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    event_id: str | None = None
    action_taken: str | None = None
    task_plan: list[dict] | None = None
    tool_calls: list[ToolCallInfo] | None = None
    quick_replies: list[QuickReplyItem] | None = None
    reflection: ReflectionInfo | None = None
    parts: list[dict] | None = None


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
            "event_draft": None,
        }
    return sid, _sessions[sid]


# ── Service + graph helpers ────────────────────────────────────
def _build_services(
    event_svc: EventService,
    att_svc: AttendeeService,
    seat_svc: SeatingService,
    badge_svc: BadgeTemplateService | None = None,
    checkin_svc: CheckinService | None = None,
) -> dict[str, Any]:
    """Build the services dict that plugins receive."""
    from app.llm_factory import get_llm
    svc: dict[str, Any] = {
        "event": event_svc,
        "seating": seat_svc,
        "attendee": att_svc,
        "llm_factory": get_llm,
    }
    if badge_svc:
        svc["badge_template"] = badge_svc
    if checkin_svc:
        svc["checkin"] = checkin_svc
    return svc


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

    return build_graph(
        registry, orchestrator_llm, plugin_llms, services=services,
    )


def _detect_image_mime(data: bytes, filename: str = "") -> str:
    """Detect actual image MIME type from file header bytes.

    Falls back to extension-based guessing if header is unrecognized.
    This fixes the common case where a .jpg file is actually PNG
    (e.g. WeChat/QQ saves).
    """
    import mimetypes

    # Check magic bytes
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return "image/png"
    if data[:2] == b'\xff\xd8':
        return "image/jpeg"
    if data[:4] == b'GIF8':
        return "image/gif"
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return "image/webp"
    if data[:2] == b'BM':
        return "image/bmp"
    # Fallback to extension
    return mimetypes.guess_type(filename)[0] or "image/png"


def _build_multimodal_message(
    text: str, attachments: list[dict[str, Any]]
) -> HumanMessage:
    """Build a multimodal HumanMessage with inline images + text.

    Images are embedded as base64 data URIs so the LLM can see them.
    Non-image files are referenced by name in the text.
    """
    import base64
    import mimetypes

    content_parts: list[dict[str, Any]] = []
    non_image_files: list[str] = []

    for att in attachments:
        if att.get("type") == "image" and att.get("path"):
            try:
                path = Path(att["path"])
                if path.exists():
                    raw = path.read_bytes()
                    mime = _detect_image_mime(raw, att.get("filename", "image.png"))
                    b64 = base64.b64encode(raw).decode()
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    })
            except Exception:
                non_image_files.append(att.get("filename", "image"))
        else:
            non_image_files.append(
                f"{att.get('filename', 'file')}({att.get('type', 'file')})"
            )

    # Add text part
    text_content = text or ""
    if non_image_files:
        file_desc = ", ".join(non_image_files)
        if text_content:
            text_content = f"[附件: {file_desc}]\n{text_content}"
        else:
            text_content = f"[附件: {file_desc}]\n请分析这些文件"
    if not text_content:
        text_content = "请分析这些图片"

    content_parts.append({"type": "text", "text": text_content})

    # If no images, just return plain text message
    if not any(p.get("type") == "image_url" for p in content_parts):
        return HumanMessage(content=text_content)

    return HumanMessage(content=content_parts)


async def _save_upload(
    file: UploadFile,
    event_id: str | None = None,
) -> dict[str, Any]:
    """Save uploaded file and return attachment metadata.

    If event_id is provided, persists to the event's file store
    (uploads/events/{event_id}/). Otherwise falls back to temp dir.
    """
    from tools.file_extract import detect_file_type

    content = await file.read()
    file_type = detect_file_type(file.filename or "")

    if event_id:
        # Persist to event file store
        from tools.event_files import event_dir as _event_dir, load_manifest as _load_manifest, save_manifest as _save_manifest

        eid = uuid.UUID(event_id)
        ext = Path(file.filename or "file").suffix.lower()
        file_id = uuid.uuid4().hex[:12]
        safe_name = f"{file_id}{ext}"
        dest = _event_dir(eid) / safe_name
        dest.write_bytes(content)

        # Update manifest — replace duplicate original filenames
        from datetime import datetime
        manifest = _load_manifest(eid)

        # Remove old entries with the same original filename (avoid duplicates)
        old_entries = [
            e for e in manifest
            if e.get("filename") == file.filename
        ]
        for old in old_entries:
            old_path = _event_dir(eid) / old["stored_name"]
            if old_path.exists():
                old_path.unlink()
        manifest = [
            e for e in manifest
            if e.get("filename") != file.filename
        ]

        entry = {
            "id": file_id,
            "filename": file.filename,
            "stored_name": safe_name,
            "type": file_type,
            "content_type": file.content_type,
            "size": len(content),
            "uploaded_at": datetime.utcnow().isoformat(),
            "source": "agent_chat",
        }
        manifest.append(entry)
        _save_manifest(eid, manifest)
        filepath = str(dest)
    else:
        # Fallback: temp dir (no event context)
        ext = Path(file.filename or "file").suffix
        uid = uuid.uuid4().hex[:8]
        filename = f"{uid}{ext}"
        filepath = str(UPLOAD_DIR / filename)
        Path(filepath).write_bytes(content)

    return {
        "filename": file.filename,
        "path": filepath,
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
    badge_svc: BadgeTemplateService = Depends(get_badge_template_service),
    checkin_svc: CheckinService = Depends(get_checkin_service),
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

    # Pre-populate user_profile from JWT organizer (skip identity plugin)
    if not session.get("user_profile") and organizer:
        session["user_profile"] = {
            "name": getattr(organizer, "name", None) or getattr(organizer, "email", ""),
            "organizer_id": str(getattr(organizer, "id", "")),
            "role": "organizer",
        }

    if event_id:
        session["event_id"] = event_id

    # Process file uploads
    new_attachments = []
    for f in files:
        if f.filename:
            att = await _save_upload(f, event_id=event_id)
            new_attachments.append(att)

    # Build user message content (multimodal when images present)
    if new_attachments:
        session["attachments"] = new_attachments
        user_msg = _build_multimodal_message(msg, new_attachments)
    else:
        user_msg = HumanMessage(content=msg)
    session["messages"].append(user_msg)

    # Build services and graph
    services = _build_services(event_svc, att_svc, seat_svc, badge_svc, checkin_svc)
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
        "plan_output": None,
        "attachments": session.get("attachments", []),
        "task_plan": session.get("task_plan", []),
        "event_draft": session.get("event_draft"),
        "scope": scope,
        "parts": [],
        "tool_calls": [],
        "quick_replies": [],
        "reflection": None,
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
    if result.get("event_draft"):
        session["event_draft"] = result["event_draft"]

    # Clear attachments after processing (but keep event_draft)
    if new_attachments:
        session["attachments"] = []

    session["messages"].append(AIMessage(content=reply_text))

    action_taken = _detect_action(reply_text)
    task_plan = session.get("task_plan") or None

    # Collect tool call info from graph result
    raw_tool_calls = result.get("tool_calls") or []
    tool_calls_out = [
        ToolCallInfo(
            tool_name=tc.get("tool_name", ""),
            tool_name_zh=tc.get("tool_name_zh", tc.get("tool_name", "")),
            status=tc.get("status", "success"),
            summary=tc.get("summary", ""),
        )
        for tc in raw_tool_calls
    ] or None

    # Build quick replies from graph result
    raw_qr = result.get("quick_replies") or []
    quick_replies_out = [
        QuickReplyItem(
            label=qr.get("label", ""),
            value=qr.get("value", qr.get("label", "")),
            style=qr.get("style", "default"),
        )
        for qr in raw_qr
        if qr.get("label")
    ] or None

    # Extract reflection data
    reflection_data = result.get("reflection")
    reflection_out = None
    if reflection_data:
        reflection_out = ReflectionInfo(
            score=reflection_data.get("score", 1.0),
            passed=reflection_data.get("passed", True),
            issues=reflection_data.get("issues", []),
            suggestions=reflection_data.get("suggestions", []),
            metrics=reflection_data.get("metrics", {}),
        )

    # Extract structured parts
    raw_parts = result.get("parts") or []
    parts_out = raw_parts if raw_parts else None

    return ChatResponse(
        reply=reply_text,
        session_id=sid,
        event_id=session.get("event_id"),
        action_taken=action_taken,
        task_plan=task_plan,
        tool_calls=tool_calls_out,
        quick_replies=quick_replies_out,
        reflection=reflection_out,
        parts=parts_out,
    )


# ── SSE streaming endpoint ────────────────────────────────────
@router.post("/chat/stream")
async def agent_chat_stream(
    message: str = Form(...),
    event_id: str | None = Form(None),
    session_id: str | None = Form(None),
    scope: str | None = Form(None),
    files: list[UploadFile] = File(default=[]),
    organizer=Depends(get_current_organizer),
    event_svc: EventService = Depends(get_event_service),
    att_svc: AttendeeService = Depends(get_attendee_service),
    seat_svc: SeatingService = Depends(get_seating_service),
    badge_svc: BadgeTemplateService = Depends(get_badge_template_service),
    checkin_svc: CheckinService = Depends(get_checkin_service),
):
    """Stream agent progress via Server-Sent Events (SSE).

    Same params as /chat, but returns text/event-stream.
    Events:
      - thinking: LLM is processing
      - tool_start: tool execution starting
      - tool_end: tool execution completed (with status)
      - done: final result (full ChatResponse JSON)
      - error: something went wrong
    """
    import json as _json
    from starlette.responses import StreamingResponse
    from agents.react import PROGRESS_QUEUE

    sid, session = _get_session(session_id)
    msg = message.strip()

    if not session.get("user_profile") and organizer:
        session["user_profile"] = {
            "name": getattr(organizer, "name", None) or getattr(organizer, "email", ""),
            "organizer_id": str(getattr(organizer, "id", "")),
            "role": "organizer",
        }
    if event_id:
        session["event_id"] = event_id

    new_attachments = []
    for f in files:
        if f.filename:
            att = await _save_upload(f, event_id=event_id)
            new_attachments.append(att)

    if new_attachments:
        session["attachments"] = new_attachments
        user_msg = _build_multimodal_message(msg, new_attachments)
    else:
        user_msg = HumanMessage(content=msg)
    session["messages"].append(user_msg)

    services = _build_services(event_svc, att_svc, seat_svc, badge_svc, checkin_svc)
    try:
        graph = _get_graph(services)
    except ValueError as e:
        async def _err_gen():
            yield f"data: {_json.dumps({'event': 'error', 'message': f'LLM 未配置：{e}'})}\n\n"
        return StreamingResponse(_err_gen(), media_type="text/event-stream")

    initial_state = {
        "messages": list(session["messages"][-20:]),
        "current_plugin": "",
        "user_profile": session.get("user_profile"),
        "event_id": session.get("event_id"),
        "pending_approval": None,
        "turn_output": None,
        "plan_output": None,
        "attachments": session.get("attachments", []),
        "task_plan": session.get("task_plan", []),
        "event_draft": session.get("event_draft"),
        "scope": scope,
        "parts": [],
        "tool_calls": [],
        "quick_replies": [],
        "reflection": None,
    }

    async def _event_stream():
        import asyncio

        queue: asyncio.Queue = asyncio.Queue()
        token = PROGRESS_QUEUE.set(queue)

        # Run graph in background task
        graph_task = asyncio.create_task(graph.ainvoke(initial_state))

        try:
            while not graph_task.done():
                try:
                    evt = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield f"data: {_json.dumps(evt, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    # Send heartbeat to keep connection alive
                    yield ": heartbeat\n\n"

            # Drain remaining events
            while not queue.empty():
                evt = await queue.get()
                yield f"data: {_json.dumps(evt, ensure_ascii=False)}\n\n"

            # Get final result
            result = graph_task.result()
            reply_text = result.get("turn_output", "")
            if not reply_text:
                for m in reversed(result.get("messages", [])):
                    if isinstance(m, AIMessage):
                        reply_text = m.content
                        break
            if not reply_text:
                reply_text = "抱歉，我没有理解您的意思，能再说一次吗？"

            # Update session
            if result.get("event_id"):
                session["event_id"] = result["event_id"]
            if result.get("user_profile"):
                session["user_profile"] = result["user_profile"]
            if result.get("task_plan"):
                session["task_plan"] = result["task_plan"]
            if result.get("event_draft"):
                session["event_draft"] = result["event_draft"]
            if new_attachments:
                session["attachments"] = []
            session["messages"].append(AIMessage(content=reply_text))

            # Build final response
            raw_tc = result.get("tool_calls") or []
            tc_out = [
                {
                    "tool_name": tc.get("tool_name", ""),
                    "tool_name_zh": tc.get("tool_name_zh", ""),
                    "status": tc.get("status", "success"),
                    "summary": tc.get("summary", ""),
                }
                for tc in raw_tc
            ]

            # Build quick replies
            raw_qr = result.get("quick_replies") or []
            qr_out = [
                {
                    "label": qr.get("label", ""),
                    "value": qr.get("value", qr.get("label", "")),
                    "style": qr.get("style", "default"),
                }
                for qr in raw_qr
                if qr.get("label")
            ] or None

            reflection_data = result.get("reflection")
            raw_parts = result.get("parts") or []
            done_data = {
                "event": "done",
                "reply": reply_text,
                "session_id": sid,
                "event_id": session.get("event_id"),
                "action_taken": _detect_action(reply_text),
                "tool_calls": tc_out or None,
                "quick_replies": qr_out,
                "reflection": reflection_data,
                "parts": raw_parts or None,
            }
            yield f"data: {_json.dumps(done_data, ensure_ascii=False)}\n\n"

        except Exception as e:
            err = {"event": "error", "message": str(e)}
            yield f"data: {_json.dumps(err, ensure_ascii=False)}\n\n"
            # Also store error in session
            session["messages"].append(
                AIMessage(content=f"Agent 执行出错：{e}"),
            )
        finally:
            PROGRESS_QUEUE.reset(token)

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── JSON-only endpoint (simple text chat, no files) ───────────
@router.post("/chat/text", response_model=ChatResponse)
async def agent_chat_text(
    body: dict,
    organizer=Depends(get_current_organizer),
    event_svc: EventService = Depends(get_event_service),
    att_svc: AttendeeService = Depends(get_attendee_service),
    seat_svc: SeatingService = Depends(get_seating_service),
    badge_svc: BadgeTemplateService = Depends(get_badge_template_service),
    checkin_svc: CheckinService = Depends(get_checkin_service),
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

    services = _build_services(event_svc, att_svc, seat_svc, badge_svc, checkin_svc)
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
        "plan_output": None,
        "attachments": [],
        "task_plan": session.get("task_plan", []),
        "event_draft": session.get("event_draft"),
        "parts": [],
        "tool_calls": [],
        "quick_replies": [],
        "reflection": None,
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
    if result.get("event_draft"):
        session["event_draft"] = result["event_draft"]

    session["messages"].append(AIMessage(content=reply_text))

    raw_tc = result.get("tool_calls") or []
    tc_out = [
        ToolCallInfo(
            tool_name=tc.get("tool_name", ""),
            tool_name_zh=tc.get("tool_name_zh", tc.get("tool_name", "")),
            status=tc.get("status", "success"),
            summary=tc.get("summary", ""),
        )
        for tc in raw_tc
    ] or None

    raw_qr = result.get("quick_replies") or []
    qr_out = [
        QuickReplyItem(
            label=qr.get("label", ""),
            value=qr.get("value", qr.get("label", "")),
            style=qr.get("style", "default"),
        )
        for qr in raw_qr
        if qr.get("label")
    ] or None

    raw_parts = result.get("parts") or []

    return ChatResponse(
        reply=reply_text,
        session_id=sid,
        event_id=session.get("event_id"),
        action_taken=_detect_action(reply_text),
        task_plan=session.get("task_plan") or None,
        tool_calls=tc_out,
        quick_replies=qr_out,
        parts=raw_parts or None,
    )


# ── Feedback endpoint (👍👎 for self-evolution) ──────────────

class FeedbackRequest(BaseModel):
    event_id: str
    feedback: int  # +1 or -1
    session_id: str | None = None


class FeedbackResponse(BaseModel):
    ok: bool
    message: str


@router.post("/chat/feedback", response_model=FeedbackResponse)
async def agent_feedback(
    body: FeedbackRequest,
    organizer=Depends(get_current_organizer),
):
    """Record user feedback (+1/-1) on the last agent interaction.

    This feeds the self-evolution system:
    - Updates event memory records
    - Updates prompt version scoring
    - Triggers A/B candidate evaluation
    """
    from agents.memory import record_user_feedback

    try:
        record_user_feedback(
            event_id=body.event_id,
            feedback=body.feedback,
        )
    except Exception:
        pass  # Memory feedback is best-effort

    action = "positive" if body.feedback > 0 else "negative"
    return FeedbackResponse(
        ok=True,
        message=f"已记录{action}反馈，Agent 将据此优化。",
    )


@router.get("/chat/stats/{event_id}")
async def agent_stats(
    event_id: str,
    organizer=Depends(get_current_organizer),
):
    """Get agent interaction stats for an event.

    Returns aggregated quality scores, feedback counts, and
    plugin usage breakdown.
    """
    from agents.memory import get_event_stats
    return get_event_stats(event_id)


def _detect_action(reply: str) -> str | None:
    """Detect what action was taken from the reply text."""
    if "已创建" in reply and "活动" in reply:
        return "event_created"
    if ("生成" in reply or "已从" in reply) and "座位" in reply:
        return "seats_generated"
    if "排座完成" in reply or "分配" in reply:
        return "seats_assigned"
    if "签到成功" in reply:
        return "checkin_done"
    if "任务计划" in reply:
        return "plan_created"
    if "设为" in reply and "区" in reply:
        return "zone_updated"
    return None
