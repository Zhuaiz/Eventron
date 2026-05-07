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

# Image content types we can resize via Pillow.
_RESIZABLE_IMAGE_TYPES = {
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp",
}


def _resized_path(src: Path, max_dim: int) -> Path:
    """Return a path under .cache/ that holds the same image scaled so
    neither dimension exceeds ``max_dim``. Aspect preserved, no upscaling.

    Generation is lazy — first request resizes and caches; subsequent
    requests serve the cached file directly. Re-encoded for compactness:
    JPEG q=85, PNG with optimize=True. GIF/BMP fall through to original
    (rare path; not worth the complexity to re-encode).
    """
    from PIL import Image

    cache_dir = src.parent / ".cache"
    suffix = src.suffix.lower()
    cache_path = cache_dir / f"{src.stem}_w{max_dim}{suffix}"
    if cache_path.exists():
        return cache_path

    try:
        with Image.open(src) as im:
            ow, oh = im.size
            if max(ow, oh) <= max_dim:
                # Already small enough — never upscale.
                return src

            if ow >= oh:
                new_w = max_dim
                new_h = round(oh * (max_dim / ow))
            else:
                new_h = max_dim
                new_w = round(ow * (max_dim / oh))

            cache_dir.mkdir(parents=True, exist_ok=True)
            resized = im.resize((new_w, new_h), Image.Resampling.LANCZOS)

            if suffix in (".jpg", ".jpeg"):
                if resized.mode != "RGB":
                    resized = resized.convert("RGB")
                resized.save(cache_path, "JPEG", quality=85, optimize=True)
            elif suffix == ".png":
                resized.save(cache_path, "PNG", optimize=True)
            elif suffix == ".webp":
                resized.save(cache_path, "WEBP", quality=85)
            else:
                # GIF/BMP — just save as-is at the new size.
                resized.save(cache_path)
    except Exception:
        # Any decode/encode failure → fall back to original.
        return src

    return cache_path


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
    w: int | None = Query(
        None, ge=16, le=4096,
        description=(
            "For images: cap longer side to this many pixels (preserves"
            " aspect, never upscales). Useful when embedding the image"
            " on a mobile page — pass w=1080 to avoid downloading the"
            " full-resolution original."
        ),
    ),
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

    # On-the-fly resize: only for image content with ?w= specified.
    # Keeps the URL stable (file_id) while letting consumers ask for the
    # version that fits their viewport. Cached on disk under .cache/.
    if w and media_type in _RESIZABLE_IMAGE_TYPES:
        filepath = _resized_path(filepath, w)

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
