"""General-purpose LangChain tools for the chat fallback agent.

These tools give the AI assistant basic context awareness —
answering "what events exist?", "show me event details", etc.
without needing to route to a specific plugin.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from langchain_core.tools import tool


def make_general_tools(
    event_svc: Any,
    attendee_svc: Any,
    seat_svc: Any,
) -> list:
    """Build general-purpose tools for the chat fallback agent.

    These are lightweight read-only query tools that let the AI
    answer basic questions about the user's events.
    """

    @tool
    async def list_events() -> str:
        """列出所有活动。用户问"有什么活动"、"我的活动"、"活动列表"时使用。"""
        events = await event_svc.list_events()
        if not events:
            return "目前没有任何活动。可以说「帮我创建一个活动」来开始。"
        lines = [f"共 {len(events)} 个活动："]
        for ev in events[:15]:
            date_str = (
                ev.event_date.strftime("%Y-%m-%d")
                if ev.event_date else "未定"
            )
            lines.append(
                f"  • {ev.name} — {date_str} | "
                f"{ev.location or '未定'} | "
                f"状态: {ev.status} | "
                f"布局: {ev.layout_type} "
                f"({ev.venue_rows}×{ev.venue_cols})"
            )
            lines.append(f"    ID: {ev.id}")
        if len(events) > 15:
            lines.append(f"  … 及另外 {len(events) - 15} 个活动")
        return "\n".join(lines)

    @tool
    async def get_event_detail(event_id: str) -> str:
        """查看指定活动的详细信息（包括参会者数量、座位情况等）。

        Args:
            event_id: 活动 UUID
        """
        from agents.message_parts import push_part, event_card_part

        try:
            eid = uuid.UUID(event_id)
        except ValueError:
            return f"无效的活动ID: {event_id}"

        try:
            ev = await event_svc.get_event(eid)
        except Exception:
            return f"未找到活动: {event_id}"

        # Get attendee count
        att_count = 0
        try:
            atts = await attendee_svc.list_attendees_for_event(eid)
            att_count = len(atts)
        except Exception:
            pass

        # Get seat count
        seat_total = 0
        seat_assigned = 0
        try:
            seats = await seat_svc.get_seats(eid)
            seat_total = len(seats)
            seat_assigned = sum(
                1 for s in seats if s.attendee_id
            )
        except Exception:
            pass

        date_str = (
            ev.event_date.strftime("%Y-%m-%d")
            if ev.event_date else "未定"
        )

        # Push structured card for frontend
        push_part(event_card_part(
            event_id=str(ev.id),
            name=ev.name,
            date=date_str,
            location=ev.location or "未定",
            status=ev.status,
            layout_type=ev.layout_type or "",
            attendee_count=att_count,
            seat_count=seat_total,
        ))

        return (
            f"活动: {ev.name}\n"
            f"日期: {date_str}\n"
            f"地点: {ev.location or '未定'}\n"
            f"状态: {ev.status}\n"
            f"布局: {ev.layout_type} ({ev.venue_rows}排×{ev.venue_cols}列)\n"
            f"参会者: {att_count} 人\n"
            f"座位: {seat_total} 个（已分配 {seat_assigned}，"
            f"空闲 {seat_total - seat_assigned}）\n"
            f"ID: {ev.id}"
        )

    @tool
    async def get_event_summary() -> str:
        """获取所有活动的统计概览（总数、各状态数量）。"""
        events = await event_svc.list_events()
        if not events:
            return "目前没有活动。"
        by_status: dict[str, int] = {}
        for ev in events:
            by_status[ev.status] = by_status.get(ev.status, 0) + 1
        status_str = ", ".join(
            f"{s}: {c}" for s, c in sorted(by_status.items())
        )
        return (
            f"活动总数: {len(events)}\n"
            f"按状态: {status_str}"
        )

    @tool
    async def describe_capabilities() -> str:
        """介绍 Eventron 系统的功能和能力。

        当用户问"你能做什么"、"有什么工具"、"有什么功能"、
        "你是谁"、"帮助"、"help"等 meta 问题时，调用此工具。
        """
        return (
            "我是 Eventron 会场智能排座助手，可以帮你完成以下工作：\n\n"
            "📋 **活动管理** — 创建活动、设置场地信息、管理参会人员\n"
            "💺 **智能排座** — 6种布局（剧院/圆桌/宴会/U形/课桌/网格），"
            "4种排座策略（按优先级/部门/分区/随机），支持 Excel 座位表一键导入\n"
            "📱 **签到页设计** — AI生成H5签到页，扫码即用，支持自定义风格\n"
            "🏷️ **铭牌设计** — 自动生成参会者铭牌/桌签，支持多种模板\n"
            "🔄 **座位变更** — 换座、加人、请假等变更，支持审批流\n"
            "📊 **数据分析** — Excel/图片/PDF 多模态分析，任务自动拆解\n"
            "🔍 **签到查询** — 实时签到统计，二维码生成\n\n"
            "💡 **使用方式：**\n"
            "- 在主页对话框直接描述需求（如「帮我创建一个200人的年会活动」）\n"
            "- 在活动详情页使用左侧专用面板（排座/铭牌/签到页各有独立助手）\n"
            "- 上传 Excel 座位表，我会自动解析并排座"
        )

    return [
        list_events,
        get_event_detail,
        get_event_summary,
        describe_capabilities,
    ]
