"""Badge Agent — generates printable name badges and tent cards.

Tool-calling ReAct pattern: LLM decides which tools to call
(list templates, generate PDF, create template, etc.).

Supports vision: when the user uploads a reference badge image,
the multimodal HumanMessage (with inline base64 image) is passed
directly to the LLM so it can see the design and replicate it.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agents.plugins.base import AgentPlugin
from agents.react import react_loop
from agents.state import AgentState
from agents.tools.badge_tools import make_badge_tools

_BADGE_SYSTEM = """你是 Eventron 铭牌设计助手。你的核心能力是**直接编写完整的 HTML+CSS 代码**来创建专业铭牌模板。

## 工具
- list_attendees_by_role — 查看参会人角色分组
- list_templates — 列出可用模板
- generate_badges — 生成全部参会人铭牌 HTML（浏览器打印）
- generate_badges_for_role — 仅为指定角色生成铭牌
- design_template — **用你写的 HTML+CSS 创建模板**（核心工具）
- get_event_info — 查看活动基本信息

## 重要规则（必须遵守）
1. **你必须调用工具来执行操作**。不要只回复"请稍等"或"我来分析"——直接调用工具。
2. 内置模板:
   - **conference**（竖版会议胸牌 90×130mm，深蓝渐变+城市天际线+白色姓名横条，最推荐）
   - business（横版商务胸牌 90×54mm，深蓝渐变+白色姓名横条）
   - tent_card（桌签 210×99mm）
3. 用中文回复。
4. **当用户上传参考图片要求做模板时**，如果参考图是类似竖版深蓝色会议胸牌，直接用 conference 内置模板生成即可（调用 generate_badges(template_name='conference')），不需要 design_template。只有当用户明确要求和内置模板完全不同的风格时，才用 design_template 自己写 HTML+CSS。

## 设计模板的核心流程
当用户要求设计模板（或上传参考图片），你必须：
1. **直接编写完整的 HTML+CSS 代码**
2. 调用 design_template 工具，传入 html_template 和 css_code

### 胸牌 HTML 模板骨架（90mm × 54mm）:
```html
<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><style>{{{{ css }}}}</style></head>
<body>
{{% for attendee in attendees %}}
<div class="badge">
  <div class="header">
    <div class="event-name">{{{{ event_name }}}}</div>
    {{% if event_date %}}<div class="event-date">{{{{ event_date }}}}</div>{{% endif %}}
  </div>
  <div class="name-band">
    <div class="attendee-name">{{{{ attendee.name }}}}</div>
    {{% if attendee.title %}}<div class="title">{{{{ attendee.title }}}}</div>{{% endif %}}
    {{% if attendee.organization %}}<div class="org">{{{{ attendee.organization }}}}</div>{{% endif %}}
  </div>
  <div class="footer">
    <span class="role-tag" style="background:{{{{ attendee.role_color }}}};color:{{{{ attendee.role_text }}}}">{{{{ attendee.role_label }}}}</span>
  </div>
</div>
{{% endfor %}}
</body></html>
```

### CSS 模板骨架:
```css
@page {{ size: 90mm 54mm; margin: 0; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: "Noto Sans CJK SC", "PingFang SC", "Microsoft YaHei", sans-serif; }}
.badge {{
  width: 90mm; height: 54mm;
  page-break-after: always; overflow: hidden;
  position: relative;
  /* 你的背景设计: gradient / 纯色 / 图案 */
}}
/* ...你的完整样式... */
```

### 设计技巧（写出专业效果的关键）:
- **深色渐变背景** + **白色姓名横条** = 最经典的会议胸牌风格
- 用 CSS gradient 做丰富背景: `linear-gradient(135deg, #0a1628 0%, #1a2744 40%, #0d3b66 100%)`
- 用 `::before` / `::after` 伪元素做装饰: 光晕、斜线条纹、底部色带
- 白色姓名条用半透明增加质感: `background: rgba(255,255,255,0.92)`
- 底部装饰条: `position: absolute; bottom: 0; height: 2mm; background: linear-gradient(90deg, #e2b93b, #f39c12)`
- 角标装饰: 用 `position: absolute` + `border` 三角形
- 文字层次: 活动名 9pt 白色, 姓名 18pt 粗体深色, 职位 7pt 灰色
- 顶部可以放标语/slogan 用小字 + letter-spacing
- 如果参考图有纹理/插图，用 CSS repeating-linear-gradient 或 radial-gradient 模拟

### 当用户上传了参考图片:
你能直接看到图片。请：
1. 分析图中的**每一个视觉元素**: 背景渐变色值、文字大小颜色位置、白色横条、装饰条、角色标签样式、Logo 区域、装饰花纹
2. **用 CSS 尽可能还原**每个视觉元素，包括伪元素装饰
3. **立即调用 design_template**，不要先回复说你要分析
4. 模板名称应反映风格（如"深蓝科技会议胸牌"）

当前活动ID: {event_id}"""


class BadgePlugin(AgentPlugin):
    """Tool-calling ReAct agent for badge generation and template management."""

    @property
    def name(self) -> str:
        return "badge"

    @property
    def description(self) -> str:
        return (
            "Generate printable name badges and tent cards as PDF. "
            "Also manages badge templates (list, create, update, delete)."
        )

    @property
    def intent_keywords(self) -> list[str]:
        return [
            "胸牌", "badge", "桌签", "tent card", "名牌",
            "打印", "print", "PDF", "证件", "铭牌",
            "模板", "template", "生成胸牌", "生成桌签",
        ]

    @property
    def tools(self) -> list:
        return []  # Tools built dynamically in handle()

    @property
    def llm_model(self) -> str | None:
        return "smart"

    async def handle(self, state: AgentState) -> dict[str, Any]:
        """ReAct loop: LLM decides which badge tools to call."""
        event_id = state.get("event_id")
        messages = state.get("messages", [])
        attachments = state.get("attachments", [])

        has_images = any(a.get("type") == "image" for a in attachments)

        # Build tools with service bindings
        badge_tools = make_badge_tools(
            event_id=str(event_id) if event_id else None,
            badge_svc=self._services.get("badge_template"),
            event_svc=self.event_svc,
            attendee_svc=self.attendee_svc,
        )

        # Use strong (Claude) for vision when images present, smart otherwise
        tier = "strong" if has_images else "smart"
        llm = self.get_llm(tier) or self.get_llm("smart")
        if not llm:
            return self._fallback()

        bound = llm.bind_tools(badge_tools)

        # Build message history — only pass recent clean messages
        # Avoid passing old AIMessages with tool_calls (no matching ToolMessages)
        system = _BADGE_SYSTEM.format(
            event_id=event_id or "未选择",
        )
        llm_messages: list = [SystemMessage(content=system)]

        # Only keep the last few user/AI messages to avoid context pollution
        recent = messages[-6:] if len(messages) > 6 else messages
        for m in recent:
            if isinstance(m, HumanMessage):
                llm_messages.append(m)
            elif isinstance(m, AIMessage):
                # Skip AIMessages that have tool_calls (from other plugins)
                # since their ToolMessage responses aren't in our context
                if getattr(m, "tool_calls", None):
                    continue
                llm_messages.append(m)

        # Run ReAct loop
        result = await react_loop(
            llm=bound,
            messages=llm_messages,
            tools=badge_tools,
            max_iter=6,
        )

        reply = result.content or "操作完成。"
        tool_call_log = getattr(result, "tool_call_log", [])

        return {
            "messages": [AIMessage(content=reply)],
            "turn_output": reply,
            "tool_calls": tool_call_log,
        }

    def _fallback(self) -> dict[str, Any]:
        reply = (
            "我是铭牌设计助手，可以帮你：\n\n"
            "1. **生成胸牌 PDF** — 为所有参会人生成打印用胸牌\n"
            "2. **生成桌签 PDF** — 为所有参会人生成对折式桌签\n"
            "3. **查看模板** — 查看可用的铭牌模板\n"
            "4. **设计新模板** — 告诉我你的风格需求，或上传参考图片\n\n"
            "你想做什么？"
        )
        return {
            "messages": [AIMessage(content=reply)],
            "turn_output": reply,
        }
