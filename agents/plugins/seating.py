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
你是 Eventron 座位管理助手，帮助用户进行会场座位布局和管理。

## 你的能力（通过工具调用实现）

1. **查看信息**: 查看活动信息、座位状态、参会者名单（含座位详情）
2. **创建布局**: 支持 grid/theater/roundtable/banquet/u_shape/classroom 六种布局
3. **自定义布局**: 每排座位数可不同，支持分区
4. **分区管理**: 按排号设置分区，或给未分区座位批量设置
5. **自动排座**: 支持 priority_first/random/by_department/by_zone 策略
6. **换座/调座**: 交换、移动、取消座位分配
7. **座位表分析**: `analyze_seat_chart` — 结构化解析 Excel 座位表（提取区域、位置、角色）
8. **一键导入**: `import_from_seat_chart` — 从座位表 Excel 一键完成全流程
9. **Excel 原始读取**: `read_event_excel` — 读取 Excel 文件的原始文本
10. **导入参会者**: 从 JSON 数据批量导入
11. **区域管理**: 创建多个区域，每个区域独立布局

## ★ 核心原则：操作必须完成全流程

**绝对不能只做一半就停！** 完整流程：
分析 → 创建区域/布局 → 导入参会者 → 设分区 → 自动排座 → view_seats 验证

## ★★ Excel 座位表处理（首选方案）

当用户提到"文件"、"座位表"、"名单"、"按照座位表"时：

### 方案 A（推荐）：一键导入
1. **`analyze_seat_chart`** — 先分析，展示结构化信息给用户确认
2. **`import_from_seat_chart`** — 一键执行全流程：
   - 解析每个 sheet 为独立区域
   - 创建区域 + 生成座位布局
   - 从单元格位置提取人名 + 推断角色（从 sheet 名称）
   - 导入参会者 + 按 by_zone 策略自动排座
   - 繁体中文自动转简体（人名保留原样）
   - 如有跨区域重复人员，自动去重
   - 可用 skip_areas 参数跳过特定区域（如"贵宾室"与贵宾区人员重叠时）
3. **`view_seats`** — 验证最终结果

### 方案 B（手动控制）：逐步操作
当用户需要精细控制时，按以下步骤：
1. `read_event_excel` → 读取原始内容
2. `create_area` → 逐个创建区域
3. `generate_area_layout` → 为每个区域生成座位
4. `import_attendees` → 导入参会者
5. `auto_assign` → 排座
6. `view_seats` → 验证

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

        # Build tools with services bound
        seat_tools = make_seating_tools(
            event_id=event_id,
            seat_svc=self.seat_svc,
            event_svc=self.event_svc,
            attendee_svc=self.attendee_svc,
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
