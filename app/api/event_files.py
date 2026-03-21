"""Event file management — upload, list, delete reference files per event.

Files are stored on disk under /uploads/events/{event_id}/ and tracked
in a simple JSON manifest. These files are available to all sub-agents
for context (e.g. venue photos, invitation images, attendee lists).
"""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from starlette.responses import Response as StarletteResponse

from app.api.auth import get_current_organizer
from app.deps import get_event_service
from app.services.event_service import EventService
from app.services.exceptions import EventNotFoundError
from tools.event_files import (
    event_dir as _event_dir,
    load_manifest as _load_manifest,
    save_manifest as _save_manifest,
)
from tools.file_extract import detect_file_type

router = APIRouter()

UPLOAD_ROOT = Path("uploads/events")

ALLOWED_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp",
    ".xlsx", ".xls", ".csv",
    ".pdf",
    ".doc", ".docx",
    ".pptx",
}

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB

# Content types that browsers can render inline (preview, not download).
INLINE_CONTENT_TYPES = {
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp",
    "application/pdf",
}


@router.post("/events/{event_id}/files")
async def upload_event_file(
    event_id: uuid.UUID,
    file: UploadFile = File(...),
    organizer=Depends(get_current_organizer),
    event_svc: EventService = Depends(get_event_service),
):
    """Upload a reference file to an event."""
    try:
        await event_svc.get_event(event_id)
    except EventNotFoundError:
        raise HTTPException(status_code=404, detail="Event not found")

    # Validate
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename")
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式: {ext}",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400, detail="文件不能超过 20MB"
        )

    # Save file
    file_id = uuid.uuid4().hex[:12]
    safe_name = f"{file_id}{ext}"
    dest = _event_dir(event_id) / safe_name
    dest.write_bytes(content)

    # Update manifest — replace duplicate original filenames
    manifest = _load_manifest(event_id)

    # Remove old entries with the same original filename
    old_entries = [e for e in manifest if e.get("filename") == file.filename]
    for old in old_entries:
        old_path = _event_dir(event_id) / old["stored_name"]
        if old_path.exists():
            old_path.unlink()
    manifest = [e for e in manifest if e.get("filename") != file.filename]

    file_type = detect_file_type(file.filename)
    entry = {
        "id": file_id,
        "filename": file.filename,
        "stored_name": safe_name,
        "type": file_type,
        "content_type": file.content_type,
        "size": len(content),
        "uploaded_at": datetime.utcnow().isoformat(),
    }
    manifest.append(entry)
    _save_manifest(event_id, manifest)

    return entry


@router.get("/events/{event_id}/files")
async def list_event_files(
    event_id: uuid.UUID,
    organizer=Depends(get_current_organizer),
    event_svc: EventService = Depends(get_event_service),
):
    """List all files uploaded to an event."""
    try:
        await event_svc.get_event(event_id)
    except EventNotFoundError:
        raise HTTPException(status_code=404, detail="Event not found")
    return _load_manifest(event_id)


@router.get("/events/{event_id}/files/{file_id}")
async def get_event_file(
    event_id: uuid.UUID,
    file_id: str,
    download: bool = Query(False, description="Force download instead of inline preview"),
):
    """Download/view a specific event file.

    No auth required — file IDs are unguessable UUIDs.
    This allows direct browser links (``<a href=...>``) to work
    without needing an Authorization header.

    For images and PDFs the default disposition is ``inline`` so
    the browser renders a preview.  Pass ``?download=1`` to force
    a download with the original filename.
    """
    manifest = _load_manifest(event_id)
    entry = next((f for f in manifest if f["id"] == file_id), None)
    if not entry:
        raise HTTPException(status_code=404, detail="File not found")

    filepath = _event_dir(event_id) / entry["stored_name"]
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="File missing")

    media_type = entry.get("content_type", "application/octet-stream")
    filename = entry["filename"]
    encoded = quote(filename)

    # Inline preview for images / PDFs; attachment for everything else.
    if not download and media_type in INLINE_CONTENT_TYPES:
        disposition = f"inline; filename*=UTF-8''{encoded}"
    else:
        disposition = f"attachment; filename*=UTF-8''{encoded}"

    return FileResponse(
        path=str(filepath),
        media_type=media_type,
        headers={"Content-Disposition": disposition},
    )


@router.delete("/events/{event_id}/files/{file_id}")
async def delete_event_file(
    event_id: uuid.UUID,
    file_id: str,
    organizer=Depends(get_current_organizer),
):
    """Delete an event file."""
    manifest = _load_manifest(event_id)
    entry = next((f for f in manifest if f["id"] == file_id), None)
    if not entry:
        raise HTTPException(status_code=404, detail="File not found")

    filepath = _event_dir(event_id) / entry["stored_name"]
    if filepath.exists():
        filepath.unlink()

    manifest = [f for f in manifest if f["id"] != file_id]
    _save_manifest(event_id, manifest)

    return {"ok": True}
