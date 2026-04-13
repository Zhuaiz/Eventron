"""Organizer Agent — LLM-driven event creation and management.

This is the most complex plugin. It uses a full LLM conversation loop
with a rich system prompt to help organizers create events, calculate
venue capacity, generate seats, and run auto-assignment.

The LLM outputs ``action`` JSON blocks which this plugin extracts and
executes against the real service layer.

When a task_plan is present (from planner), the organizer operates in
**one-shot mode**: it creates the event, generates the layout, and
auto-assigns seats in a single turn — no extra confirmation needed.
"""

from __future__ import annotations

import json
import math
import re
import uuid
from datetime import date, datetime
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from agents.llm_utils import extract_text_content
from agents.plugins.base import AgentPlugin
from agents.state import AgentState


# ── System prompt for the organizer LLM ──────────────────────
ORGANIZER_SYSTEM = """你是 Eventron 会场智能排座助手。你帮助用户创建活动、规划会场座位、管理参会人。

## 今天日期
{today}

## 你的能力
1. **创建活动** — 收集活动信息后创建
2. **计算会场容量** — 根据会场/座位尺寸计算行列数
3. **生成座位** — 为活动创建座位网格
4. **自动排座** — 随机/VIP优先/按部门
5. **查看签到/活动**

## 对话规则（非常重要）
- 用简洁友好的中文回复
- **用户随时可以修改之前说的信息**。比如用户说"名字改成xxx"，你要理解这是修改，不是回答当前问题。用 update_draft 更新后继续。
- 一步步来，每次只问一个问题
- 如果用户给了模糊信息，主动澄清
- **不要反复确认**。当必需信息都收集完了，直接用 create_event 创建，不用再问"确认吗"。用户说"创建"/"是"/"好"就代表确认。
- 日期处理：用户说"明天"就算成明天的 ISO 日期，说"下周五"就算出来。**必须输出 YYYY-MM-DD 格式**。
- **主动建议合理参数**。如果用户说"正方形布局"但有128人，直接建议12×12=144座（能容纳128人），不要让用户自己算。

## 座位计算规则
- "会场WxH米"：rows = floor(H / 行距), cols = floor(W / 列距)。默认行距0.9m，列距0.6m
- "座位面积X平米"：宽=sqrt(面积*2/3), 深=sqrt(面积*3/2)，然后用这个宽深代替默认列距行距
- 会场总面积推行列：先推算会场宽高（假设比例2:3或正方形），再算行列
- **必须展示计算过程**
- **人数推正方形**: rows=cols=ceil(sqrt(人数)), 确保总数≥人数

## 创建活动必需信息
name, layout_type, venue_rows, venue_cols（必需）
event_date, location（可选）
必需信息齐全 → 直接创建或列出信息等一次确认即可。不要反复追问可选字段。

## 当前状态
{state_context}

## Action 指令
在回复末尾加 JSON 指令块（用户看不到）：
```action
{{"action": "动作名", "params": {{...}}}}
```

可用 action：
- update_draft: {{字段...}} — 更新草稿
- create_event: {{name, event_date?, location?, layout_type, venue_rows, venue_cols}} — event_date 必须是 "YYYY-MM-DD" 格式或 null
- generate_seats: {{event_id?}}
- auto_assign: {{event_id?, strategy: "random"|"vip_first"|"by_department"}}
- list_events: {{}}
- checkin_stats: {{event_id?}}

layout_type: theater|classroom|roundtable|banquet|u_shape

信息不完整 → 继续问。
用户修正 → update_draft 更新。
信息齐全且用户确认 → create_event（不要再二次确认）。"""


def _parse_date(val: str | None) -> Any:
    """Parse a date string into datetime, or return None."""
    if not val:
        return None
    if isinstance(val, (datetime, date)):
        return val
    val = val.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d", "%Y年%m月%d日"):
        try:
            return datetime.strptime(val, fmt)
        except ValueError:
            continue
    return None


def _extract_action(text: str) -> tuple[str, dict | None]:
    """Extract action JSON from LLM response."""
    pattern = r'```action\s*\n?(.*?)\n?```'
    match = re.search(pattern, text, re.DOTALL)
    if match:
        clean = text[:match.start()].strip()
        try:
            action = json.loads(match.group(1).strip())
            return clean, action
        except json.JSONDecodeError:
            return clean, None
    return text, None


class OrganizerPlugin(AgentPlugin):
    """Helps organizers create/manage events through LLM conversation.

    Uses a rich system prompt so the LLM can:
    - Collect event info step by step
    - Calculate venue capacity from dimensions
    - Handle mid-flow corrections
    - Output action blocks that get executed

    When task_plan is present, enters one-shot mode:
    create event → generate layout → auto-assign, all in one turn.
    """

    def __init__(self, services: dict[str, Any] | None = None):
        super().__init__(services)
        # Per-session drafts: {session_key: {field: value}}
        self._drafts: dict[str, dict] = {}

    @property
    def name(self) -> str:
        return "organizer"

    @property
    def description(self) -> str:
        return (
            "Create events, calculate venue capacity, generate seats, "
            "auto-assign seats, list events — the full organizer workflow"
        )

    @property
    def intent_keywords(self) -> list[str]:
        return [
            "创建活动", "新活动", "create event", "会场", "venue",
            "容量", "capacity", "几排几列", "排座", "自动排座",
            "座位", "seat", "布局", "layout", "活动列表",
            "list events", "多少人", "生成座位", "generate",
        ]

    @property
    def tools(self) -> list:
        return []

    @property
    def requires_identity(self) -> bool:
        return False  # Organizer is authenticated via JWT

    @property
    def llm_model(self) -> str | None:
        return "smart"

    async def handle(self, state: AgentState) -> dict[str, Any]:
        """Full LLM-driven organizer conversation.

        If task_plan is present with event_draft, uses one-shot mode
        to execute create + layout + assign without further prompting.
        """
        event_id = state.get("event_id")
        task_plan = state.get("task_plan") or []
        event_draft = state.get("event_draft")

        # ── One-shot mode: plan confirmed, execute everything ──
        if event_draft and task_plan and not event_id:
            return await self._one_shot_execute(state, event_draft, task_plan)

        # ── Normal LLM conversation mode ──
        draft_key = event_id or "new"
        draft = self._drafts.setdefault(draft_key, {})

        # Pre-populate draft from planner's event_draft if present
        if event_draft and not draft:
            for k, v in event_draft.items():
                if v is not None:
                    draft[k] = v

        # Build state context
        state_ctx = self._build_state_context(event_id, draft)
        today_str = date.today().isoformat()
        prompt_tpl = self._effective_prompt(ORGANIZER_SYSTEM)
        system = prompt_tpl.format(
            today=today_str, state_context=state_ctx,
        )

        # Build messages for LLM (system + conversation history)
        llm_messages = [{"role": "system", "content": system}]
        for msg in state["messages"][-20:]:
            if isinstance(msg, HumanMessage):
                llm_messages.append(
                    {"role": "user", "content": extract_text_content(msg.content)}
                )
            elif isinstance(msg, AIMessage):
                llm_messages.append(
                    {"role": "assistant", "content": msg.content}
                )

        # Call LLM
        llm = self.get_llm("smart")
        if not llm:
            reply = "LLM 未配置，无法处理请求。"
            return {
                "messages": [AIMessage(content=reply)],
                "turn_output": reply,
            }

        try:
            response = await llm.ainvoke(llm_messages)
            raw_reply = response.content
        except Exception as e:
            reply = f"LLM 调用失败：{e}。请稍后重试。"
            return {
                "messages": [AIMessage(content=reply)],
                "turn_output": reply,
            }

        # Extract and execute action
        reply_text, action_data = _extract_action(raw_reply)
        action_taken = None
        new_event_id = event_id

        if action_data and isinstance(action_data, dict):
            act = action_data.get("action")
            params = action_data.get("params", {})

            if act == "update_draft":
                draft.update(params)

            elif act == "create_event":
                extra, action_taken, new_event_id = (
                    await self._exec_create_event(params, draft_key)
                )
                reply_text += extra

            elif act == "generate_seats":
                extra, action_taken = await self._exec_generate_seats(
                    params, event_id
                )
                reply_text += extra

            elif act == "auto_assign":
                extra, action_taken = await self._exec_auto_assign(
                    params, event_id
                )
                reply_text += extra

            elif act == "list_events":
                extra = await self._exec_list_events()
                reply_text += extra

            elif act == "checkin_stats":
                extra = await self._exec_checkin_stats(params, event_id)
                reply_text += extra

        result: dict[str, Any] = {
            "messages": [AIMessage(content=reply_text)],
            "turn_output": reply_text,
        }
        if new_event_id and new_event_id != event_id:
            result["event_id"] = new_event_id

        return result

    # ── One-shot execution mode ──────────────────────────────────
    async def _one_shot_execute(
        self,
        state: AgentState,
        event_draft: dict,
        task_plan: list[dict],
    ) -> dict[str, Any]:
        """Execute full plan in one shot: create + layout + assign.

        Skips LLM conversation entirely — all info is already known
        from the planner's analysis.
        """
        parts: list[str] = []

        # ── Step 1: Create event ──
        name = event_draft.get("name", "未命名活动")
        event_date = _parse_date(event_draft.get("date"))
        location = event_draft.get("location")
        layout_type = event_draft.get("layout_type", "theater")

        # Calculate rows/cols from draft or estimate
        rows = event_draft.get("estimated_rows") or event_draft.get("venue_rows")
        cols = event_draft.get("estimated_cols") or event_draft.get("venue_cols")
        estimated = event_draft.get("estimated_attendees")

        # If no rows/cols but have estimated attendees, calculate
        if (not rows or not cols) and estimated:
            side = math.ceil(math.sqrt(estimated))
            rows = side
            cols = side

        if not rows or not cols:
            rows = rows or 10
            cols = cols or 10

        svc = self.event_svc
        if not svc:
            reply = "❌ EventService 不可用。"
            return {
                "messages": [AIMessage(content=reply)],
                "turn_output": reply,
            }

        try:
            event = await svc.create_event(
                name=name,
                event_date=event_date,
                location=location,
                layout_type=layout_type,
                venue_rows=rows,
                venue_cols=cols,
            )
            eid = str(event.id)
            total_seats = event.venue_rows * event.venue_cols
            parts.append(
                f"✅ 活动「{event.name}」已创建！"
                f"\n📍 {location or '未设置'}"
                f" · 📅 {event.event_date or '未设置'}"
                f"\n🪑 布局: {layout_type}，{rows}排×{cols}列 = {total_seats}座"
            )
        except Exception as e:
            reply = f"❌ 创建活动失败：{e}"
            return {
                "messages": [AIMessage(content=reply)],
                "turn_output": reply,
            }

        # ── Step 2: Generate layout ──
        seat_svc = self.seat_svc
        if seat_svc:
            try:
                seats = await seat_svc.create_venue_layout(
                    uuid.UUID(eid), layout_type, rows, cols,
                )
                parts.append(
                    f"✅ 已生成 {len(seats)} 个{layout_type}布局座位"
                )
            except Exception as e:
                parts.append(f"⚠️ 座位生成出错：{e}")

        # Mark organizer tasks as done in task_plan
        updated_plan = []
        for t in task_plan:
            t2 = dict(t)
            if t2.get("plugin") == "organizer":
                t2["status"] = "done"
            updated_plan.append(t2)

        reply = "\n".join(parts)

        # Build quick replies based on remaining tasks
        pending = [t for t in updated_plan if t.get("status") == "pending"]
        if pending:
            qr = [{"label": "继续下一步", "value": "继续", "style": "primary"}]
        else:
            qr = [
                {"label": "📋 查看座位图", "value": "查看座位图", "style": "primary"},
                {"label": "🏷️ 设计铭牌", "value": "设计铭牌", "style": "default"},
            ]

        result: dict[str, Any] = {
            "messages": [AIMessage(content=reply)],
            "turn_output": reply,
            "event_id": eid,
            "task_plan": updated_plan,
            "quick_replies": qr,
        }
        return result

    # ── State context builder ──────────────────────────────────
    def _build_state_context(
        self, event_id: str | None, draft: dict
    ) -> str:
        parts = []
        if event_id:
            parts.append(f"当前活动ID: {event_id}")
        if draft:
            parts.append(
                f"已收集的活动信息（来自之前对话或图片分析）: "
                f"{json.dumps(draft, ensure_ascii=False)}"
            )
            parts.append(
                "重要：以上信息已由之前的对话/图片分析提取，"
                "不要再重复询问这些信息。如果信息齐全就直接创建。"
                "如果缺少 venue_rows/venue_cols，根据 estimated_attendees 推算。"
            )
        if not parts:
            parts.append("无活动上下文，用户刚开始对话")
        return "\n".join(parts)

    # ── Action executors ───────────────────────────────────────
    async def _exec_create_event(
        self, params: dict, draft_key: str
    ) -> tuple[str, str | None, str | None]:
        """Create event via EventService. Returns (msg, action, event_id)."""
        svc = self.event_svc
        if not svc:
            return "\n\n EventService 不可用。", None, None
        try:
            event_date = _parse_date(params.get("event_date"))
            event = await svc.create_event(
                name=params["name"],
                event_date=event_date,
                location=params.get("location"),
                layout_type=params.get("layout_type", "theater"),
                venue_rows=params.get("venue_rows", 0),
                venue_cols=params.get("venue_cols", 0),
            )
            # Clear draft
            self._drafts.pop(draft_key, None)
            eid = str(event.id)
            rows = event.venue_rows
            cols = event.venue_cols
            return (
                f"\n\n✅ 活动「{event.name}」已创建！"
                f"\n布局: {event.layout_type}，{rows}排×{cols}列"
                f" = {rows * cols}座",
                "event_created",
                eid,
            )
        except Exception as e:
            return f"\n\n❌ 创建失败：{e}", None, None

    async def _exec_generate_seats(
        self, params: dict, event_id: str | None
    ) -> tuple[str, str | None]:
        eid = params.get("event_id") or event_id
        if not eid:
            return "\n\n请先创建或选择一个活动。", None
        svc = self.event_svc
        seat_svc = self.seat_svc
        if not svc or not seat_svc:
            return "\n\n服务不可用。", None
        try:
            event = await svc.get_event(uuid.UUID(eid))
            existing = await seat_svc.get_seats(uuid.UUID(eid))
            if existing:
                return (
                    f"\n\n该活动已有 {len(existing)} 个座位，"
                    "无需重复生成。",
                    None,
                )
            # Use proper layout generator, not legacy grid
            seats = await seat_svc.create_venue_layout(
                uuid.UUID(eid),
                event.layout_type or "theater",
                event.venue_rows,
                event.venue_cols,
            )
            return (
                f"\n\n✅ 已生成 {len(seats)} 个座位！"
                f"\n可以去「座位图」标签页查看，或说「自动排座」。",
                "seats_generated",
            )
        except Exception as e:
            return f"\n\n❌ 生成失败：{e}", None

    async def _exec_auto_assign(
        self, params: dict, event_id: str | None
    ) -> tuple[str, str | None]:
        eid = params.get("event_id") or event_id
        if not eid:
            return "\n\n请先选择一个活动。", None
        seat_svc = self.seat_svc
        if not seat_svc:
            return "\n\n服务不可用。", None
        strategy = params.get("strategy", "priority_first")
        label = {
            "random": "随机",
            "priority_first": "优先级排座",
            "vip_first": "VIP优先(兼容)",
            "by_department": "按部门",
            "by_zone": "按分区",
        }.get(strategy, strategy)
        try:
            assignments = await seat_svc.auto_assign(
                uuid.UUID(eid), strategy=strategy
            )
            if not assignments:
                return (
                    "\n\n没有需要分配的参会者"
                    "（都已有座位或没有参会者）。",
                    None,
                )
            return (
                f"\n\n✅ 排座完成！策略：{label}，"
                f"共分配 {len(assignments)} 个座位。",
                "seats_assigned",
            )
        except ValueError as e:
            return f"\n\n❌ {e}", None
        except Exception as e:
            return f"\n\n❌ 出错：{e}", None

    async def _exec_list_events(self) -> str:
        svc = self.event_svc
        if not svc:
            return "\n\n服务不可用。"
        events = await svc.list_events()
        if not events:
            return "\n\n还没有活动，要创建一个吗？"
        status_map = {
            "draft": "草稿", "active": "进行中",
            "completed": "已完成", "cancelled": "已取消",
        }
        lines = ["\n\n你的活动："]
        for e in events[:10]:
            lines.append(
                f"  · {e.name} [{status_map.get(e.status, e.status)}] "
                f"— {e.venue_rows}×{e.venue_cols} {e.layout_type}"
            )
        return "\n".join(lines)

    async def _exec_checkin_stats(
        self, params: dict, event_id: str | None
    ) -> str:
        eid = params.get("event_id") or event_id
        if not eid:
            return "\n\n请先选择一个活动。"
        att_svc = self.attendee_svc
        if not att_svc:
            return "\n\n服务不可用。"
        try:
            attendees = await att_svc.list_attendees_for_event(
                uuid.UUID(eid)
            )
            total = len(attendees)
            checked = sum(
                1 for a in attendees if a.status == "checked_in"
            )
            rate = round(checked / total * 100, 1) if total > 0 else 0
            return (
                f"\n\n签到统计：总 {total} 人，"
                f"已签到 {checked} 人 ({rate}%)"
            )
        except Exception as e:
            return f"\n\n查询失败：{e}"
