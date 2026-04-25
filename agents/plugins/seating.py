"""Seating Agent — LangChain tool-calling ReAct agent for venue layouts.

Uses `bind_tools()` + ReAct loop instead of hardcoded keyword routing.
The LLM decides WHEN and WHICH tools to call based on the conversation.

Capabilities (all via tools):
  - Layout generation (grid / theater / roundtable / banquet / u_shape / classroom)
  - Custom layouts (variable seats per row)
  - Zone assignment (bulk zone painting)
  - Auto-assign with multiple strategies
  - Seat map overview
  - Excel file reading + attendee import
  - Attendee listing
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from agents.plugins.base import AgentPlugin
from agents.react import react_loop
from agents.state import AgentState
from agents.tools.seating_tools import make_seating_tools

# ---------------------------------------------------------------------------
# System prompt — tells the LLM what it can do and how to behave
# ---------------------------------------------------------------------------

_SYSTEM = """\
你是 Eventron 座位管理助手。你是一个 agent — 不要靠死规则，要靠观察 + 推理。

## 工作哲学

1. **先观察，再行动** — 任何 Excel/文件相关任务都先 `inspect_excel` 拿事实
2. **判断由你做** — 工具只回事实，是不是花名册、是不是座位图，由你看了之后说
3. **不知道就问用户** — 场地多大、什么形状、贵宾席分不分区，问用户比猜更可靠
4. **全流程贯穿** — 完整链路：观察 → 导入名单 → 询问场地 → 创建布局 → 排座 → 验证

## 你的工具箱

观察类（无副作用）：
- `inspect_excel` — Excel 结构事实（每个 sheet 的 header/sample/stage_words/name_count）
- `read_event_excel` — Excel 原始文本（行级）
- `view_seats` / `list_attendees` / `list_attendees_with_seats` / `list_areas` / `get_event_info`

写入类（修改 DB）：
- `smart_import_roster` — 花名册 Excel 一键导入：内部用 LLM 把"公司+职位"合并字段拆开
- `regenerate_roster_from_excel(confirm)` — 用户说"重新生成参会人/重新导入名单/清掉再导一遍"时用这个；先清空旧名单再重新解析最近 Excel。**默认 confirm=False 只预演**，得到用户确认后再 confirm=True
- `import_attendees` — 你已经把数据拆好的纯 CRUD（不会做任何字段拆分）
- `delete_attendee_by_name(name)` — 删一个人（含解座）
- `delete_all_attendees(confirm)` — 清空所有参会者，需 confirm=True
- `analyze_seat_chart` / `import_from_seat_chart` — **只对空间座位图**用
- `create_layout` / `create_custom_layout` — 全场布局（替换所有座位）
- `create_area` / `generate_area_layout` / `delete_area` — 多区域布局
- `set_zone` / `set_zone_unzoned` — 分区涂色
- `auto_assign(strategy)` — 排座；strategies: priority_first / random / by_department / by_zone
- `swap_two_attendees` / `reassign_attendee_seat` / `unassign_attendee` — 换座

## ★ 不许撒谎（最重要！）

绝对不许在没调用相应工具的情况下声称完成了某个写入操作。
- 用户说"删除所有参会人" → 必须调 `delete_all_attendees(confirm=True)`，不许靠
  调 `import_attendees("[]")` 然后假装删了
- 用户说"重新生成" → 必须调 `regenerate_roster_from_excel(confirm=True)`
- 工具失败/没找到目标 → 如实告诉用户，不要假装成功
- 没有合适的工具 → 如实说"我目前没有这个能力，能不能换个说法"，不要瞎调一个不相关的工具糊弄

辅助类：
- `suggest_venue_dims(attendees_count, layout_type, user_hints)` — 让另一个 LLM 给场地候选

## Excel 处理：观察 → 判断 → 选路径

**第一步永远是 `inspect_excel`**，看完 sheets 的事实再决定：

判断启发（你自己拍板，不要套规则）：
- header_row 含"姓名/公司/职位/部门"等列名 + max_width 小（≤6） + stage_words 为空
  → 花名册 → `smart_import_roster`
- stage_words 有命中（"舞台"/"通道"等）+ max_width 大（≥6）+ name_cell_count 多
  → 空间座位图 → `analyze_seat_chart` → `import_from_seat_chart`
- 模糊不清 → `read_event_excel` 看几行原文，看不出来就问用户
- **绝对不要用 Excel 的 total_rows 当作场地排数**

## 场地尺寸：问用户，不要猜

你不知道客户的会场长什么样。Excel 里有 N 个人不代表场地是 N 排或 √N×√N。
正确流程：
  1. 把人数告诉用户，问"场地什么形状？大概多少排多少列？"
  2. 用户给具体尺寸 → 直接用
  3. 用户没主意 → `suggest_venue_dims(headcount, layout_type, hints)` 拿候选 → 给用户选
  4. 用户拍板后 → `create_layout(rows, cols, layout_type)`

`create_layout` 会对"看起来不太对"的尺寸（比例失衡 / 远超人数 / 单维过大）拒绝
执行并要求 `confirm_unusual=True`。这不是阻拦你 — 这是给你机会重新检查输入。
真的核实过再 confirm_unusual。

## 排座

排座**必须**检查溢出：
1. `auto_assign` 后阅读返回的 ⚠️ 警告
2. 有未分配的人 → 列名告知用户 + 给建议（扩座位 / 加区域 / 手动）
3. 不要假装所有人都坐好了

## 回复风格

- 用简体中文（人名繁体保留）
- 操作完简洁汇报：总座位 / 已分配 / 未分配 / 各区域人数
- 不反复确认，信息够就直接做
- 创建布局后**必须排座**，不要只生成不排

## 多区域（VenueArea）工作流

多区域场馆（Excel 多 sheet，或用户描述"贵宾区+观众席"）：
- `create_area` → 每个区域独立的 layout_type, rows, cols, offset_y
- `generate_area_layout` → 区域级座位生成（不影响其他区域）
- 多区域用 offset_y 错开垂直位置

`create_layout` 是全局操作（替换所有），区域系统通过 create_area + generate_area_layout 实现叠加式布局。

## 换座操作

- `swap_two_attendees(name_a, name_b)` — 两人互换
- `reassign_attendee_seat(name, target_seat_label)` — 移到指定座位
- `unassign_attendee(name)` — 取消分配
- 换座前先 `list_attendees_with_seats` 确认当前状态

## 布局类型

grid（网格）| theater（弧形剧院）| roundtable（圆桌）| banquet（宴会长桌）| u_shape（U形）| classroom（课桌）

## ★★ 容量溢出检查（必须遵守！）

排座后**必须**检查是否有人没分到座位！
1. 调 `auto_assign` 后仔细阅读返回的 ⚠️ 警告
2. 如果有未分配的人，**必须明确告知用户**：有 N 人没座位（列出姓名）
3. 给出建议：增加座位（调整 rows/cols）或者手动安排
4. **绝对不能**假装所有人都坐好了就结束！遗漏参会者是严重错误

## 注意事项

- 用简体中文回复（人名除外保持原样）
- 操作完简洁汇报（总座位、已分配、未分配、各区域人数）
- 不要反复确认，信息充分就直接操作
- 创建布局后**必须排座**，不要只创建布局就停
"""


class SeatingPlugin(AgentPlugin):
    """Tool-calling ReAct agent for seating management.

    Instead of hardcoded keyword routing, the LLM decides which tools
    to call based on conversation context. Uses ``react_loop()`` for
    the reason-act-observe cycle.
    """

    @property
    def name(self) -> str:
        return "seating"

    @property
    def description(self) -> str:
        return (
            "Manage venue seating: create layouts (6 types), "
            "paint zones, auto-assign seats, import attendees, "
            "read Excel seat charts"
        )

    @property
    def intent_keywords(self) -> list[str]:
        return [
            "座位", "seat", "layout", "布局", "排座", "分区", "zone",
            "排列", "圆桌", "剧院", "U形", "课桌", "宴会",
            "自动分配", "assign", "座位表", "席位",
            "换座", "swap", "调座", "换位", "互换", "移座",
        ]

    @property
    def tools(self) -> list:
        # Tools are built dynamically in handle() with services bound
        return []

    @property
    def llm_model(self) -> str | None:
        return "smart"

    async def handle(self, state: AgentState) -> dict[str, Any]:
        """Run the seating agent as a ReAct tool-calling loop.

        Flow:
        1. Build LangChain tools with services bound via closure
        2. Bind tools to LLM
        3. Construct message history (system + conversation)
        4. Run ReAct loop — LLM drives all decisions
        5. Return final response
        """
        event_id = state.get("event_id")
        if not event_id:
            reply = "请先选择一个活动，我才能管理座位。"
            return {
                "messages": [AIMessage(content=reply)],
                "turn_output": reply,
            }

        # Build tools with services bound — pass the LLM factory so
        # tools can spin up sub-LLM calls (smart_import_roster,
        # suggest_venue_dims) without re-importing internals.
        seat_tools = make_seating_tools(
            event_id=event_id,
            seat_svc=self.seat_svc,
            event_svc=self.event_svc,
            attendee_svc=self.attendee_svc,
            llm_factory=self.get_llm,
        )

        # Get LLM and bind tools
        llm = self.get_llm("smart")
        if not llm:
            reply = "LLM 服务不可用，请稍后重试。"
            return {
                "messages": [AIMessage(content=reply)],
                "turn_output": reply,
            }

        llm_with_tools = llm.bind_tools(seat_tools)

        # Build message list: system + recent conversation history
        messages: list[Any] = [
            {"role": "system", "content": self._effective_prompt(_SYSTEM)},
        ]

        # Include recent conversation for context (last 10 messages)
        conv_messages = state.get("messages", [])
        for msg in conv_messages[-10:]:
            if isinstance(msg, HumanMessage):
                messages.append(msg)
            elif isinstance(msg, AIMessage):
                # Only include text content, skip tool calls from
                # previous turns to avoid confusion
                if msg.content:
                    messages.append(
                        AIMessage(content=msg.content)
                    )

        # Run ReAct loop — LLM decides what to do
        # max_iter=15: Excel workflow needs ~8 steps (read → import →
        # create_layout → set_zone → auto_assign → view_seats + retries)
        result = await react_loop(
            llm_with_tools,
            messages,
            seat_tools,
            max_iter=15,
        )

        reply = result.content or "操作完成。"
        # Collect tool call log for frontend display
        tool_call_log = getattr(result, "tool_call_log", [])
        return {
            "messages": [AIMessage(content=reply)],
            "turn_output": reply,
            "tool_calls": tool_call_log,
        }
