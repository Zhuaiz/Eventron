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

## 用户附加要求
{design_description}

{image_directive}

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

## 用户流程（两步：先查询，再确认签到）
真正驱动这个页面的 JS 已经写好，会自动注入。流程如下：
  1. 用户输入姓名 → 点 #search-btn → JS 调 /lookup（无副作用），\
取回信息卡数据
  2. 单匹配：JS 把姓名/席位/区域填进 `#name-display` / `#seat-display` / \
`#zone-display`，并把 `#result-section` 显示出来、`#confirm-btn` 也显示出来
  3. 同名匹配：JS 把候选列表填进 `#candidates-list`，用户点击其一
  4. 用户点 #confirm-btn → JS 调 /confirm/{{attendee_id}} → 真正签到 → \
显示 `#success-section`
  5. 已签到：填同样的展示字段，但 #confirm-btn 自动变灰显示"已签到"

## 必备元素（JS 用 ID 操作；可自由排版/分组/装饰）
布局完全自由——可以加 logo 区、活动介绍、装饰图、底部插画等等任何区块。\
JS 只在乎下面这几个 ID 存在且语义对：

**步骤 1—搜索（必备）**
- `<input id="name-input">` 姓名输入框
- `<button id="search-btn" onclick="doSearch()">` 触发查询的按钮（按钮\
文字自由：搜索/查询/查找席位都行）

**步骤 2—信息卡（必备）：JS 在 lookup 成功后会填这些字段**
- `<section id="result-section" style="display:none;">` 信息卡外壳，\
JS 会把它显示出来；内部布局自由
- 在信息卡内部任意位置放：
  - `<span id="name-display"></span>` 姓名
  - `<span id="seat-display"></span>` 席位号
  - `<span id="zone-display"></span>` 区域名（可选；活动没分区就空）

**步骤 3—确认签到（必备）：用户审核后点这个按钮**
- `<button id="confirm-btn" onclick="doConfirm()" style="display:none;">` \
确认签到按钮（按钮文字自由：签到/确认签到/我要签到都行）。**这是设计上\
最醒目的 CTA，红色大按钮。**

**步骤 4—成功（必备）**
- `<section id="success-section" style="display:none;">` 成功区
  - 内含 `<span id="success-name"></span>` 显示姓名，\
`<p id="success-msg"></p>` 显示提示
  - 可选：`<div id="seat-info" style="display:none;">\
<span id="seat-label"></span></div>` 显示座位
  - 可加返回按钮 `<button onclick="resetPage()">返回</button>`

**同名消歧（可选）**
- `<section id="candidates-section" style="display:none;"><div \
id="candidates-list"></div></section>` —— 加了的话，同名时会显示候选\
列表；不加的话同名会 toast 提示"输入更完整姓名"

**统计栏（可选）**
若用户要展示实时签到率，加 `<span id="stat-total"></span>` / \
`<span id="stat-checked"></span>` / `<span id="stat-rate"></span>`

## 设计原则
- **移动端优先**：max-width 约 440px 居中；窄屏下不要溢出
- 活动名称醒目展示；可加副标题、日期、地点、装饰
- 信息卡（result-section）是页面的视觉焦点之一——参会者在这里\
确认是不是自己。配色和参考图保持一致
- 确认按钮（confirm-btn）是页面 CTA——足够大、配色突出、点击区域舒适
- 装饰区（背景渐变、纹理、几何线条、城市剪影 SVG 等）大胆加
- 不要写任何 `<script>`，JS 会由系统自动注入
- 不要修改上述任何 ID 的拼写——拼错就 JS 找不到、流程跑不通"""


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
        extra_requirements: str = "",
    ) -> str:
        """生成并部署自定义签到页（自动使用本活动已上传的参考图）。

        ## 工具实际行为（重要）
        本工具会自动读取本活动文件库中最近上传的参考图（PNG/JPG，最多 2 张），
        作为视觉风格基准 *直接* 喂给生成模型——生成模型自己看图判断主色、
        渐变、字体气质、装饰风格等。

        因此 ``extra_requirements`` **不要描述参考图的颜色 / 风格**。
        曾出现的 bug：用户上传红色图，路由 LLM 转写成"蓝白配色"放进这个参数，
        生成模型读到文字后输出蓝色页面。

        ## 何时该填什么
        - 有参考图，用户只说"按这张图设计" → ``extra_requirements=""``
        - 有参考图，用户额外要求功能改动 →
            只写功能性改动，例如 ``"去掉底部统计栏"`` /
            ``"标题字号再大一些"`` / ``"加一个 logo 区域"``
        - 没有参考图（仅文字描述）→ 这时才完整描述视觉风格，例如
            ``"深蓝紫渐变背景，标题居中大号，无统计栏，科技感"``

        ## 返回
        JSON：``status``、``preview_url``、``reference_images_used``
        （实际使用的参考图数量，可据此向用户确认）、``next_step`` 等。

        Args:
            extra_requirements: 视觉之外的功能/结构补充。无参考图时改为视觉描述。
                默认空字符串 = 完全按参考图风格生成。
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

        # 2. Load reference images from event file store FIRST so we can
        #    tailor the prompt depending on whether visuals are available.
        image_parts = _load_event_images(event_id, max_images=2)
        n_images = len(image_parts)

        # The gen prompt only needs to know which input is authoritative:
        # when reference images are present, they outrank any conflicting
        # text in `extra_requirements`. The tool docstring already steers
        # the routing LLM to keep `extra_requirements` non-visual, so this
        # block is just a safety rail for residual cases.
        if n_images:
            image_directive = (
                f"## 视觉基准\n"
                f"消息开头附带 {n_images} 张用户上传的参考图——"
                "把它们当作视觉模板直接采用（颜色、渐变、字体气质、装饰）。\n"
                "上面「用户附加要求」里若出现颜色/风格描述与图冲突，以图为准；"
                "若是功能/结构性的附加要求（如去掉统计栏、加大字号），保留执行。"
            )
        else:
            image_directive = (
                "## 视觉基准\n"
                "本次没有参考图，请按上方「用户附加要求」自由设计。"
            )

        from langchain_core.messages import HumanMessage as HM
        gen_text = _GEN_PROMPT.format(
            event_name=ev.name or "活动",
            event_date=str(ev.event_date) if ev.event_date else "",
            event_location=ev.location or "",
            design_description=extra_requirements or "（无附加要求）",
            image_directive=image_directive,
        )

        if n_images:
            # Multimodal message: images first, then framed text prompt.
            content_parts: list[dict[str, Any]] = list(image_parts)
            content_parts.append({
                "type": "text",
                "text": gen_text,
            })
            gen_msg = HM(content=content_parts)
        else:
            gen_msg = HM(content=gen_text)

        # 3. Stream the LLM generation.
        #
        # Why streaming + inactivity timeout instead of a fixed wallclock
        # cap: a 16K-token Opus generation can legitimately take 60–300s.
        # A wallclock timeout either kills valid work or has to be huge.
        # Inactivity timeout only fires when the model genuinely hangs
        # (no token for N seconds), so the budget scales with the task.
        #
        # We also push periodic progress events to PROGRESS_QUEUE so the
        # SSE endpoint can surface real activity to the user instead of
        # an opaque "thinking..." state. Reuses agents/react.py infra.
        import asyncio
        import time

        from agents.react import PROGRESS_QUEUE

        INACTIVITY_TIMEOUT = 60.0   # no token for 60s → assume hung
        PROGRESS_BYTE_STEP = 1024   # push event every ~1KB of output
        HARD_CAP_SECONDS = 600.0    # absolute upper bound (10 min) — sanity

        queue = PROGRESS_QUEUE.get(None)

        async def _push_progress(summary: str) -> None:
            if queue is not None:
                try:
                    await queue.put({
                        "event": "tool_progress",
                        "tool_name": "deploy_custom_checkin_page",
                        "tool_name_zh": "部署自定义签到页",
                        "summary": summary,
                    })
                except Exception:
                    pass  # progress is best-effort

        chunks: list[str] = []
        last_token_at = time.monotonic()
        started_at = last_token_at
        last_pushed_size = 0

        async def _consume_stream() -> None:
            """Drain llm.astream() into chunks, updating activity timestamp."""
            nonlocal last_token_at, last_pushed_size
            async for chunk in llm.astream([gen_msg]):
                # LangChain chunks expose .content; may be str or list[dict]
                piece = getattr(chunk, "content", "")
                if isinstance(piece, list):
                    from agents.llm_utils import extract_text_content
                    piece = extract_text_content(piece)
                if not piece:
                    continue
                chunks.append(piece)
                last_token_at = time.monotonic()
                total = sum(len(c) for c in chunks)
                if total - last_pushed_size >= PROGRESS_BYTE_STEP:
                    last_pushed_size = total
                    await _push_progress(f"已生成 {total // 1024}KB…")

        async def _watchdog() -> None:
            """Abort if the stream stalls for too long with no new tokens."""
            while True:
                await asyncio.sleep(2.0)
                idle = time.monotonic() - last_token_at
                if idle > INACTIVITY_TIMEOUT:
                    raise asyncio.TimeoutError(
                        f"stream stalled: no token for {idle:.0f}s"
                    )
                if time.monotonic() - started_at > HARD_CAP_SECONDS:
                    raise asyncio.TimeoutError(
                        f"hard cap exceeded: {HARD_CAP_SECONDS}s"
                    )

        if n_images:
            await _push_progress(
                f"读取到 {n_images} 张参考图，将作为视觉风格基准"
            )
        await _push_progress("正在调用模型生成页面…")

        stream_task = asyncio.create_task(_consume_stream())
        watch_task = asyncio.create_task(_watchdog())
        stream_error: Exception | None = None
        try:
            done, pending = await asyncio.wait(
                {stream_task, watch_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
            for t in done:
                exc = t.exception()
                if exc is not None:
                    stream_error = exc
                    break
        except Exception as e:
            stream_error = e
        finally:
            for t in (stream_task, watch_task):
                if not t.done():
                    t.cancel()

        response_text = "".join(chunks)
        elapsed = time.monotonic() - started_at

        # If streaming failed but we got substantial output, try to salvage
        # it. Otherwise return a structured error so the ReAct LLM can
        # reason about whether to retry, simplify, or fall back.
        if stream_error is not None and "<body" not in response_text.lower():
            err_class = type(stream_error).__name__
            if isinstance(stream_error, asyncio.TimeoutError):
                return json.dumps({
                    "status": "error",
                    "reason": "stream_stalled",
                    "elapsed_seconds": round(elapsed, 1),
                    "received_bytes": len(response_text),
                    "message": (
                        f"生成模型在 {elapsed:.0f}s 内停止响应。"
                        " 建议简化设计描述，或改用 patch_page_css "
                        "对现有页面做局部修改。"
                    ),
                }, ensure_ascii=False)
            return json.dumps({
                "status": "error",
                "reason": "llm_call_failed",
                "error_class": err_class,
                "elapsed_seconds": round(elapsed, 1),
                "received_bytes": len(response_text),
                "message": (
                    f"调用生成模型失败：{err_class}: {stream_error}。"
                    " 请稍后重试，或换一种描述方式。"
                ),
            }, ensure_ascii=False)

        try:
            html = _extract_full_page(response_text)
        except Exception as e:
            return json.dumps({
                "status": "error",
                "reason": "parse_failed",
                "error_class": type(e).__name__,
                "message": f"解析生成结果失败：{type(e).__name__}: {e}",
            }, ensure_ascii=False)

        if not html or "<body" not in html.lower():
            return json.dumps({
                "status": "error",
                "reason": "empty_or_invalid_html",
                "message": (
                    "生成的内容不是完整 HTML（缺少 <body>）。"
                    "可能是模型只返回了片段，请重试或在描述中明确"
                    "\"输出完整 HTML 文件\"。"
                ),
                "raw_length": len(response_text),
                "raw_preview": response_text[:200],
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

        # 6. Save to STAGING (not live) — user must confirm before going live
        upload_dir = Path(f"uploads/events/{event_id}")
        upload_dir.mkdir(parents=True, exist_ok=True)
        staging_path = upload_dir / "checkin_page_staging.html"
        staging_path.write_text(html, encoding="utf-8")

        if n_images:
            usage_note = (
                f"已读取并参考 {n_images} 张用户上传的参考图，"
                "页面配色与风格基于参考图生成。"
            )
        else:
            usage_note = (
                "本次没有用户上传的参考图，"
                "页面基于文字描述生成。如需贴合具体视觉，可上传参考图后重新生成。"
            )

        return json.dumps({
            "status": "ok",
            "message": (
                "签到页已生成到预览区（尚未上线）。"
                f"{usage_note}"
                "请在预览中确认效果，满意后调用 confirm_staged_page 正式部署。"
                "如需重新生成，可再次调用本工具。"
            ),
            "reference_images_used": n_images,
            "preview_url": f"/p/{event_id}/checkin?preview=staging",
            "next_step": "confirm_staged_page",
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

    # ── Staging / deployment lifecycle ────────────────────────────

    @tool
    async def confirm_staged_page() -> str:
        """将预览中的签到页正式部署上线。

        会自动备份当前在线版本，部署后参会者扫码即可看到新页面。
        如果效果不满意，可用 rollback_page 一键回退到上一版。
        """
        upload_dir = Path(f"uploads/events/{event_id}")
        staging_path = upload_dir / "checkin_page_staging.html"
        live_path = upload_dir / "checkin_page.html"
        backup_path = upload_dir / "checkin_page_backup.html"

        if not staging_path.exists():
            return json.dumps({
                "status": "error",
                "message": "没有待部署的预览页面。请先用 deploy_custom_checkin_page 生成。",
            }, ensure_ascii=False)

        # Back up current live page (if exists)
        if live_path.exists():
            import shutil
            shutil.copy2(str(live_path), str(backup_path))

        # Promote staging → live
        import shutil
        shutil.move(str(staging_path), str(live_path))

        return json.dumps({
            "status": "ok",
            "message": "签到页已正式上线！参会者扫码即可看到新页面。",
            "url": f"/p/{event_id}/checkin",
            "can_rollback": backup_path.exists(),
        }, ensure_ascii=False)

    @tool
    async def rollback_page() -> str:
        """回退签到页到上一个版本。

        如果新部署的页面有问题，调用此工具恢复到之前的版本。
        """
        upload_dir = Path(f"uploads/events/{event_id}")
        live_path = upload_dir / "checkin_page.html"
        backup_path = upload_dir / "checkin_page_backup.html"

        if not backup_path.exists():
            return json.dumps({
                "status": "error",
                "message": "没有可回退的版本。",
            }, ensure_ascii=False)

        # Restore backup → live
        import shutil
        shutil.copy2(str(backup_path), str(live_path))
        backup_path.unlink()

        return json.dumps({
            "status": "ok",
            "message": "已回退到上一版签到页。",
            "url": f"/p/{event_id}/checkin",
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
        confirm_staged_page,
        rollback_page,
        list_attendee_roles,
        preview_checkin_page,
        # Incremental editing tools
        get_current_page_source,
        patch_page_css,
        update_page_source,
    ]
