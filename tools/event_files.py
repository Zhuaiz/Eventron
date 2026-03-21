"""Event file tools — pure filesystem helpers for reading event files.

These functions read the event file manifest and return file metadata/paths.
No DB, no HTTP, no state — just filesystem reads. Can be used by both
API routes and agent plugins.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

UPLOAD_ROOT = Path("uploads/events")


def event_dir(event_id: uuid.UUID | str) -> Path:
    """Get (and ensure exists) the upload directory for an event."""
    d = UPLOAD_ROOT / str(event_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_manifest(event_id: uuid.UUID | str) -> list[dict[str, Any]]:
    """Load the file manifest for an event. Returns [] if none."""
    mp = event_dir(event_id) / ".manifest.json"
    if mp.exists():
        return json.loads(mp.read_text())
    return []


def save_manifest(
    event_id: uuid.UUID | str, files: list[dict[str, Any]]
) -> None:
    """Save the file manifest for an event."""
    mp = event_dir(event_id) / ".manifest.json"
    mp.write_text(json.dumps(files, ensure_ascii=False, indent=2))


def get_file_path(
    event_id: uuid.UUID | str, file_id: str
) -> Path | None:
    """Get the absolute path of a stored event file, or None."""
    manifest = load_manifest(event_id)
    entry = next((f for f in manifest if f["id"] == file_id), None)
    if not entry:
        return None
    p = event_dir(event_id) / entry["stored_name"]
    return p if p.exists() else None


def find_files_by_type(
    event_id: uuid.UUID | str, file_type: str
) -> list[dict[str, Any]]:
    """Find all event files of a given type (image/excel/pdf/unknown).

    Returns manifest entries with an extra 'path' key pointing to
    the absolute file path on disk.
    """
    manifest = load_manifest(event_id)
    results = []
    for entry in manifest:
        if entry.get("type") != file_type:
            continue
        p = event_dir(event_id) / entry["stored_name"]
        if p.exists():
            results.append({**entry, "path": str(p)})
    return results


def find_latest_file_by_type(
    event_id: uuid.UUID | str, file_type: str
) -> dict[str, Any] | None:
    """Find the most recently uploaded file of a given type.

    Returns manifest entry with 'path' key, or None.
    """
    files = find_files_by_type(event_id, file_type)
    if not files:
        return None
    # Manifest is append-only, so last entry is most recent
    return files[-1]
