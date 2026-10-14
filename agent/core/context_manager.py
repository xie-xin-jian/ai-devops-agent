"""Prompt assembly and context compaction shared by the Agent facade."""

from __future__ import annotations

from datetime import datetime

from agent.platform.config import CONTEXT_LIMIT, WORKDIR
from agent.core.context_compact import (
    estimate_size,
    micro_compact,
    snip_compact,
    tool_result_budget,
)
from agent.mcp.client import assemble_tool_pool, list_connected_mcp
from agent.memory.policy import readable_scopes
from agent.platform.identity import system_admin_principal
from agent.platform.skill import list_skills
from agent.tools.registry import ToolRegistry


class ContextManagerMixin:
    def _mcp_context(self) -> dict:
        return {
            "owner_id": getattr(
                getattr(self, "principal", None),
                "id",
                "",
            ),
            "session_id": getattr(self, "session_id", ""),
            "run_id": getattr(self, "current_run_id", ""),
        }

    def _runtime_tool_registry(self) -> ToolRegistry:
        tools, handlers = assemble_tool_pool(
            self.tool_registry.schemas(),
            self.tool_registry.handlers(),
            self._mcp_context(),
        )
        return self.tool_registry.with_dynamic_tools(tools, handlers)

    def _build_system_prompt(self) -> str:
        tool_context = getattr(self, "tool_context", None)
        registry = self._runtime_tool_registry()
        tool_names = [tool["name"] for tool in registry.filtered_schemas(tool_context)]
        sections = [
            "You are an AI DevOps assistant. Act, don't explain.",
            f"Available tools: {', '.join(tool_names)}",
            f"Working directory: {WORKDIR}",
            f"Current time: {datetime.now().isoformat(timespec='seconds')}",
            "bash runs on the host only after user approval. Its default "
            "working directory is the active target root. Sandbox file tools "
            "are not a substitute for target_* tools.",
            "Skills catalog:\n"
            + list_skills()
            + "\nUse load_skill(name) when a skill is relevant.",
            "Tool usage policy:\n"
            "- Plan multi-step work (3+ steps, or work spanning several turns) "
            "with create_task before starting; claim_task when you begin an item; "
            "complete_task with a concrete result when done. Keep task lists small "
            "and relevant - skip them for a single quick action.\n"
            "- Persist durable, reusable facts (service endpoints, host quirks, "
            "deploy/rollback procedures, user preferences) with add_memory. "
            "Call search_memory before re-investigating something you may already "
            "know, and prefer update_memory over adding duplicates. Do NOT store "
            "ephemeral run output or secrets.\n"
            "- For recurring work (health checks, log sweeps, cert renewals) use "
            "schedule_cron rather than ad-hoc loops.\n"
            "- Delegate an independent, long-running investigation to spawn_subagent "
            "when its output would otherwise flood the main context; you receive "
            "only its summary. Keep the subagent's scope self-contained.\n"
            "- Prefer the dedicated inspection tools (cpu_usage, memory_usage, "
            "disk_io, process_top, ping_host) over raw bash when checking system "
            "health, so results stay structured.",
        ]
        target = getattr(self, "target", None)
        if target is not None:
            sections.append(
                "Active project target:\n"
                f"- id: {target.id}\n"
                f"- name: {target.name}\n"
                f"- root: {target.root}\n"
                f"- service: {target.service or '(not configured)'}\n"
                f"- health_url: {target.health_url or '(not configured)'}\n"
                "Use target_* tools for this project. Do not use sandbox "
                "read_file/glob for host project paths."
            )
        else:
            sections.append(
                "No active project target is selected. Ask the user to "
                "choose one in the Targets page before inspecting or "
                "operating a host project."
            )
        if self._last_user_query:
            principal = getattr(self, "principal", None) or system_admin_principal()
            memories_text = self.memory.format_relevant(
                self._last_user_query,
                scopes=readable_scopes(
                    principal,
                    default_scope=self.memory_scope,
                    session_id=getattr(self, "session_id", ""),
                ),
            )
            if not memories_text.startswith("(no relevant"):
                sections.append("Relevant memories:\n" + memories_text)
        mcp_names = [s["name"] for s in list_connected_mcp()]
        if mcp_names:
            sections.append(f"Connected MCP servers: {', '.join(mcp_names)}")
            sections.append("MCP tools are prefixed mcp__{server}__{tool}.")
        return "\n\n".join(sections)

    def _compact_if_needed(self, messages: list) -> list:
        messages = tool_result_budget(messages)
        messages = micro_compact(messages)
        if estimate_size(messages) > CONTEXT_LIMIT:
            messages = snip_compact(messages)
        return messages
