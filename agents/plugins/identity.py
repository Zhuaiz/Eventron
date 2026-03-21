"""Identity Agent — recognizes user identity, binds IM user_id to attendee.

LLM-first approach: uses LLM to extract name from natural language,
falling back to fast heuristic for simple cases (pure Chinese names).
"""

from __future__ import annotations

import uuid
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from agents.llm_utils import extract_json, extract_text_content
from agents.plugins.base import AgentPlugin
from agents.state import AgentState

_NAME_EXTRACT_PROMPT = """你是一个姓名提取器。从用户消息中提取出人名。

规则：
- 用户可能说"我是张三"、"我叫李四"、"王五"、"I am John"等
- 只提取人名，忽略其他内容
- 如果消息中没有人名，输出 null

输出格式（纯JSON，不要代码块）：
{"name": "提取到的姓名" 或 null}"""


class IdentityPlugin(AgentPlugin):
    """Identifies who the user is by matching against the attendee list.

    Uses LLM to extract name from any natural language message,
    then matches against attendee list via service.
    """

    @property
    def name(self) -> str:
        return "identity"

    @property
    def description(self) -> str:
        return "Identify user identity, match IM user to attendee list"

    @property
    def intent_keywords(self) -> list[str]:
        return ["我是", "身份", "who am i", "identity", "叫什么", "名字"]

    @property
    def tools(self) -> list:
        return []

    @property
    def requires_identity(self) -> bool:
        return False  # This plugin IS the identity resolver

    @property
    def llm_model(self) -> str | None:
        return "fast"

    async def handle(self, state: AgentState) -> dict[str, Any]:
        """Try to identify user from their message.

        LLM-first flow:
        1. Check if user already identified -> return greeting
        2. LLM extracts name from message (any format/language)
        3. Match against attendee list via service
        4. If unique match -> bind and confirm
        5. If ambiguous -> ask for clarification
        6. If no match -> ask user to provide name
        """
        if state.get("user_profile"):
            name = state["user_profile"].get("name", "")
            reply = f"您好 {name}，我已经知道您的身份了。有什么可以帮您的？"
            return {
                "messages": [AIMessage(content=reply)],
                "turn_output": reply,
            }

        # Extract name from last user message (handle multimodal)
        last_msg = ""
        for msg in reversed(state["messages"]):
            if isinstance(msg, HumanMessage):
                last_msg = extract_text_content(msg.content)
                break

        # Try fast heuristic first for trivial cases
        name_hint = _fast_name_hint(last_msg)

        # If heuristic fails, use LLM to extract name
        if not name_hint:
            name_hint = await self._llm_extract_name(last_msg)

        if not name_hint:
            reply = "请问您是哪位？请告诉我您的姓名，我帮您在参会名单中查找。"
            return {
                "messages": [AIMessage(content=reply)],
                "turn_output": reply,
            }

        # Try real service lookup if available
        att_svc = self.attendee_svc
        event_id = state.get("event_id")

        if att_svc and event_id:
            try:
                attendees = await att_svc.list_attendees_for_event(
                    uuid.UUID(event_id)
                )
                matches = [
                    a for a in attendees if name_hint in a.name
                ]
                if len(matches) == 1:
                    a = matches[0]
                    reply = (
                        f"找到了！您是 {a.name}"
                        f"（{a.organization or ''} {a.title or ''}）。"
                        f"\n身份已确认，有什么可以帮您的？"
                    )
                    return {
                        "messages": [AIMessage(content=reply)],
                        "user_profile": {
                            "name": a.name,
                            "attendee_id": str(a.id),
                            "role": a.role,
                        },
                        "turn_output": reply,
                    }
                elif len(matches) > 1:
                    names = "、".join(a.name for a in matches[:5])
                    reply = (
                        f"找到多位匹配：{names}。"
                        f"\n请说出您的全名以便确认。"
                    )
                    return {
                        "messages": [AIMessage(content=reply)],
                        "turn_output": reply,
                    }
            except Exception:
                pass  # Fall through to generic response

        # Generic confirmation (no service or no event)
        reply = (
            f"您好！请确认您是 {name_hint} 吗？"
            "如果是的话我会帮您绑定身份，之后就可以直接操作了。"
        )
        return {
            "messages": [AIMessage(content=reply)],
            "turn_output": reply,
        }

    async def _llm_extract_name(self, message: str) -> str | None:
        """Use LLM to extract name from any natural language message."""
        llm = self.get_llm("fast")
        if not llm:
            return None
        try:
            response = await llm.ainvoke([
                {"role": "system", "content": _NAME_EXTRACT_PROMPT},
                {"role": "user", "content": message},
            ])
            data = extract_json(response.content)
            return data.get("name")
        except (ValueError, Exception):
            return None


def _fast_name_hint(message: str) -> str | None:
    """Fast heuristic for trivial name patterns.

    Handles obvious cases without LLM round-trip:
    - "我是张三" / "我叫李四"
    - Pure 2-4 char Chinese names
    """
    prefixes = ["我是", "我叫", "i am ", "i'm ", "this is "]
    lower = message.strip().lower()
    for prefix in prefixes:
        if lower.startswith(prefix):
            name = message.strip()[len(prefix):].strip()
            if name:
                return name

    # Pure Chinese name (2-4 chars)
    stripped = message.strip()
    if 2 <= len(stripped) <= 4 and all(
        "\u4e00" <= ch <= "\u9fff" for ch in stripped
    ):
        return stripped

    return None
