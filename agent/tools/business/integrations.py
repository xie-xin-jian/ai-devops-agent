"""MCP, subagent, and compaction tool registration."""

from __future__ import annotations


from agent.mcp.client import connect_mcp
from agent.extensions.subagent import spawn_subagent


class IntegrationToolsMixin:
    def _add_subagent_tool(self):
        schema = {
            "name": "spawn_subagent",
            "description": "Spawn a subagent to work on a side task. The subagent has its own isolated context and returns a summary when done.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                },
                "required": ["description"],
            },
        }
        self.tool_registry.register(
            schema,
            lambda description: spawn_subagent(
                self.client,
                self.recovery.current_model,
                description,
                sandbox_manager=getattr(self, "sandbox_manager", None),
                run_id=getattr(self, "current_run_id", ""),
                tool_registry=self.tool_registry,
                principal=self.principal,
            ),
        )

    def _add_compact_tool(self):
        schema = {
            "name": "compact",
            "description": "Compact conversation history into a summary to free up context.",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        }

        def _compact():
            self._pending_compaction = True
            return "History compaction scheduled for the next safe boundary."

        self.tool_registry.register(schema, _compact)

    def _add_mcp_tools(self):
        """注册 connect_mcp 工具，让 Agent 能动态连接 MCP 服务器。"""
        schema = {
            "name": "connect_mcp",
            "description": "Connect to an MCP server (docs, deploy, metrics) and discover tools. Use this first to access external services.",
            "input_schema": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        }
        self.tool_registry.register(
            schema,
            lambda name: connect_mcp(
                name,
                owner_id=getattr(
                    getattr(self, "principal", None),
                    "id",
                    "",
                ),
                session_id=getattr(self, "session_id", ""),
                run_id=getattr(self, "current_run_id", ""),
                source="agent",
            ),
        )
