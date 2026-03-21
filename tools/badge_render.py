"""Badge / tent-card PDF rendering — pure tool, no DB or HTTP.

Uses Jinja2 for HTML templating and WeasyPrint for PDF generation.
All data is passed in as plain dicts by the calling agent/service.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "badges"

# Font stack that works across Linux (Docker), macOS, and Windows.
# "Droid Sans Fallback" is the most universally available CJK font on Linux.
CJK_FONT_STACK = (
    '"Noto Sans CJK SC", "Noto Sans SC", "Source Han Sans SC", '
    '"Droid Sans Fallback", "PingFang SC", "Microsoft YaHei", '
    '"Helvetica Neue", sans-serif'
)

# Priority tier display labels (Chinese)
# Higher priority = more important.  Role labels are now free-text,
# so we fall back to the attendee's own role string.
PRIORITY_TIER_LABELS: dict[str, str] = {
    "high": "贵宾",   # priority >= 10
    "mid": "嘉宾",    # 1 <= priority < 10
    "normal": "参会者",  # priority == 0
}

# Built-in template name → (html file, css file)
BUILTIN_TEMPLATES: dict[str, tuple[str, str]] = {
    "business": ("business.html", "business.css"),
    "conference": ("conference.html", "conference.css"),
    "tent_card": ("tent_card.html", "tent_card.css"),
}


def _load_builtin_css(css_filename: str) -> str:
    """Load CSS from the templates/badges/ directory."""
    css_path = TEMPLATE_DIR / css_filename
    if css_path.exists():
        return css_path.read_text(encoding="utf-8")
    return ""


def _role_color(role: str) -> tuple[str, str]:
    """Generate a deterministic background + text color for a role label.

    Returns (bg_color, text_color) as CSS hex strings.
    """
    palette = [
        ("#e2b93b", "#1a1a2e"),  # gold
        ("#e94560", "#ffffff"),  # red
        ("#0f9b58", "#ffffff"),  # green
        ("#4a90d9", "#ffffff"),  # blue
        ("#9b59b6", "#ffffff"),  # purple
        ("#00b894", "#ffffff"),  # teal
        ("#fd79a8", "#ffffff"),  # pink
        ("#636e72", "#ffffff"),  # gray
        ("#0984e3", "#ffffff"),  # bright blue
        ("#d63031", "#ffffff"),  # bright red
    ]
    # Simple hash to pick consistent color per role
    h = sum(ord(c) for c in role) if role else 0
    bg, text = palette[h % len(palette)]
    # "参会者" gets a muted default
    if role in ("参会者", ""):
        return ("rgba(255,255,255,0.15)", "#ffffff")
    return bg, text


def _prepare_attendees(
    attendees: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Enrich attendee dicts with role_label, role_color, role_text, qr_data."""
    result = []
    for att in attendees:
        enriched = dict(att)
        # Use the attendee's free-text role directly as the badge label.
        # Fall back to a priority-tier label if role is generic.
        role = att.get("role", "参会者")
        pri = att.get("priority", 0)
        if role in ("参会者", "") or not role:
            if pri >= 10:
                role = PRIORITY_TIER_LABELS["high"]
            elif pri >= 1:
                role = PRIORITY_TIER_LABELS["mid"]
            else:
                role = PRIORITY_TIER_LABELS["normal"]
        enriched["role_label"] = role
        bg, text = _role_color(role)
        enriched["role_color"] = bg
        enriched["role_text"] = text
        # qr_data can be a base64 data-uri set by the caller
        if "qr_data" not in enriched:
            enriched["qr_data"] = ""
        result.append(enriched)
    return result


def render_badges_html(
    attendees: list[dict[str, Any]],
    event_name: str,
    event_date: str = "",
    template_name: str = "business",
    custom_html: str | None = None,
    custom_css: str | None = None,
) -> str:
    """Render badge HTML from a built-in or custom template.

    Args:
        attendees: List of attendee dicts (name, title, organization, role).
        event_name: Display name of the event.
        event_date: Optional formatted date string.
        template_name: Built-in template key ("business" or "tent_card").
        custom_html: If provided, use this Jinja2 HTML instead of built-in.
        custom_css: If provided, use this CSS instead of built-in.

    Returns:
        Rendered HTML string ready for WeasyPrint.
    """
    enriched = _prepare_attendees(attendees)

    if custom_html:
        # Use custom template from BadgeTemplate.html_template
        env = Environment(autoescape=False)
        tpl = env.from_string(custom_html)
        css = custom_css or ""
        # Ensure CJK fonts are available even in custom templates
        if "Droid Sans" not in css and "Noto Sans" not in css:
            css = f"body {{ font-family: {CJK_FONT_STACK}; }}\n{css}"
    else:
        # Use built-in file template
        if template_name not in BUILTIN_TEMPLATES:
            template_name = "business"
        html_file, css_file = BUILTIN_TEMPLATES[template_name]
        env = Environment(
            loader=FileSystemLoader(str(TEMPLATE_DIR)),
            autoescape=False,
        )
        tpl = env.get_template(html_file)
        css = _load_builtin_css(css_file)

    return tpl.render(
        attendees=enriched,
        event_name=event_name,
        event_date=event_date,
        css=css,
    )


def render_badges_pdf(
    attendees: list[dict[str, Any]],
    event_name: str,
    event_date: str = "",
    template_name: str = "business",
    custom_html: str | None = None,
    custom_css: str | None = None,
    output_path: str | Path | None = None,
) -> bytes:
    """Render badges as PDF bytes.

    Args:
        attendees: List of attendee dicts.
        event_name: Event display name.
        event_date: Optional date string.
        template_name: Built-in template key.
        custom_html: Optional custom Jinja2 HTML.
        custom_css: Optional custom CSS.
        output_path: If provided, also write PDF to this file path.

    Returns:
        PDF content as bytes.
    """
    from weasyprint import HTML  # lazy import — heavy dependency

    html_str = render_badges_html(
        attendees=attendees,
        event_name=event_name,
        event_date=event_date,
        template_name=template_name,
        custom_html=custom_html,
        custom_css=custom_css,
    )

    pdf_bytes = HTML(string=html_str).write_pdf()

    if output_path:
        Path(output_path).write_bytes(pdf_bytes)

    return pdf_bytes
