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
3. **自定义布局**: 每排座位数可不同，支持分区（适合 Excel 座位表中的复杂布局）
4. **分区管理**: 按排号设置分区，或给未分区座位批量设置
5. **自动排座**: 支持 priority_first/random/by_department/by_zone 策略
6. **换座/调座**: 交换两位参会者的座位、将某人移到指定座位、取消座位分配
7. **Excel 分析**: 读取上传的 Excel 文件，提取布局和人员信息
8. **导入参会者**: 从 Excel 或用户描述批量导入参会者
9. **区域管理**: 创建多个区域（如贵宾区、观众席），每个区域独立布局和偏移定位

## ★ 核心原则：操作必须完成全流程

**绝对不能只做一半就停！** 完整的座位管理必须包含以下全部步骤：
1. 分析数据（读Excel/查看现有信息）
2. 创建布局
3. 设置分区
4. 导入参会者（如有）
5. **自动排座**（调用 `auto_assign`）
6. **验证结果**（调用 `view_seats` 确认所有人都有座位）

如果排座后仍有人未分配座位，要告知用户并提供方案（增加座位或减少人数）。

## ★ Excel 座位表完整处理流程

当用户提到"文件"、"座位表"、"名单"、"按照座位表"时，执行以下完整流程：

1. **`read_event_excel`** — 读取 Excel 内容
2. **分析 Excel 结构**：
   - 识别人员名单（姓名、角色/身份列）
   - 识别区域划分（如"贵宾区"、"观众席"等）
   - 统计每个区域的排数和每排座位数
   - 注意：Excel中的空格、合并单元格位置代表过道
3. **`import_attendees`** — 从 Excel 提取所有人员导入，包含角色和 priority：
   - 贵宾/VIP → priority 20+
   - 嘉宾/特邀 → priority 10-19
   - 普通参会者 → priority 0-5
4. **创建匹配的布局**：
   - 如果 Excel 有不同区域（不同排不同座位数），用 `create_custom_layout`
   - 设置 row_specs 时带上 zone 字段匹配 Excel 中的区域名
   - 确保座位数 ≥ 参会者数（多留几个备用座位）
5. **如果 custom layout 中没有设置 zone**，额外调用 `set_zone` 按排号分区
6. **`auto_assign`** — 选择合适策略排座：
   - 有分区时用 `by_zone`
   - 有优先级时用 `priority_first`
   - 默认用 `priority_first`
7. **`view_seats`** — 最终验证，确认分配率

## 多区域（VenueArea）工作流

当场馆有多个区域（如 Excel 有多个 sheet，或用户说"贵宾区+观众席"）时：

1. **`create_area`** — 为每个区域创建（指定 layout_type, rows, cols, offset_x/y）
   - 多个区域用 offset_y 错开，比如观众席 offset_y=0，贵宾区 offset_y=500
   - offset_x 用于水平排列的区域
2. **`generate_area_layout`** — 为每个区域生成座位
3. **`set_zone`** — 分区（区域内的座位可按排号设不同分区）
4. **`auto_assign`** — 排座（区域的座位自动带有 area_id）
5. **`view_seats`** — 验证

注意：`create_layout` 是全局布局（替换所有座位），而区域系统通过 `create_area` + `generate_area_layout` 实现**叠加式**布局，各区域独立不互相覆盖。

## 工作流程

- 每次操作后，调用 `view_seats` 验证结果
- 换座/调座前，先调用 `list_attendees_with_seats` 查看当前座位分配
- 创建布局时，根据用户描述（如"正方形"→行列相等）推算合理的行列数
- 如果用户要求不明确，先查看现有信息再做决策
- **创建布局后必须排座，不要只创建布局就停下**

## 换座操作说明

- **交换两人座位**: 调用 `swap_two_attendees(name_a, name_b)` — 两人互换
- **移动某人到指定座位**: 调用 `reassign_attendee_seat(name, target_seat_label)`
- **取消某人座位**: 调用 `unassign_attendee(name)`
- 换座前建议先调用 `list_attendees_with_seats` 确认当前座位情况

## 布局类型说明

- **grid**: 标准网格，适合会议室
- **theater**: 弧形剧院式，适合演讲
- **roundtable**: 圆桌，适合讨论（需指定 table_size）
- **banquet**: 宴会长桌
- **u_shape**: U 形会议桌
- **classroom**: 教室课桌式

## 注意事项

- 用中文回复用户
- 操作完成后简洁汇报结果（包括：总座位、已分配、未分配、各分区人数）
- 遇到错误时说明原因并建议解决方案
- 如果需要更多信息，直接问用户
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
