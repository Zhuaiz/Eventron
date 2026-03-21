"""PageGen Agent — ReAct tool-calling agent for H5 page design.

Key design (Phase 11 v2 — "vibe coding"):
  Tools are data providers + lightweight actions. Heavy HTML generation
  happens INSIDE the deploy_custom_checkin_page tool via an internal
  LLM call.  The ReAct agent only passes a short design description,
  NOT thousands of chars of raw HTML.

Tools:
- get_event_info: understand event context
- render_checkin_page: generate default template
- deploy_custom_checkin_page(description): AI generates + deploys
- patch_page_css: incremental CSS edits
- get_current_page_source + update_page_source: read-modify-write
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from agents.llm_utils import extract_text_content
from agents.plugins.base import AgentPlugin
from agents.react import react_loop
from agents.state import AgentState

_PAGEGEN_SYSTEM = """\
你是 Eventron 签到页设计助手。

## 核心原则
1. **直接执行，不要反问** — 不要问用户活动信息，工具会自动获取
2. **优先增量修改** — 小改动用 patch_page_css，不要重新生成
3. **收到请求立即行动** — 不要输出计划让用户确认

## 工具选择策略

### 生成默认签到页（快速启用）
→ `render_checkin_page`

### 全新设计 / 自定义风格
→ `deploy_custom_checkin_page` — 传入设计描述文字即可！
  工具内部会自动获取活动数据、生成 HTML+CSS、注入签到JS、部署页面。
  你只需要把用户的设计要求总结成一段描述传入。
  示例: deploy_custom_checkin_page(design_description=\
"深蓝渐变背景，标题和logo醒目居中，去掉底部统计栏，现代简约科技风")

### 小改动（隐藏元素、改颜色、调字体）
→ `patch_page_css` 追加CSS规则

### 中等改动（重排布局、替换某个区块）
→ `get_current_page_source` 读取 → `update_page_source` 写回

## 把用户要求转化为设计描述的技巧（非常重要！）
用户说 "去掉统计栏" → 加入 "去掉底部统计栏"
用户说 "logo和title醒目" → 加入 "标题和活动名称醒目突出，大号字体"
用户说 "科技感" → "科技感设计风格，渐变背景，发光效果"

**参考图处理（关键）** — 用户上传参考图时，仔细观察图片，在描述中详细说明：
- 配色方案（主色、辅色、渐变方向）
- 布局结构（标题位置、搜索框位置、是否有背景装饰）
- 视觉元素（logo样式、图标、背景图案、几何装饰）
- 整体风格（科技感/商务/简约/活泼等）
示例: deploy_custom_checkin_page(design_description=\
"深蓝到紫色渐变背景，顶部居中显示白色大号活动名称，\
背景有淡色几何线条装饰，搜索框白色圆角卡片风格居中，\
按钮亮蓝色渐变，整体科技感简约风，无统计栏")

## CSS class / ID 速查（增量修改用）
- `#stats-bar` — 底部统计栏
- `.header` / `.event-title` — 标题区
- `#search-section` — 搜索区
- `#success-section` — 成功区

## 回复
- 中文，简洁
- 完成后告知签到链接
- 描述改了什么

当前活动ID: {event_id}"""


class PagegenPlugin(AgentPlugin):
    """ReAct tool-calling agent for H5 page design + deployment.

    deploy_custom_checkin_page uses an internal LLM call to generate
    HTML, so the ReAct agent only needs to pass a short description.
    """

    @property
    def name(self) -> str:
        return "pagegen"

    @property
    def description(self) -> str:
        return "Design and deploy H5 check-in pages, generate QR codes"

    @property
    def intent_keywords(self) -> list[str]:
        return [
            "页面", "page", "签到页", "签到", "checkin", "check-in",
            "活动介绍", "主页", "H5", "链接", "二维码", "生成页面",
            "扫码", "QR", "qr",
        ]

    @property
    def tools(self) -> list:
        return []  # Built dynamically in handle()

    @property
    def llm_model(self) -> str | None:
        return "strong"  # Needs vision for reference images

    async def handle(self, state: AgentState) -> dict[str, Any]:
        """ReAct loop: LLM calls tools to design/deploy pages."""
        from agents.tools.checkin_tools import make_checkin_tools

        event_id = state.get("event_id") or ""
        if not event_id:
            reply = "请先选择一个活动，我才能为您生成签到页。"
            return {
                "messages": [AIMessage(content=reply)],
                "turn_output": reply,
            }

        # Build tools with services injected
        checkin_svc = self._services.get("checkin")
        if not checkin_svc:
            checkin_svc = self._services.get("checkin_service")

        # ReAct loop LLM — strong tier for tool orchestration
        llm = self.get_llm("strong")
        if not llm:
            llm = self.get_llm("smart")
        if not llm:
            return self._fallback()

        # Internal page generation LLM — max tier (Opus) for
        # high-quality full-page HTML/CSS generation
        gen_llm = self.get_llm("max") or llm

        # Pass gen_llm to make_checkin_tools so deploy_custom_checkin_page
        # uses the most powerful model for HTML generation
        tools = make_checkin_tools(
            event_id=str(event_id),
            checkin_svc=checkin_svc or self._mock_checkin_svc(),
            event_svc=self.event_svc,
            attendee_svc=self.attendee_svc,
            llm=gen_llm,
        )

        llm_with_tools = llm.bind_tools(tools)

        # Build message history
        system = _PAGEGEN_SYSTEM.format(event_id=event_id)
        messages: list[Any] = [
            {"role": "system", "content": system},
        ]

        recent = state["messages"][-8:]
        for i, msg in enumerate(recent):
            is_last = i == len(recent) - 1
            if isinstance(msg, HumanMessage):
                if is_last:
                    messages.append(
                        self._trim_images(msg, max_images=2),
                    )
                else:
                    messages.append(
                        HumanMessage(
                            content=extract_text_content(
                                msg.content,
                            ),
                        ),
                    )
            elif isinstance(msg, AIMessage) and msg.content:
                text = extract_text_content(msg.content)
                if len(text) > 300:
                    text = text[:300] + "..."
                messages.append(AIMessage(content=text))

        if len(messages) == 1:
            messages.append(
                HumanMessage(content="请生成签到页"),
            )

        # Inject experience if available
        experiences = state.get("_experiences")
        if experiences:
            exp_text = "\n".join(
                f"- 用户: {e.get('user_msg', '')[:60]} → "
                f"成功: {e.get('agent_reply', '')[:80]}"
                for e in experiences[:3]
            )
            messages.insert(1, {
                "role": "system",
                "content": f"## 相关历史经验\n{exp_text}",
            })

        # Run ReAct loop
        result = await react_loop(llm_with_tools, messages, tools)
        reply = (
            extract_text_content(result.content)
            if result.content else ""
        )

        if not reply:
            reply = "签到页已生成，请查看预览。"

        tool_calls = getattr(result, "tool_call_log", [])

        return {
            "messages": [AIMessage(content=reply)],
            "turn_output": reply,
            "tool_calls": tool_calls,
        }

    @staticmethod
    def _trim_images(
        msg: HumanMessage, max_images: int = 2,
    ) -> HumanMessage:
        """Limit base64 images in a multimodal message."""
        content = msg.content
        if isinstance(content, str):
            return msg
        if not isinstance(content, list):
            return msg

        images = [
            p for p in content if p.get("type") == "image_url"
        ]
        if len(images) <= max_images:
            return msg

        kept_images = 0
        trimmed_parts: list = []
        dropped = 0
        for part in content:
            if part.get("type") == "image_url":
                if kept_images < max_images:
                    trimmed_parts.append(part)
                    kept_images += 1
                else:
                    dropped += 1
            else:
                trimmed_parts.append(part)

        if dropped:
            trimmed_parts.append({
                "type": "text",
                "text": (
                    f"（共上传了 {len(images)} 张图片，"
                    f"已选取前 {max_images} 张作为风格参考）"
                ),
            })

        return HumanMessage(content=trimmed_parts)

    def _fallback(self) -> dict[str, Any]:
        reply = (
            "我可以帮您：\n"
            "1. 生成签到页 — 参会者扫码即可在手机上签到\n"
            "2. 自定义设计 — 描述您想要的风格即可\n"
            "3. 生成二维码 — 生成签到入口二维码\n\n"
            "请问需要什么帮助？"
        )
        return {
            "messages": [AIMessage(content=reply)],
            "turn_output": reply,
        }

    def _mock_checkin_svc(self):
        """Minimal mock for when real service isn't available."""
        class _Mock:
            async def get_checkin_stats(self, eid):
                return {
                    "total": 0, "checked_in": 0,
                    "remaining": 0, "rate": 0,
                }
            async def checkin_by_name(self, eid, name):
                return {
                    "name": name, "already_checked_in": False,
                }
        return _Mock()
