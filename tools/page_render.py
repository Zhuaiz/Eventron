"""Check-in page rendering — pure tool, no DB or HTTP.

Uses Jinja2 to produce self-contained H5 check-in pages.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "pages"


def _load_css(name: str) -> str:
    css_path = TEMPLATE_DIR / f"{name}.css"
    if css_path.exists():
        return css_path.read_text(encoding="utf-8")
    return ""


def render_checkin_page(
    event_name: str,
    event_date: str = "",
    event_location: str = "",
    mode: str = "name",
    total: int = 0,
    checked_in: int = 0,
    custom_html: str | None = None,
    custom_css: str | None = None,
) -> str:
    """Render a standalone H5 check-in page.

    Args:
        event_name: Event display name.
        event_date: Formatted date string.
        event_location: Venue location text.
        mode: "qr" for QR scanner or "name" for name search.
        total: Total attendee count.
        checked_in: Already checked-in count.
        custom_html: Optional custom Jinja2 HTML template.
        custom_css: Optional custom CSS.

    Returns:
        Complete HTML string (self-contained, can be served or saved).
    """
    rate = round(checked_in / total * 100) if total > 0 else 0

    if custom_html:
        env = Environment(autoescape=False)
        tpl = env.from_string(custom_html)
        css = custom_css or ""
    else:
        env = Environment(
            loader=FileSystemLoader(str(TEMPLATE_DIR)),
            autoescape=False,
        )
        tpl = env.get_template("checkin.html")
        css = _load_css("checkin")

    return tpl.render(
        event_name=event_name,
        event_date=event_date,
        event_location=event_location,
        mode=mode,
        total=total,
        checked_in=checked_in,
        rate=rate,
        css=css,
    )
