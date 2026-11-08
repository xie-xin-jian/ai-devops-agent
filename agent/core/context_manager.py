"""Prompt assembly and context compaction shared by the Agent facade."""

from __future__ import annotations

from datetime import datetime

from agent.platform.config import CONTEXT_BYTES_BUDGET, CONTEXT_LIMIT, WORKDIR
from agent.core.context_compact import (
    estimate_size,
    micro_compact,
    snip_compact,
    tool_result_budget,
    trim_by_size,
)
from agent.mcp.client import assemble_tool_pool, list_connected_mcp
from agent.memory.policy import readable_scopes
from agent.orchestration.tasks import list_tasks
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
            "health, so results stay structured. Use http_check for HTTP health "
            "checks instead of curl. Simple inspection commands in bash "
            "(ss -tlnp, df -h, curl GET, pgrep) are auto-redirected to the "
            "dedicated tool; call the tool directly.",
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
        return "\n\n".join(sections)

    def _active_tasks_note(self) -> str:
        """Inject the session's active tasks so plans survive across turns."""
        session_id = getattr(self, "session_id", "")
        if not session_id:
            return ""
        try:
            tasks = list_tasks(
                session_id=session_id,
                statuses=("pending", "in_progress"),
                limit=8,
            )
        except Exception:
            return ""
        if not tasks:
            return ""
        status_rank = {"in_progress": 0, "pending": 1}
        priority_rank = {"high": 0, "medium": 1, "low": 2}
        tasks = sorted(
            tasks,
            key=lambda task: (
                status_rank.get(task.status, 9),
                priority_rank.get(task.priority, 9),
                task.created_at,
            ),
        )[:8]
        lines = []
        for task in tasks:
            line = f"- {task.id}: {task.subject[:80]} [{task.status}]"
            if task.blockedBy:
                line += f" (blockedBy: {', '.join(task.blockedBy)})"
            lines.append(line)
        return (
            "Active tasks (this session):\n"
            + "\n".join(lines)
            + "\nClaim before starting an item; complete with a concrete result."
        )

    def _runtime_tail_note(self) -> str:
        """每轮变化的上下文（时间、任务、记忆、MCP 连接）。

        刻意不放进 system prompt：供应商按前缀缓存，把秒级时间或按问题
        检索出的记忆放进去会让每次调用的前缀都不同，缓存全部失效。
        """
        parts = [f"Current time: {datetime.now().isoformat(timespec='seconds')}"]
        tasks_note = self._active_tasks_note()
        if tasks_note:
            parts.append(tasks_note)
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
                parts.append("Relevant memories:\n" + memories_text)
        mcp_names = [s["name"] for s in list_connected_mcp()]
        if mcp_names:
            parts.append(
                f"Connected MCP servers: {', '.join(mcp_names)}\n"
                "MCP tools are prefixed mcp__{server}__{tool}."
            )
        return "\n\n".join(parts)

    def _inject_runtime_context(self, messages: list) -> list:
        """把动态上下文追加到最后一条 user 消息末尾。

        只改尾部，保证前面所有内容的前缀保持稳定，从而命中 prompt cache。
        返回新列表，不修改调用方持有的历史（不落盘）。
        """
        note = self._runtime_tail_note()
        if not note or not messages:
            return messages
        last = len(messages) - 1
        if messages[last].get("role") != "user":
            return messages
        injected = list(messages)
        tail = dict(messages[last])
        content = tail.get("content")
        if isinstance(content, str):
            tail["content"] = f"{content}\n\n{note}" if content else note
        elif isinstance(content, list):
            # tool_result 块必须在最前，文本块追加在其后
            tail["content"] = list(content) + [{"type": "text", "text": note}]
        else:
            tail["content"] = note
        injected[last] = tail
        return injected

    def _compact_if_needed(self, messages: list) -> list:
        messages = tool_result_budget(messages)
        size = estimate_size(messages)
        # 只有真的超过水位才做有损压缩：micro_compact 每轮改写中段历史
        # 会让 prompt cache 前缀失效，因此不能无条件执行。
        if size > CONTEXT_LIMIT:
            messages = micro_compact(messages)
            size = estimate_size(messages)
        if size > CONTEXT_LIMIT:
            messages = snip_compact(messages)
        return trim_by_size(messages, CONTEXT_BYTES_BUDGET)
