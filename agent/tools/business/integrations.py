"""MCP, subagent, and compaction tool registration."""

from __future__ import annotations


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
