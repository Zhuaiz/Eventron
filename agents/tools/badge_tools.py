"""Badge tools — LangChain @tool wrappers for badge template CRUD & generation.

Factory pattern: `make_badge_tools(event_id, badge_svc, event_svc, attendee_svc)`
returns a list of tools that the ReAct agent can bind to.
"""

from __future__ import annotations

import uuid
from typing import Any

from langchain_core.tools import tool

# Default CJK font stack used by all badge templates
_FONT_STACK = (
    '"Noto Sans CJK SC", "Noto Sans SC", "Source Han Sans SC", '
    '"Droid Sans Fallback", "PingFang SC", "Microsoft YaHei", '
    '"Helvetica Neue", sans-serif'
)


def make_badge_tools(
    event_id: str | None,
    badge_svc: Any,
    event_svc: Any,
    attendee_svc: Any,
) -> list:
    """Build badge tools with services bound via closure."""

    eid = uuid.UUID(event_id) if event_id else None

    @tool
    async def list_templates(
        template_type: str = "",
    ) -> str:
        """列出可用的铭牌模板。template_type: 'badge' 或 'tent_card'，留空返回全部。"""
        ttype = template_type if template_type in ("badge", "tent_card") else None
        templates = await badge_svc.list_templates(template_type=ttype)
        if not templates:
            return (
                "暂无自定义模板。可用内置模板：\n"
                "- conference（竖版会议胸牌 90×130mm，深蓝渐变+城市天际线，推荐）\n"
                "- business（横版商务胸牌 90×54mm）\n"
                "- tent_card（桌签 210×99mm）"
            )
        lines = ["可用模板："]
        for t in templates:
            flag = "（内置）" if t.is_builtin else ""
            lines.append(
                f"- {t.name} [{t.template_type}] {t.style_category} {flag}"
            )
        lines.append(
            "\n内置模板：conference（竖版会议胸牌，推荐）、"
            "business（横版商务胸牌）、tent_card（桌签）"
        )
        return "\n".join(lines)

    @tool
    async def list_attendees_by_role() -> str:
        """按角色分组列出当前活动的参会人，用于了解铭牌生成需求。"""
        if not eid:
            return "请先选择一个活动。"
        attendees = await attendee_svc.list_attendees_for_event(eid)
        if not attendees:
            return "该活动暂无参会人员。"
        groups: dict[str, list[str]] = {}
        for a in attendees:
            if a.status == "cancelled":
                continue
            role = a.role or "参会者"
            groups.setdefault(role, []).append(a.name)
        lines = [f"共 {len(attendees)} 位参会人："]
        for role, names in sorted(
            groups.items(),
            key=lambda x: -len(x[1]),
        ):
            lines.append(f"- {role}（{len(names)}人）: {', '.join(names[:5])}"
                         + ("..." if len(names) > 5 else ""))
        return "\n".join(lines)

    @tool
    async def generate_badges(
        template_name: str = "conference",
        template_id: str = "",
    ) -> str:
        """生成铭牌 HTML 页面并返回打印链接（浏览器 Ctrl+P 打印）。

        template_name: 内置模板名:
          'conference'（竖版会议胸牌 90×130mm，深蓝+城市天际线，最推荐）
          'business'（横版商务胸牌 90×54mm）
          'tent_card'（桌签 210×99mm）
        template_id: 自定义模板ID（可选，留空使用内置模板）。
        """
        if not eid:
            return "请先选择一个活动。"
        attendees = await attendee_svc.list_attendees_for_event(eid)
        active = [a for a in attendees if a.status != "cancelled"]
        if not active:
            return "该活动暂无参会人员，无法生成铭牌。"

        params = f"template_name={template_name}"
        if template_id:
            params += f"&template_id={template_id}"
        url = f"/api/v1/events/{eid}/export/badges/html?{params}"

        label = "桌签" if template_name == "tent_card" else "胸牌"
        roles = set(a.role or "参会者" for a in active)
        role_summary = "、".join(list(roles)[:5])

        return (
            f"已为 {len(active)} 位参会人生成{label}。\n"
            f"涵盖角色：{role_summary}\n"
            f"打印链接：{url}\n"
            f"（在浏览器中打开后按 Ctrl+P 即可打印，中文显示正常）\n\n"
            f"每位参会人的角色标签会自动显示在铭牌上，颜色按角色区分。"
        )

    @tool
    async def design_template(
        name: str,
        template_type: str = "badge",
        style_description: str = "",
        html_template: str = "",
        css_code: str = "",
    ) -> str:
        """设计并创建自定义铭牌模板。你必须直接编写完整的 Jinja2 HTML 和 CSS 代码。

        name: 模板名称（如"科技蓝会议胸牌"）
        template_type: 'badge'(胸牌 90×54mm) 或 'tent_card'(桌签 210×99mm)
        style_description: 风格描述
        html_template: **完整的 Jinja2 HTML 模板**（见下方模板变量说明）
        css_code: **完整的 CSS 样式代码**

        ## 模板变量（Jinja2）
        可用变量:
        - {{ event_name }} — 活动名称
        - {{ event_date }} — 活动日期
        - {{ css }} — CSS 代码（自动注入）
        - {% for attendee in attendees %} — 遍历参会人
          - {{ attendee.name }} — 姓名
          - {{ attendee.title }} — 职位
          - {{ attendee.organization }} — 单位/公司
          - {{ attendee.role_label }} — 角色标签（如"嘉宾"、"媒体"）
          - {{ attendee.role_color }} — 角色颜色（自动生成）
          - {{ attendee.role_text }} — 角色文字颜色
          - {{ attendee.qr_data }} — 二维码 data URI（如有）

        ## HTML 模板格式（必须严格遵循）:
        ```
        <!DOCTYPE html>
        <html lang="zh-CN">
        <head><meta charset="utf-8"><style>{{ css }}</style></head>
        <body>
        {% for attendee in attendees %}
        <div class="badge">
          <!-- 你的设计内容 -->
        </div>
        {% endfor %}
        </body></html>
        ```

        ## CSS 要求:
        - 胸牌: @page { size: 90mm 54mm; margin: 0; }
          .badge { width: 90mm; height: 54mm; }
        - 桌签: @page { size: 210mm 99mm; margin: 0; }
          .badge { width: 210mm; height: 99mm; }
        - 必须有: page-break-after: always;
        - 必须有中文字体: font-family: "Noto Sans CJK SC", ...sans-serif;
        - 用 CSS gradient/box-shadow/border 实现装饰效果
        - 用 flexbox 布局
        """
        if not html_template or not css_code:
            return (
                "错误：必须提供 html_template 和 css_code 参数。"
                "请编写完整的 Jinja2 HTML 模板和 CSS 代码。"
            )

        # Ensure CJK font stack is present
        if "Noto Sans" not in css_code and "Droid Sans" not in css_code:
            css_code = f"body {{ font-family: {_FONT_STACK}; }}\n{css_code}"

        tpl = await badge_svc.create_template(
            name=name,
            template_type=template_type,
            html_template=html_template,
            css=css_code,
            style_category="custom",
        )
        return (
            f"模板「{tpl.name}」已创建（ID: {tpl.id}）。\n"
            f"类型: {'桌签' if template_type == 'tent_card' else '胸牌'}\n"
            f"风格: {style_description or '自定义'}\n"
            f"可以在铭牌页面的模板下拉框中选择使用，"
            f"或直接调用 generate_badges(template_id='{tpl.id}') 生成。"
        )

    @tool
    async def generate_badges_for_role(
        role: str,
        template_name: str = "conference",
        template_id: str = "",
    ) -> str:
        """仅为指定角色的参会人生成铭牌 HTML 页面。

        role: 角色名称（如"甲方嘉宾"、"演讲嘉宾"、"工作人员"）
        template_name: 'conference'/'business'/'tent_card'
        template_id: 自定义模板ID（可选）
        """
        if not eid:
            return "请先选择一个活动。"
        attendees = await attendee_svc.list_attendees_for_event(eid)
        matched = [a for a in attendees
                   if a.status != "cancelled" and (a.role or "参会者") == role]
        if not matched:
            return f"没有角色为「{role}」的参会人员。"

        params = f"template_name={template_name}&roles={role}"
        if template_id:
            params += f"&template_id={template_id}"
        url = f"/api/v1/events/{eid}/export/badges/html?{params}"

        label = "桌签" if template_name == "tent_card" else "胸牌"
        return (
            f"已为 {len(matched)} 位「{role}」生成{label}。\n"
            f"打印链接：{url}\n"
            f"（浏览器打开后 Ctrl+P 打印）"
        )

    @tool
    async def get_event_info() -> str:
        """获取当前活动的基本信息。"""
        if not eid:
            return "请先选择一个活动。"
        event = await event_svc.get_event(eid)
        date_str = ""
        if event.event_date:
            date_str = event.event_date.strftime("%Y-%m-%d")
        return (
            f"活动: {event.name}\n"
            f"日期: {date_str or '未设置'}\n"
            f"地点: {event.location or '未设置'}\n"
            f"状态: {event.status}"
        )

    return [
        list_templates,
        list_attendees_by_role,
        generate_badges,
        generate_badges_for_role,
        design_template,
        get_event_info,
    ]
