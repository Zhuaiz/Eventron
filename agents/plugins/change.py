"""Change Agent — handles seat swap, leave, add person with HITL approval.

LLM-first approach: LLM classifies change type and extracts details
from natural language, then routes to the appropriate action.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from agents.llm_utils import extract_json, extract_text_content

from agents.plugins.base import AgentPlugin
from agents.state import AgentState

_CHANGE_SYSTEM = """你是 Eventron 座位变更助手。分析用户的变更请求，分类并提取关键信息。

## 变更类型
- leave: 请假、不来了、来不了、取消
- swap: 换座、跟某人换、想跟某人坐一起
- add: 加人、临时添加参会者
- reassign: 重新安排座位、换个位置
- other: 无法分类

## 输出格式（纯JSON，不要代码块）
{{
  "change_type": "leave|swap|add|reassign|other",
  "details": {{
    "person_name": "涉及的人名(如提到)",
    "target_name": "想跟谁换/加谁(如提到)",
    "reason": "原因(如提到)",
    "extra": "其他信息"
  }},
  "response": "用中文回复用户的友好消息"
}}

## 回复规则
- leave: 确认已记录，座位会释放
- swap: 确认收到申请，告知需要审批
- add: 询问新人的姓名和职位
- reassign: 确认并说明会重新安排
- other: 友好地问用户需要什么变更

当前用户信息: {user_context}"""


class ChangePlugin(AgentPlugin):
    """Processes seat changes that may require human approval.

    LLM-first: LLM analyzes the change request, classifies intent,
    extracts details, and generates an appropriate response.
    """

    @property
    def name(self) -> str:
        return "change"

    @property
    def description(self) -> str:
        return "Handle seat swap, leave, add person — with approval workflow"

    @property
    def intent_keywords(self) -> list[str]:
        return [
            "换座", "swap", "请假", "leave", "不来了", "加人",
            "add person", "临时", "调整", "变更", "change",
        ]

    @property
    def tools(self) -> list:
        return []

    @property
    def llm_model(self) -> str | None:
        return "smart"

    async def handle(self, state: AgentState) -> dict[str, Any]:
        """Handle change requests via LLM analysis.

        LLM-first flow:
        1. LLM classifies change type from natural language
        2. LLM extracts relevant details (names, reasons)
        3. LLM generates appropriate response
        4. In production: create ApprovalRequest + interrupt()
        """
        last_msg = ""
        for msg in reversed(state["messages"]):
            if isinstance(msg, HumanMessage):
                last_msg = extract_text_content(msg.content)
                break

        profile = state.get("user_profile")
        user_ctx = "未知用户"
        if profile:
            user_ctx = f"{profile.get('name', '未知')} (角色: {profile.get('role', '参会者')})"

        llm = self.get_llm("smart")
        if not llm:
            # Fallback without LLM
            reply = (
                "您需要什么变更？我可以帮您：\n"
                "· 请假 — 释放座位\n"
                "· 换座 — 与他人交换座位\n"
                "· 加人 — 临时添加参会人员"
            )
            return {
                "messages": [AIMessage(content=reply)],
                "turn_output": reply,
            }

        system = _CHANGE_SYSTEM.format(user_context=user_ctx)
        try:
            response = await llm.ainvoke([
                {"role": "system", "content": system},
                {"role": "user", "content": last_msg},
            ])
            data = extract_json(response.content)
            reply = data.get("response", "收到您的变更请求，正在处理。")

            # TODO: In production, create ApprovalRequest based on
            # data["change_type"] and data["details"], then use
            # LangGraph interrupt() for HITL approval.

        except (ValueError, Exception):
            # LLM didn't return valid JSON, use raw response
            reply = response.content if 'response' in dir() else (
                "收到您的变更请求。请具体说明：\n"
                "· 请假/不来了\n"
                "· 想换座位\n"
                "· 临时加人"
            )

        return {
            "messages": [AIMessage(content=reply)],
            "turn_output": reply,
        }
