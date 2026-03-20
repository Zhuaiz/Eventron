"""Badge Agent — generates printable name badges and tent cards.

Handles intents: list templates, generate PDF, create/update templates.
Uses badge_template service for DB operations and badge_render tool for PDF.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from agents.plugins.base import AgentPlugin
from agents.state import AgentState


class BadgePlugin(AgentPlugin):
    """Generates badge PDFs and manages badge templates."""

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
        return []

    @property
    def llm_model(self) -> str | None:
        return "fast"

    async def handle(self, state: AgentState) -> dict[str, Any]:
        """Route to sub-intents: generate, list templates, etc."""
        messages = state.get("messages", [])
        last_msg = ""
        for m in reversed(messages):
            if isinstance(m, HumanMessage):
                last_msg = m.content if isinstance(m.content, str) else ""
                break

        content = last_msg.lower()

        # Sub-intent: generate PDF
        if any(kw in content for kw in ["生成", "下载", "打印", "pdf", "全部"]):
            return await self._handle_generate(state, content)

        # Sub-intent: list templates
        if any(kw in content for kw in ["模板", "template", "列表", "有哪些"]):
            return await self._handle_list_templates(state)

        # Default: show options
        return self._reply_options(state)

    async def _handle_generate(
        self, state: AgentState, content: str,
    ) -> dict[str, Any]:
        """Guide user to generate badge PDF."""
        event_id = state.get("event_id")
        if not event_id:
            reply = "请先选择一个活动，我才能生成铭牌。"
            return {
                "messages": [AIMessage(content=reply)],
                "turn_output": reply,
            }

        is_tent = any(kw in content for kw in ["桌签", "tent"])
        template = "tent_card" if is_tent else "business"
        label = "桌签" if is_tent else "胸牌"

        reply = (
            f"好的，我来为当前活动生成{label} PDF。\n\n"
            f"请点击活动「铭牌」页面上方的「生成{label} PDF」按钮下载，"
            f"使用的是内置 **{template}** 模板。\n\n"
            f"如果你想自定义样式，可以告诉我：\n"
            f"· 想要什么颜色/风格\n"
            f"· 是否需要 QR 码\n"
            f"· 中英双语还是纯中文"
        )
        return {
            "messages": [AIMessage(content=reply)],
            "turn_output": reply,
        }

    async def _handle_list_templates(
        self, state: AgentState,
    ) -> dict[str, Any]:
        """List available badge templates."""
        reply = (
            "目前可用的铭牌模板：\n\n"
            "**内置模板：**\n"
            "1. **business** — 商务深色风格胸牌 (90×54mm)\n"
            "2. **tent_card** — 渐变紫色桌签 (210×99mm)\n\n"
            "你也可以在「模板管理」中创建自定义模板，"
            "或告诉我你想要什么风格，我帮你设计。"
        )
        return {
            "messages": [AIMessage(content=reply)],
            "turn_output": reply,
        }

    def _reply_options(self, state: AgentState) -> dict[str, Any]:
        """Show badge-related action options."""
        reply = (
            "我是铭牌设计助手，可以帮你：\n\n"
            "1. **生成胸牌 PDF** — 为所有参会人生成打印用胸牌\n"
            "2. **生成桌签 PDF** — 为所有参会人生成对折式桌签\n"
            "3. **查看模板** — 查看可用的铭牌模板\n"
            "4. **设计新模板** — 告诉我你的风格需求\n\n"
            "你想做什么？"
        )
        return {
            "messages": [AIMessage(content=reply)],
            "turn_output": reply,
        }
