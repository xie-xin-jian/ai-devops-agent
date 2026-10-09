"""Business tool registration entry point."""

from __future__ import annotations

from agent.tools.registry import ToolRegistry


class BusinessRegistrationMixin:
    def _register_default_tools(self):
        self.tool_registry = ToolRegistry.builtin()
        self._add_todo_tool()
        self._add_task_tools()
        self._add_skill_tools()
        self._add_memory_tools()
        self._add_subagent_tool()
        self._add_compact_tool()
        self._add_cron_tools()
        self._add_mcp_tools()
        self._add_background_tools()
