"""File extraction tools — pure functions to extract structured data from files.

These tools process uploaded files (images, PDFs, Excel) and return
structured event information. They do NOT access the database or network.

For images, the caller must provide the base64 data and use an LLM with
vision capabilities. This tool just builds the prompt.
"""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any


def _detect_image_mime(data: bytes, filename: str = "") -> str:
    """Detect actual image MIME from file header magic bytes."""
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
    return mimetypes.guess_type(filename)[0] or "image/png"


def build_vision_prompt(filename: str) -> str:
    """Build an LLM prompt for extracting event info from an image.

    Args:
        filename: Original filename for context.

    Returns:
        System prompt string for vision LLM.
    """
    return """你是一个专业的活动信息提取器。请仔细分析这张图片，提取所有活动相关信息。

请提取以下字段（JSON格式），找不到的字段用 null：
```json
{
  "event_name": "活动名称",
  "event_date": "YYYY-MM-DD",
  "event_time": "HH:MM-HH:MM",
  "location": "活动地点",
  "venue_name": "场馆名称",
  "organizer": "主办方",
  "schedule": [
    {"time": "HH:MM", "activity": "活动内容"}
  ],
  "participants": "参会人群描述",
  "notes": "备注/提醒",
  "estimated_attendees": 估计人数或null,
  "layout_suggestion": "theater|classroom|roundtable|banquet|u_shape",
  "badge_info": {
    "style": "formal|casual|tech|government",
    "needs_photo": true/false,
    "bilingual": true/false
  }
}
```

分析完图片后，再给出一段中文总结，说明你理解的活动需求和你的建议。"""


def build_vision_message(
    image_path: str, filename: str
) -> list[dict[str, Any]]:
    """Build a multimodal LLM message with image content.

    Args:
        image_path: Path to the image file on disk.
        filename: Original filename.

    Returns:
        List of message dicts ready for LLM invocation.
    """
    # Read and encode image
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    raw = path.read_bytes()
    mime_type = _detect_image_mime(raw, filename)
    b64 = base64.b64encode(raw).decode("utf-8")

    system_prompt = build_vision_prompt(filename)

    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{b64}",
                    },
                },
                {
                    "type": "text",
                    "text": f"请分析这张图片（{filename}），提取活动信息。",
                },
            ],
        },
    ]


def extract_from_excel(file_path: str) -> dict[str, Any]:
    """Extract attendee data from Excel file.

    Args:
        file_path: Path to .xlsx file.

    Returns:
        Dict with 'headers', 'rows', 'row_count', 'summary'.
    """
    from tools.excel_io import read_excel

    result = read_excel(file_path)
    rows = result.get("rows", [])
    headers = result.get("headers", [])

    # Analyze content
    summary_parts = [f"共 {len(rows)} 行数据"]
    if headers:
        summary_parts.append(f"列: {', '.join(headers[:10])}")

    # Try to detect name/title/org columns
    name_cols = [
        h for h in headers
        if any(kw in h.lower() for kw in ["姓名", "name", "名字"])
    ]
    if name_cols:
        summary_parts.append(f"姓名列: {name_cols[0]}")

    return {
        "headers": headers,
        "rows": rows[:5],  # Preview first 5 rows
        "row_count": len(rows),
        "summary": "，".join(summary_parts),
    }


def extract_from_pdf(file_path: str) -> dict[str, Any]:
    """Extract text from PDF file.

    Args:
        file_path: Path to .pdf file.

    Returns:
        Dict with 'text', 'page_count', 'summary'.
    """
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(file_path)
        pages = []
        for page in doc:
            pages.append(page.get_text())
        doc.close()

        full_text = "\n---\n".join(pages)
        return {
            "text": full_text[:5000],  # Truncate
            "page_count": len(pages),
            "summary": f"PDF共{len(pages)}页，已提取文本",
        }
    except ImportError:
        return {
            "text": "",
            "page_count": 0,
            "summary": "PDF解析库未安装(PyMuPDF)",
        }


def detect_file_type(filename: str) -> str:
    """Detect file category from filename.

    Returns:
        'image', 'excel', 'pdf', or 'unknown'.
    """
    ext = Path(filename).suffix.lower()
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
        return "image"
    if ext in (".xlsx", ".xls", ".csv"):
        return "excel"
    if ext == ".pdf":
        return "pdf"
    return "unknown"
