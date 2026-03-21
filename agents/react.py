"""Reusable ReAct (Reason+Act) loop for tool-calling agents.

Pattern: LLM thinks → calls tools → observes results → thinks again → ...
Stops when LLM gives a text response with no tool calls, or max iterations.

Collects tool call metadata for frontend display.
Supports optional progress callback for SSE streaming.
"""

from __future__ import annotations

import asyncio
import contextvars
from typing import Any, Callable, Awaitable

from langchain_core.messages import AIMessage, ToolMessage

MAX_ITERATIONS = 10

# Callback type: async fn(event_type, data) → None
ProgressCallback = Callable[[str, dict[str, Any]], Awaitable[None]]

# Context var: SSE endpoint sets an asyncio.Queue here so react_loop
# can push progress events without any changes to the plugin/graph layer.
PROGRESS_QUEUE: contextvars.ContextVar[asyncio.Queue | None] = (
    contextvars.ContextVar("react_progress_queue", default=None)
)

# Chinese display names for tools
_TOOL_NAMES_ZH: dict[str, str] = {
    "get_event_info": "查看活动信息",
    "view_seats": "查看座位状态",
    "create_layout": "创建座位布局",
    "create_custom_layout": "创建自定义布局",
    "auto_assign": "自动排座",
    "set_zone": "设置分区",
    "set_zone_unzoned": "设置未分区座位",
    "read_event_excel": "读取Excel文件",
    "list_attendees": "查看参会者名单",
    "import_attendees": "导入参会者",
    # Seat swap/reassign tools
    "list_attendees_with_seats": "查看座位分配详情",
    "swap_two_attendees": "交换两人座位",
    "reassign_attendee_seat": "调整座位",
    "unassign_attendee": "取消座位分配",
    # Check-in / page tools
    "get_checkin_stats": "查看签到统计",
    "get_checkin_url": "获取签到链接",
    "generate_checkin_qr": "生成签到二维码",
    "render_checkin_page": "渲染签到页",
    "deploy_custom_checkin_page": "部署自定义签到页",
    "list_attendee_roles": "查看参会角色",
    "preview_checkin_page": "预览签到页",
    # Incremental page editing tools
    "get_current_page_source": "读取当前页面源码",
    "patch_page_css": "追加CSS样式",
    "update_page_source": "更新页面源码",
}


def _truncate(text: str, max_len: int = 80) -> str:
    return text[:max_len] + "..." if len(text) > max_len else text


async def _noop_callback(_event: str, _data: dict) -> None:
    """Default no-op progress callback."""


async def react_loop(
    llm,
    messages: list,
    tools: list,
    *,
    max_iter: int = MAX_ITERATIONS,
    call_timeout: float = 120.0,
    on_progress: ProgressCallback | None = None,
) -> AIMessage:
    """Run a ReAct tool-calling loop.

    Args:
        llm: LLM with tools already bound via ``bind_tools()``.
        messages: Initial message list (system + conversation history).
        tools: List of LangChain tool objects (for execution lookup).
        max_iter: Safety limit on loop iterations.
        call_timeout: Max seconds to wait for each LLM call.
        on_progress: Optional async callback for streaming progress.
            Called with (event_type, data) where event_type is one of:
            "thinking", "tool_start", "tool_end", "done", "error".

    Returns:
        Final AIMessage containing the text response to the user.
        The message has an extra ``tool_call_log`` attribute (list of dicts)
        with metadata about each tool call for frontend display.
    """
    # If no explicit callback, check context var for SSE queue
    if on_progress:
        progress = on_progress
    else:
        queue = PROGRESS_QUEUE.get(None)
        if queue is not None:
            async def _queue_callback(
                event: str, data: dict[str, Any],
            ) -> None:
                await queue.put({"event": event, **data})
            progress = _queue_callback
        else:
            progress = _noop_callback
    tool_map = {t.name: t for t in tools}
    tool_call_log: list[dict[str, Any]] = []

    # Track consecutive failures per tool to prevent infinite retries
    _consecutive_failures: dict[str, int] = {}
    _MAX_CONSECUTIVE_FAILURES = 2

    _nudged = False
    for _i in range(max_iter):
        # Notify: LLM is thinking
        await progress("thinking", {"iteration": _i + 1})

        try:
            response = await asyncio.wait_for(
                llm.ainvoke(messages), timeout=call_timeout,
            )
        except asyncio.TimeoutError:
            await progress("error", {"message": "LLM 响应超时"})
            fallback = AIMessage(
                content="LLM 响应超时，请稍后重试或简化请求。"
            )
            fallback.tool_call_log = tool_call_log  # type: ignore[attr-defined]
            return fallback
        messages.append(response)

        # No tool calls → LLM might be done
        if not getattr(response, "tool_calls", None):
            if (
                not _nudged
                and not tool_call_log
                and tools
                and response.content
            ):
                _nudged = True
                from langchain_core.messages import HumanMessage as _HM
                messages.append(
                    _HM(content="请直接调用工具执行操作，不要只回复文字。")
                )
                continue

            response.tool_call_log = tool_call_log  # type: ignore[attr-defined]
            await progress("done", {
                "reply": _truncate(str(response.content), 200),
            })
            return response

        # Execute each tool call and feed results back
        _should_abort = False
        for tc in response.tool_calls:
            tool_name = tc["name"]
            tool_args = tc["args"]
            tool_fn = tool_map.get(tool_name)
            tool_zh = _TOOL_NAMES_ZH.get(tool_name, tool_name)

            # Check consecutive failure limit before executing
            if _consecutive_failures.get(tool_name, 0) >= _MAX_CONSECUTIVE_FAILURES:
                result = (
                    f"工具 {tool_zh} 已连续失败 "
                    f"{_consecutive_failures[tool_name]} 次，停止重试。"
                    f"请向用户说明遇到的问题并提供建议。"
                )
                entry = {
                    "tool_name": tool_name,
                    "tool_name_zh": tool_zh,
                    "status": "error",
                    "summary": "连续失败，已停止重试",
                }
                tool_call_log.append(entry)
                await progress("tool_end", entry)
                messages.append(
                    ToolMessage(content=result, tool_call_id=tc["id"]),
                )
                _should_abort = True
                continue

            # Notify: tool starting
            await progress("tool_start", {
                "tool_name": tool_name,
                "tool_name_zh": tool_zh,
            })

            if tool_fn:
                try:
                    result = await tool_fn.ainvoke(tool_args)
                    entry = {
                        "tool_name": tool_name,
                        "tool_name_zh": tool_zh,
                        "status": "success",
                        "summary": _truncate(str(result)),
                    }
                    tool_call_log.append(entry)
                    await progress("tool_end", entry)
                    # Reset failure counter on success
                    _consecutive_failures[tool_name] = 0
                except Exception as e:
                    result = f"Error: {type(e).__name__}: {e}"
                    entry = {
                        "tool_name": tool_name,
                        "tool_name_zh": tool_zh,
                        "status": "error",
                        "summary": _truncate(str(e)),
                    }
                    tool_call_log.append(entry)
                    await progress("tool_end", entry)
                    _consecutive_failures[tool_name] = (
                        _consecutive_failures.get(tool_name, 0) + 1
                    )
            else:
                result = f"Unknown tool: {tool_name}"
                entry = {
                    "tool_name": tool_name,
                    "tool_name_zh": tool_name,
                    "status": "error",
                    "summary": f"未知工具: {tool_name}",
                }
                tool_call_log.append(entry)
                await progress("tool_end", entry)

            messages.append(
                ToolMessage(
                    content=str(result),
                    tool_call_id=tc["id"],
                )
            )

        # If abort triggered, force LLM to give final text response
        if _should_abort:
            from langchain_core.messages import HumanMessage as _HM
            messages.append(
                _HM(content="工具已连续失败，请直接向用户回复说明情况。"),
            )

    # Max iterations reached — return graceful fallback
    fallback = AIMessage(content="操作步骤过多，请简化请求后重试。")
    fallback.tool_call_log = tool_call_log  # type: ignore[attr-defined]
    await progress("done", {"reply": fallback.content})
    return fallback
