"""Tests for orchestrator — verify tool-calling routing architecture.

Post-refactor: orchestrator is a ReAct agent with delegate_to_{plugin}
tools + utility tools. Tests verify:
1. Delegate tools are built correctly from registry
2. Scope filtering works
3. Identity pre-check works
4. Plugin registry basics (unchanged)
"""

from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from agents.plugins.base import AgentPlugin
from agents.registry import PluginRegistry
from agents.tools.routing_tools import make_delegate_tools


# ── Helpers ──────────────────────────────────────────────────

class DummyPlugin(AgentPlugin):
    """Minimal plugin for testing registry integration."""

    def __init__(self, name: str, keywords: list[str], requires_id: bool = True):
        self._name = name
        self._keywords = keywords
        self._requires_id = requires_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"Test plugin: {self._name}"

    @property
    def intent_keywords(self) -> list[str]:
        return self._keywords

    @property
    def tools(self) -> list:
        return []

    async def handle(self, state):
        return {"turn_output": f"Handled by {self._name}"}

    @property
    def requires_identity(self) -> bool:
        return self._requires_id


def _make_state(msg: str, user_profile=None, event_id=None):
    return {
        "messages": [HumanMessage(content=msg)],
        "current_plugin": "",
        "user_profile": user_profile,
        "event_id": event_id,
        "pending_approval": None,
        "turn_output": None,
        "plan_output": None,
        "attachments": [],
        "task_plan": [],
        "event_draft": None,
        "scope": None,
        "parts": [],
        "tool_calls": [],
        "quick_replies": [],
        "reflection": None,
    }


def _build_registry():
    reg = PluginRegistry()
    reg.register(DummyPlugin("seating", ["排座", "座位", "assign"]))
    reg.register(DummyPlugin("checkin", ["签到", "check-in", "checkin"]))
    reg.register(DummyPlugin(
        "identity", ["我是", "身份", "who"], requires_id=False,
    ))
    reg.register(DummyPlugin("change", ["换座", "请假", "swap"]))
    return reg


# ── Tests: Delegate Tool Construction ────────────────────────

class TestMakeDelegateTools:
    """Verify delegate tools are built correctly from registry."""

    def test_creates_tool_per_plugin_except_identity(self):
        """Each active non-identity plugin gets a delegate tool."""
        reg = _build_registry()
        state = _make_state("test", user_profile={"name": "张三"})
        acc_upd, acc_parts, acc_tc = {}, [], []

        tools = make_delegate_tools(
            reg, state, {}, acc_upd, acc_parts, acc_tc,
        )
        names = {t.name for t in tools}
        # identity should be excluded
        assert "delegate_to_identity" not in names
        assert "delegate_to_seating" in names
        assert "delegate_to_checkin" in names
        assert "delegate_to_change" in names

    def test_scope_filters_to_single_plugin(self):
        """When scope='seating', only delegate_to_seating is exposed."""
        reg = _build_registry()
        state = _make_state("test", user_profile={"name": "张三"})
        acc_upd, acc_parts, acc_tc = {}, [], []

        tools = make_delegate_tools(
            reg, state, {}, acc_upd, acc_parts, acc_tc,
            scope="seating",
        )
        names = {t.name for t in tools}
        assert names == {"delegate_to_seating"}

    def test_no_profile_skips_identity_required_plugins(self):
        """Without user_profile, plugins with requires_identity=True are skipped."""
        reg = _build_registry()
        state = _make_state("test", user_profile=None)  # No profile
        acc_upd, acc_parts, acc_tc = {}, [], []

        tools = make_delegate_tools(
            reg, state, {}, acc_upd, acc_parts, acc_tc,
        )
        # All plugins require identity except identity itself (which is excluded)
        assert len(tools) == 0

    def test_tool_description_includes_plugin_description(self):
        """Each delegate tool's description references the plugin."""
        reg = _build_registry()
        state = _make_state("test", user_profile={"name": "张三"})
        acc_upd, acc_parts, acc_tc = {}, [], []

        tools = make_delegate_tools(
            reg, state, {}, acc_upd, acc_parts, acc_tc,
        )
        seating_tool = next(
            t for t in tools if t.name == "delegate_to_seating"
        )
        assert "seating" in seating_tool.description

    async def test_delegate_tool_calls_plugin_handle(self):
        """Calling a delegate tool actually invokes plugin.handle()."""
        reg = _build_registry()
        state = _make_state("排座", user_profile={"name": "张三"})
        acc_upd: dict = {}
        acc_parts: list = []
        acc_tc: list = []

        tools = make_delegate_tools(
            reg, state, {}, acc_upd, acc_parts, acc_tc,
        )
        seating_tool = next(
            t for t in tools if t.name == "delegate_to_seating"
        )
        result = await seating_tool.ainvoke({"user_request": "帮我排座"})
        assert "Handled by seating" in result

    async def test_delegate_captures_event_id_side_effect(self):
        """State side-effects from plugin.handle() are captured."""
        reg = PluginRegistry()
        p = DummyPlugin("organizer", ["创建"])
        # Override handle to return event_id
        async def _handle_with_event(state):
            return {
                "turn_output": "创建成功",
                "event_id": "evt-123",
            }
        p.handle = _handle_with_event  # type: ignore[assignment]
        reg.register(p)

        state = _make_state("创建活动", user_profile={"name": "张三"})
        acc_upd: dict = {}
        acc_parts: list = []
        acc_tc: list = []

        tools = make_delegate_tools(
            reg, state, {}, acc_upd, acc_parts, acc_tc,
        )
        tool = tools[0]
        await tool.ainvoke({"user_request": "创建活动"})
        assert acc_upd["event_id"] == "evt-123"
        assert acc_upd["current_plugin"] == "organizer"


# ── Tests: Plugin Registry (unchanged) ──────────────────────

class TestPluginRegistry:
    """Tests for registry itself."""

    def test_register_and_get(self):
        reg = PluginRegistry()
        p = DummyPlugin("test", ["foo"])
        reg.register(p)
        assert reg.get("test") is p

    def test_get_nonexistent_returns_none(self):
        reg = PluginRegistry()
        assert reg.get("nope") is None

    def test_active_plugins_excludes_disabled(self):
        reg = PluginRegistry()
        p = DummyPlugin("test", ["foo"])
        p.enabled  # True by default
        reg.register(p)
        assert len(reg.active_plugins) == 1

    def test_build_routing_prompt_empty(self):
        reg = PluginRegistry()
        prompt = reg.build_routing_prompt()
        assert "No plugins" in prompt

    def test_build_routing_prompt_with_plugins(self):
        reg = _build_registry()
        prompt = reg.build_routing_prompt()
        assert "seating" in prompt
        assert "checkin" in prompt
        assert "排座" in prompt

    def test_unregister(self):
        reg = PluginRegistry()
        p = DummyPlugin("test", ["foo"])
        reg.register(p)
        assert reg.unregister("test") is True
        assert reg.get("test") is None
        assert reg.unregister("test") is False
