"""LangChain tools for the check-in / page-gen agent.

Each tool is a thin async wrapper around services + pure tools.
The LLM decides WHEN and WHICH to call via ReAct loop.

Design: same closure pattern as seating_tools.py.

Key design decision (Phase 11 v2):
  `deploy_custom_checkin_page` takes a SHORT design description, NOT raw
  HTML. The tool internally calls a dedicated LLM to generate the HTML/CSS
  based on the description + event info. This avoids the fundamental issue
  of LLMs failing to produce thousands of chars in a tool-call argument.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from langchain_core.tools import tool


# ── Generation prompt for internal LLM call ───────────────────
# The LLM generates a COMPLETE HTML page (<!DOCTYPE> through </html>).
# The tool only injects EVENT_ID + checkin JS before </body>.
_GEN_PROMPT = """\
你是一个专业的移动端 H5 页面设计师。请根据用户的设计要求生成一个 **完整的** 签到页面。

## 活动信息
- 名称: {event_name}
- 日期: {event_date}
- 地点: {event_location}

## 用户设计要求
{design_description}

## 输出格式
输出一个完整的 HTML 文件（从 <!DOCTYPE html> 到 </html>），放在一个 ```html 代码块中。
CSS 样式必须写在 <head> 内的 <style> 标签中，不要分开输出。

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, \
maximum-scale=1.0, user-scalable=no">
  <title>活动签到</title>
  <style>
    /* 所有 CSS 写在这里 */
  </style>
</head>
<body>
  <!-- 页面内容 -->
</body>
</html>
```

## 必须包含的 HTML 元素（签到 JS 依赖这些 ID）
在 <body> 中必须包含以下结构（可调整样式、class、顺序，但 ID 必须保留）:

1. 搜索区:
<section id="search-section">
  <form id="checkin-form" onsubmit="return false;">
    <input type="text" id="name-input" placeholder="请输入您的姓名" \
autocomplete="off" autofocus>
    <button type="button" id="search-btn" onclick="doSearch()">签到</button>
  </form>
</section>

2. 结果区（初始隐藏）:
<section id="result-section" style="display:none;"></section>

3. 同名消歧区（初始隐藏）:
<section id="candidates-section" style="display:none;">
  <p>找到多位同名人员，请选择：</p>
  <div id="candidates-list"></div>
</section>

4. 签到成功区（初始隐藏）:
<section id="success-section" style="display:none;">
  <div class="success-icon">✓</div>
  <h2 id="success-name"></h2>
  <p id="success-msg">签到成功</p>
  <div id="seat-info" style="display:none;">\
<span id="seat-label"></span></div>
  <button onclick="resetPage()">返回</button>
</section>

## 设计原则
- 移动端优先（max-width: 440px 居中）
- 视觉美观，符合现代 H5 签到页设计
- 活动名称醒目展示
- 搜索区域突出，输入框和按钮易于点击
- 丰富的 CSS 样式：渐变背景、圆角、阴影、过渡动画等
- 如用户没要求统计栏，就不加
- 将真实活动名称/日期/地点直接写入 HTML
- 不要写任何 <script>，JS 会由系统自动注入"""


def _extract_full_page(text: str) -> str:
    """Extract a complete HTML page from LLM response text.

    Tries multiple extraction strategies:
    1. ```html code block containing <!DOCTYPE or <html
    2. Any code block containing <!DOCTYPE or <html
    3. Raw HTML from <!DOCTYPE to </html> in the text itself

    Returns the full HTML string, or empty string on failure.
    """
    # 1. Labeled ```html code block
    html_blocks = re.findall(
        r"```html\s*\n(.*?)```", text, re.DOTALL | re.IGNORECASE,
    )
    for block in html_blocks:
        block = block.strip()
        if "<!DOCTYPE" in block.upper() or "<html" in block.lower():
            return block

    # 2. Any code block with full HTML
    generic_blocks = re.findall(
        r"```\w*\s*\n(.*?)```", text, re.DOTALL,
    )
    for block in generic_blocks:
        block = block.strip()
        if "<!DOCTYPE" in block.upper() or "<html" in block.lower():
            return block

    # 3. Raw HTML in the response (no code fence)
    raw_match = re.search(
        r"(<!DOCTYPE\s+html[^>]*>.*?</html>)",
        text, re.DOTALL | re.IGNORECASE,
    )
    if raw_match:
        return raw_match.group(1).strip()

    # 4. Last resort — any code block with <style> and <body>
    for block in generic_blocks:
        block = block.strip()
        if "<style" in block.lower() and "<body" in block.lower():
            return block

    return ""


def _load_event_images(
    event_id: str, max_images: int = 2,
) -> list[dict[str, Any]]:
    """Load recent reference images from event file store.

    Returns list of image content parts for multimodal LLM message.
    """
    import base64

    event_dir = Path(f"uploads/events/{event_id}")
    manifest_path = event_dir / ".manifest.json"
    if not manifest_path.exists():
        return []

    try:
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8"),
        )
    except Exception:
        return []

    # Get latest uploaded images (sorted by upload time, newest first)
    images = [
        e for e in manifest if e.get("type") == "image"
    ]
    images.sort(
        key=lambda e: e.get("uploaded_at", ""), reverse=True,
    )

    parts: list[dict[str, Any]] = []
    for img in images[:max_images]:
        img_path = event_dir / img["stored_name"]
        if not img_path.exists():
            continue
        try:
            raw = img_path.read_bytes()
            # Detect MIME type
            if raw[:8] == b'\x89PNG\r\n\x1a\n':
                mime = "image/png"
            elif raw[:2] == b'\xff\xd8':
                mime = "image/jpeg"
            else:
                mime = img.get("content_type", "image/png")
            b64 = base64.b64encode(raw).decode()
            parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            })
        except Exception:
            continue

    return parts


def make_checkin_tools(
    event_id: str,
    checkin_svc: Any,
    event_svc: Any,
    attendee_svc: Any,
    llm: Any = None,
) -> list:
    """Build LangChain tools for check-in + page design agent.

    Args:
        event_id: UUID string of the current event.
        checkin_svc: CheckinService instance.
        event_svc: EventService instance.
        attendee_svc: AttendeeService instance.
        llm: LLM for internal page generation (optional but needed
            for deploy_custom_checkin_page).

    Returns:
        List of LangChain tool objects for ``llm.bind_tools()``.
    """
    eid = uuid.UUID(event_id)

    @tool
    async def get_event_info() -> str:
        """获取当前活动的基本信息（名称、日期、地点、状态、人数）。"""
        ev = await event_svc.get_event(eid)
        stats = await checkin_svc.get_checkin_stats(eid)
        return json.dumps({
            "name": ev.name,
            "event_date": str(ev.event_date) if ev.event_date else "",
            "location": ev.location or "",
            "status": ev.status,
            "total_attendees": stats["total"],
            "checked_in": stats["checked_in"],
            "checkin_rate": stats["rate"],
        }, ensure_ascii=False)

    @tool
    async def get_checkin_stats() -> str:
        """获取签到实时统计（总人数、已签到、剩余、签到率）。"""
        stats = await checkin_svc.get_checkin_stats(eid)
        return json.dumps(stats, ensure_ascii=False)

    @tool
    async def get_checkin_url() -> str:
        """获取签到页面的公开URL。参会者扫码后打开此地址即可签到。"""
        return json.dumps({
            "url": f"/p/{event_id}/checkin",
            "hint": "此为相对路径，实际部署时加上域名前缀",
        }, ensure_ascii=False)

    @tool
    async def generate_checkin_qr(base_url: str = "") -> str:
        """生成签到二维码（PNG base64）。

        Args:
            base_url: 域名前缀（如 https://example.com）。留空则用相对路径。
        """
        try:
            from tools.qr_gen import generate_checkin_qr as _qr
            qr_data = _qr(
                base_url=base_url or "https://your-domain.com",
                event_id=event_id,
            )
            return json.dumps({
                "qr_base64": qr_data,
                "url": (
                    f"{base_url or 'https://your-domain.com'}"
                    f"/p/{event_id}/checkin"
                ),
            }, ensure_ascii=False)
        except ImportError:
            return json.dumps({
                "error": "qrcode 模块未安装",
                "url": f"/p/{event_id}/checkin",
            }, ensure_ascii=False)

    @tool
    async def render_checkin_page() -> str:
        """生成默认签到页（内置模板），适用于快速启用签到功能。"""
        from tools.page_render import render_checkin_page as _render

        ev = await event_svc.get_event(eid)
        stats = await checkin_svc.get_checkin_stats(eid)

        html = _render(
            event_name=ev.name,
            event_date=str(ev.event_date) if ev.event_date else "",
            event_location=ev.location or "",
            mode="name",
            total=stats["total"],
            checked_in=stats["checked_in"],
            event_id=event_id,
        )

        upload_dir = Path(f"uploads/events/{event_id}")
        upload_dir.mkdir(parents=True, exist_ok=True)
        page_path = upload_dir / "checkin_page.html"
        page_path.write_text(html, encoding="utf-8")

        return json.dumps({
            "status": "ok",
            "url": f"/p/{event_id}/checkin",
            "message": "默认签到页已生成",
        }, ensure_ascii=False)

    @tool
    async def deploy_custom_checkin_page(
        design_description: str,
    ) -> str:
        """根据设计描述，自动生成并部署自定义签到页面。

        你只需传入简短的设计要求文字描述，工具内部会自动：
        1. 获取活动信息
        2. 生成符合要求的 HTML + CSS
        3. 注入签到交互 JS
        4. 部署页面

        Args:
            design_description: 设计要求描述。例如：
                "深蓝渐变背景，标题醒目居中，去掉底部统计栏，现代简约风"
                "白色简约风格，logo区域大，搜索框突出"
                "参考科技感设计，紫色主题，动效背景"
        """
        from tools.page_render import _load_js

        if not llm:
            return json.dumps({
                "status": "error",
                "message": "LLM 未配置，无法生成自定义页面",
            }, ensure_ascii=False)

        # 1. Fetch event info
        ev = await event_svc.get_event(eid)
        checkin_js = _load_js("checkin")

        # 2. Build generation prompt (multimodal with images)
        from langchain_core.messages import HumanMessage as HM
        gen_text = _GEN_PROMPT.format(
            event_name=ev.name or "活动",
            event_date=str(ev.event_date) if ev.event_date else "",
            event_location=ev.location or "",
            design_description=design_description,
        )

        # Load reference images from event file store
        image_parts = _load_event_images(event_id, max_images=2)
        if image_parts:
            # Multimodal message: images + text prompt
            content_parts: list[dict[str, Any]] = list(image_parts)
            content_parts.append({
                "type": "text",
                "text": (
                    "以上是用户上传的参考图片，请参考其视觉风格。\n\n"
                    + gen_text
                ),
            })
            gen_msg = HM(content=content_parts)
        else:
            gen_msg = HM(content=gen_text)

        # 3. Call LLM to generate complete HTML page
        import asyncio
        try:
            gen_response = await asyncio.wait_for(
                llm.ainvoke([gen_msg]),
                timeout=90.0,
            )
        except asyncio.TimeoutError:
            return json.dumps({
                "status": "error",
                "message": "页面生成超时，请简化设计要求后重试",
            }, ensure_ascii=False)

        response_text = gen_response.content or ""
        if isinstance(response_text, list):
            from agents.llm_utils import extract_text_content
            response_text = extract_text_content(response_text)

        # 4. Extract complete HTML page from response
        html = _extract_full_page(response_text)

        if not html or "<body" not in html.lower():
            return json.dumps({
                "status": "error",
                "message": "生成的页面内容为空，请重试",
                "raw_length": len(response_text),
            }, ensure_ascii=False)

        # 5. Inject EVENT_ID + checkin JS before </body>
        js_inject = (
            f'\n<script>var EVENT_ID = "{event_id}";</script>\n'
            f"<script>\n{checkin_js}\n</script>\n"
        )
        html = re.sub(
            r"</body>",
            js_inject + "</body>",
            html,
            count=1,
            flags=re.IGNORECASE,
        )

        # 6. Save
        upload_dir = Path(f"uploads/events/{event_id}")
        upload_dir.mkdir(parents=True, exist_ok=True)
        page_path = upload_dir / "checkin_page.html"
        page_path.write_text(html, encoding="utf-8")

        return json.dumps({
            "status": "ok",
            "message": "自定义签到页已部署",
            "url": f"/p/{event_id}/checkin",
            "size_bytes": len(html.encode()),
        }, ensure_ascii=False)

    @tool
    async def list_attendee_roles() -> str:
        """列出活动中所有角色及人数，帮助了解参会人员构成。"""
        attendees = await attendee_svc.list_attendees(eid)
        roles: dict[str, int] = {}
        for a in attendees:
            role = a.role or "参会者"
            roles[role] = roles.get(role, 0) + 1
        return json.dumps(
            {"roles": roles, "total": len(attendees)},
            ensure_ascii=False,
        )

    @tool
    async def preview_checkin_page() -> str:
        """获取签到页预览URL，用于在 iframe 中展示当前签到页效果。"""
        return json.dumps({
            "preview_url": f"/p/{event_id}/checkin",
            "hint": "可在 iframe 或浏览器中打开此 URL 预览签到页",
        }, ensure_ascii=False)

    # ── Incremental editing tools ────────────────────────────────

    @tool
    async def get_current_page_source() -> str:
        """读取当前已部署的签到页 HTML 源码。

        用于了解页面当前结构和样式，以便做局部修改。
        返回 body HTML 和 CSS 摘要。
        """
        page_path = Path(
            f"uploads/events/{event_id}/checkin_page.html",
        )
        if not page_path.exists():
            return (
                "当前没有已部署的签到页。"
                "请先调用 render_checkin_page 生成默认页面。"
            )

        html = page_path.read_text(encoding="utf-8")

        body_match = re.search(
            r"<body[^>]*>(.*)</body>", html, re.DOTALL,
        )
        body_html = (
            body_match.group(1).strip() if body_match else ""
        )

        styles = re.findall(
            r"<style[^>]*>(.*?)</style>", html, re.DOTALL,
        )
        css_summary = "\n".join(
            s.strip()[:2000] for s in styles
        )

        if len(body_html) > 4000:
            body_html = body_html[:4000] + "\n... (truncated)"

        return json.dumps({
            "exists": True,
            "total_size": len(html),
            "body_html": body_html,
            "css_summary": css_summary[:3000],
            "element_ids": re.findall(r'id="([^"]+)"', html),
        }, ensure_ascii=False)

    @tool
    async def patch_page_css(css_rules: str) -> str:
        """向当前签到页追加 CSS 规则（不改变 HTML 结构）。

        适用于：隐藏元素、修改颜色、调整布局、改变字体等。
        CSS 会被注入到页面 <head> 最后，优先级最高。

        示例：
        - 隐藏统计栏: "#stats-bar { display: none !important; }"
        - 改背景: "body { background: linear-gradient(...) !important; }"
        - 调标题: ".event-title { font-size: 28px; color: gold; }"

        Args:
            css_rules: 要追加的 CSS 规则（一条或多条）
        """
        page_path = Path(
            f"uploads/events/{event_id}/checkin_page.html",
        )
        if not page_path.exists():
            return "当前没有已部署的签到页。请先生成页面再修改样式。"

        html = page_path.read_text(encoding="utf-8")

        override_tag = '<style id="agent-overrides">'
        if override_tag in html:
            pattern = (
                r'(<style id="agent-overrides">)(.*?)(</style>)'
            )
            match = re.search(pattern, html, re.DOTALL)
            if match:
                existing = match.group(2)
                html = html.replace(
                    match.group(0),
                    f"{override_tag}{existing}\n"
                    f"{css_rules}</style>",
                )
        else:
            override_block = (
                f"\n{override_tag}\n{css_rules}\n</style>\n"
            )
            html = html.replace(
                "</head>", f"{override_block}</head>", 1,
            )

        page_path.write_text(html, encoding="utf-8")
        return json.dumps({
            "status": "ok",
            "message": f"已追加 CSS 规则 ({len(css_rules)} 字符)",
            "url": f"/p/{event_id}/checkin",
        }, ensure_ascii=False)

    @tool
    async def update_page_source(full_html: str) -> str:
        """替换整个签到页 HTML 源码（适用于大范围修改）。

        通常的流程：get_current_page_source 读取 → 修改 → 此工具保存。
        页面必须保留关键 ID: name-input, search-btn, checkin-form,
        result-section, candidates-section, success-section

        Args:
            full_html: 完整的 HTML 源码
        """
        page_path = Path(
            f"uploads/events/{event_id}/checkin_page.html",
        )
        page_path.parent.mkdir(parents=True, exist_ok=True)
        page_path.write_text(full_html, encoding="utf-8")

        return json.dumps({
            "status": "ok",
            "message": "页面源码已更新",
            "url": f"/p/{event_id}/checkin",
            "size_bytes": len(full_html.encode()),
        }, ensure_ascii=False)

    return [
        get_event_info,
        get_checkin_stats,
        get_checkin_url,
        generate_checkin_qr,
        render_checkin_page,
        deploy_custom_checkin_page,
        list_attendee_roles,
        preview_checkin_page,
        # Incremental editing tools
        get_current_page_source,
        patch_page_css,
        update_page_source,
    ]
