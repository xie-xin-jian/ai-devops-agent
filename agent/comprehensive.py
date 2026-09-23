"""
综合 Agent —— 所有运维机制组装在一个 loop 里。

将以下机制整合到同一个 agent loop 中，面向 DevOps 场景：
- 工具分发 (tool dispatch)
- 权限系统 (permission)
- 钩子系统 (hooks)
- 待办规划 (todo)
- 子 agent (subagent)
- 技能加载 (skills)
- 上下文压缩 (context compaction)
- 记忆系统 (memory)
- 系统提示组装 (prompt assembly)
- 错误恢复 (error recovery)
- 任务图 (task graph)
- 后台任务 (background tasks)
- 定时调度 (cron)

采用模块化拆分，可通过类实例化配置，便于多会话隔离与扩展。
"""

import json
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from anthropic import Anthropic

from .config import (
    WORKDIR, MODEL_ID, ANTHROPIC_BASE_URL, API_KEY,
    DEFAULT_MAX_TOKENS, CONTEXT_LIMIT, CONTINUATION_PROMPT,
    CLI_ACTIVE, MEMORY_SCOPE,
)
from .hooks import register_hook, trigger_hooks
from .permission import permission_hook
from .todo import todo_write
from .tools import ALL_TOOL_SCHEMAS, ALL_TOOL_HANDLERS

from .skill import list_skills, load_skill
from .subagent import spawn_subagent, extract_text, has_tool_use, call_tool_handler
from .context_compact import (
    estimate_size, tool_result_budget, micro_compact, snip_compact,
    compact_history, write_transcript,
)
from .error_recovery import (
    RecoveryState, with_retry, is_prompt_too_long_error,
    is_output_limit_error, escalate_tokens, recover_context_overflow,
)
from .task_system import (
    create_task, list_tasks, load_task, claim_task, complete_task,
    get_task_json, can_start,
)
from .background import (
    should_run_background, start_background_task, collect_background_results,
    list_background_tasks,
)
from .cron import schedule_job, cancel_job
from .memory import MemorySystem
from .mcp import (
    connect_mcp, disconnect_mcp, assemble_tool_pool, list_connected_mcp,
    is_mcp_tool, is_destructive_mcp_tool,
)
from .logger import logger


class ComprehensiveAgent:
    """综合 Agent —— 所有 harness 机制在一个 loop 里。"""

    @classmethod
    def get_tool_catalog(cls) -> list[dict]:
        """Build the complete tool schema list without requiring an API key."""
        catalog = object.__new__(cls)
        catalog.tools = []
        catalog.handlers = {}
        catalog._register_default_tools()
        return list(catalog.tools)

    def __init__(
        self,
        system_prompt: str = None,
        api_key: str = None,
        memory_scope: str | None = None,
    ):
        base_url = ANTHROPIC_BASE_URL if ANTHROPIC_BASE_URL else None
        key = api_key or API_KEY
        if not key:
            raise ValueError("API Key not found. Set ANTHROPIC_API_KEY or API_KEY in .env file.")
        kwargs = {"api_key": key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = Anthropic(**kwargs)
        self.model = MODEL_ID
        self.recovery = RecoveryState()
        self.memory = MemorySystem()
        self.memory_scope = (memory_scope or MEMORY_SCOPE).strip() or "global"
        self._last_user_query = ""
        self.messages: list = []
        self._pending_compaction = False
        self._register_default_hooks()
        self._register_default_tools()
        self.system_prompt = system_prompt or self._build_system_prompt()

    def _register_default_hooks(self):
        register_hook("PreToolUse", permission_hook)

    def _register_default_tools(self):
        self.tools = list(ALL_TOOL_SCHEMAS)
        self.handlers = dict(ALL_TOOL_HANDLERS)
        self._add_todo_tool()
        self._add_task_tools()
        self._add_skill_tools()
        self._add_memory_tools()
        self._add_subagent_tool()
        self._add_compact_tool()
        self._add_cron_tools()
        self._add_mcp_tools()
        self._add_background_tools()

    def _add_todo_tool(self):
        schema = {
            "name": "todo_write",
            "description": "Set or update the current todo list for your work.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "completed"],
                                },
                            },
                            "required": ["content", "status"],
                        },
                    },
                },
                "required": ["todos"],
            },
        }
        self.tools.append(schema)
        self.handlers["todo_write"] = lambda todos: todo_write(todos)

    def _add_task_tools(self):
        tools = [
            {
                "name": "create_task",
                "description": "Create a new task with optional dependencies.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "subject": {"type": "string"},
                        "description": {"type": "string"},
                        "blockedBy": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "priority": {
                            "type": "string",
                            "enum": ["low", "medium", "high"],
                            "default": "medium",
                        },
                    },
                    "required": ["subject"],
                },
            },
            {
                "name": "list_tasks",
                "description": "List all tasks and their status.",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "get_task",
                "description": "Get full details of a specific task.",
                "input_schema": {
                    "type": "object",
                    "properties": {"task_id": {"type": "string"}},
                    "required": ["task_id"],
                },
            },
            {
                "name": "claim_task",
                "description": "Claim a pending task for execution.",
                "input_schema": {
                    "type": "object",
                    "properties": {"task_id": {"type": "string"}},
                    "required": ["task_id"],
                },
            },
            {
                "name": "complete_task",
                "description": "Mark an in-progress task as completed.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"},
                        "result": {"type": "string"},
                    },
                    "required": ["task_id"],
                },
            },
        ]
        handlers = {
            "create_task": lambda subject, description="", blockedBy=None, priority="medium": (
                json.dumps({
                    "id": create_task(
                        subject, description, blockedBy, priority
                    ).id
                })
            ),
            "list_tasks": lambda: "\n".join(
                f"  {t.id}: {t.subject} [{t.status}]" + (f" (owner: {t.owner})" if t.owner else "")
                for t in list_tasks()
            ) or "No tasks.",
            "get_task": lambda task_id: get_task_json(task_id),
            "claim_task": lambda task_id: claim_task(task_id),
            "complete_task": lambda task_id, result="": complete_task(task_id, result),
        }
        self.tools.extend(tools)
        self.handlers.update(handlers)

    def _add_skill_tools(self):
        tools = [
            {
                "name": "list_skills",
                "description": "List all available skills.",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "load_skill",
                "description": "Load a specific skill's full content into context.",
                "input_schema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            },
        ]
        handlers = {
            "list_skills": lambda: list_skills(),
            "load_skill": lambda name: load_skill(name),
        }
        self.tools.extend(tools)
        self.handlers.update(handlers)

    def _add_memory_tools(self):
        tools = [
            {
                "name": "add_memory",
                "description": "Save a piece of information to long-term memory for future sessions.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "importance": {"type": "integer", "default": 3},
                        "category": {"type": "string", "default": "general"},
                        "memory_type": {
                            "type": "string",
                            "enum": [
                                "entity",
                                "semantic",
                                "episodic",
                                "procedural",
                            ],
                            "default": "semantic",
                        },
                        "entity_type": {"type": "string"},
                        "entity_key": {"type": "string"},
                        "entity_value": {"type": "string"},
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "scope": {"type": "string", "default": "global"},
                        "confidence": {
                            "type": "number",
                            "default": 0.8,
                        },
                    },
                    "required": ["content"],
                },
            },
            {
                "name": "search_memory",
                "description": "Search long-term memory for relevant past information.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "scope": {"type": "string"},
                        "memory_type": {
                            "type": "string",
                            "enum": [
                                "entity",
                                "semantic",
                                "episodic",
                                "procedural",
                            ],
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "update_memory",
                "description": "Update a long-term memory by id.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "memory_id": {"type": "string"},
                        "content": {"type": "string"},
                        "importance": {"type": "integer"},
                        "category": {"type": "string"},
                        "memory_type": {
                            "type": "string",
                            "enum": [
                                "entity",
                                "semantic",
                                "episodic",
                                "procedural",
                            ],
                        },
                        "entity_type": {"type": "string"},
                        "entity_key": {"type": "string"},
                        "entity_value": {"type": "string"},
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "scope": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                    "required": ["memory_id"],
                },
            },
            {
                "name": "archive_memory",
                "description": "Archive a long-term memory without deleting it.",
                "input_schema": {
                    "type": "object",
                    "properties": {"memory_id": {"type": "string"}},
                    "required": ["memory_id"],
                },
            },
            {
                "name": "delete_memory",
                "description": (
                    "Soft-delete a long-term memory. The record is retained "
                    "for audit and can be restored."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {"memory_id": {"type": "string"}},
                    "required": ["memory_id"],
                },
            },
            {
                "name": "restore_memory",
                "description": "Restore an archived or deleted memory.",
                "input_schema": {
                    "type": "object",
                    "properties": {"memory_id": {"type": "string"}},
                    "required": ["memory_id"],
                },
            },
        ]

        def _add_memory(
            content,
            importance=3,
            category="general",
            memory_type="semantic",
            entity_type="",
            entity_key="",
            entity_value="",
            tags=None,
            scope=None,
            confidence=0.8,
        ):
            memory = self.memory.add(
                content,
                importance,
                category,
                memory_type=memory_type,
                entity_type=entity_type,
                entity_key=entity_key,
                entity_value=entity_value,
                tags=tags,
                scope=scope or self.memory_scope,
                confidence=confidence,
            )
            if memory.get("status") == "candidate":
                return (
                    f"Memory saved as candidate (id={memory['id']}): "
                    f"{content[:80]}"
                )
            return f"Memory saved (id={memory['id']}): {content[:80]}"

        def _search_memory(query, scope=None, memory_type=None):
            return self.memory.format_relevant(
                query,
                scope=scope or self.memory_scope,
                memory_type=memory_type,
            )

        def _update_memory(
            memory_id,
            content=None,
            importance=None,
            category=None,
            memory_type=None,
            entity_type=None,
            entity_key=None,
            entity_value=None,
            tags=None,
            scope=None,
            confidence=None,
        ):
            memory = self.memory.update(
                memory_id,
                content=content,
                importance=importance,
                category=category,
                memory_type=memory_type,
                entity_type=entity_type,
                entity_key=entity_key,
                entity_value=entity_value,
                tags=tags,
                scope=scope,
                confidence=confidence,
            )
            return f"Memory updated: {memory['id']} (version={memory['version']})"

        def _archive_memory(memory_id):
            memory = self.memory.archive(memory_id)
            return f"Memory archived: {memory['id']}"

        def _delete_memory(memory_id):
            memory = self.memory.delete(memory_id)
            return f"Memory soft-deleted: {memory['id']}"

        def _restore_memory(memory_id):
            memory = self.memory.restore(memory_id)
            return f"Memory restored: {memory['id']}"

        handlers = {
            "add_memory": _add_memory,
            "search_memory": _search_memory,
            "update_memory": _update_memory,
            "archive_memory": _archive_memory,
            "delete_memory": _delete_memory,
            "restore_memory": _restore_memory,
        }
        self.tools.extend(tools)
        self.handlers.update(handlers)

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
        self.tools.append(schema)
        self.handlers["spawn_subagent"] = lambda description: spawn_subagent(
            self.client, self.recovery.current_model, description
        )

    def _add_compact_tool(self):
        schema = {
            "name": "compact",
            "description": "Compact conversation history into a summary to free up context.",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        }
        self.tools.append(schema)

        def _compact():
            self._pending_compaction = True
            return "History compaction scheduled for the next safe boundary."

        self.handlers["compact"] = _compact

    def _add_cron_tools(self):
        tools = [
            {
                "name": "schedule_cron",
                "description": "Schedule a recurring prompt using cron syntax (5 fields: min hour dom month dow). Cron jobs will auto-execute in background at the scheduled time (no need to wait for user message).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "cron": {"type": "string"},
                        "prompt": {"type": "string"},
                        "recurring": {"type": "boolean", "default": True},
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "enabled": {"type": "boolean", "default": True},
                    },
                    "required": ["cron", "prompt"],
                },
            },
            {
                "name": "list_crons",
                "description": "List all scheduled cron jobs with their last run status.",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "cancel_cron",
                "description": "Cancel a scheduled cron job by ID.",
                "input_schema": {
                    "type": "object",
                    "properties": {"job_id": {"type": "string"}},
                    "required": ["job_id"],
                },
            },
            {
                "name": "list_cron_logs",
                "description": "List cron job execution history (recent N runs). Each entry has fired_at, finished_at, success, output, error.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "job_id": {"type": "string", "description": "Optional. Filter by specific job ID."},
                        "limit": {"type": "integer", "default": 10, "description": "Max number of logs to return, default 10."},
                    },
                    "required": [],
                },
            },
        ]
        from .cron import scheduled_jobs, _last_fired, list_cron_run_logs

        def _schedule(
            cron,
            prompt,
            recurring=True,
            name="",
            description="",
            enabled=True,
        ):
            job, message = schedule_job(
                cron,
                prompt,
                recurring,
                name=name,
                description=description,
                enabled=enabled,
            )
            if job is None:
                return message
            label = job.name or job.id
            return f"Scheduled {job.id} ({label}, {job.cron})"

        handlers = {
            "schedule_cron": _schedule,
            "list_crons": lambda: "\n".join(
                f"  {j.id}: {j.name or '(unnamed)'} | {j.cron}"
                f" {'recurring' if j.recurring else 'once'}"
                f" | last_run={_last_fired.get(j.id).strftime('%H:%M:%S') if _last_fired.get(j.id) else 'never'}"
                f" | prompt={j.prompt[:50]}"
                for j in scheduled_jobs.values()
            ) or "No scheduled jobs.",
            "cancel_cron": lambda job_id: cancel_job(job_id),
            "list_cron_logs": lambda job_id=None, limit=10: (
                (lambda logs: "\n".join(
                    f"  [{log.get('fired_at', '?')}] job={log.get('job_id','?')[:12]} "
                    f"success={log.get('success')} "
                    f"{(log.get('output') or '')[:80]}"
                    f"{' error=' + str(log.get('error'))[:60] if log.get('error') else ''}"
                    for log in logs
                ) or "No cron run logs yet.")(list_cron_run_logs(job_id=job_id, limit=limit))
            ),
        }
        self.tools.extend(tools)
        self.handlers.update(handlers)

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
        self.tools.append(schema)
        self.handlers["connect_mcp"] = lambda name: connect_mcp(name)

    def _add_background_tools(self):
        schema = {
            "name": "list_background_tasks",
            "description": (
                "List all background tasks with their current status (running/completed). "
                "By default output is summarized; set full=true for complete captured output. "
                "Does NOT consume/modify them — safe to call repeatedly. "
                "Use this to check whether a background task finished and read its result. "
                "Prefer this over collect_background_results when you need to re-check a task."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "full": {
                        "type": "boolean",
                        "default": False,
                        "description": "Return complete captured output instead of a head/tail summary.",
                    },
                },
                "required": [],
            },
        }
        self.tools.append(schema)
        self.handlers["list_background_tasks"] = (
            lambda full=False: list_background_tasks(full=full)
        )

    def _build_system_prompt(self) -> str:
        tool_names = [t["name"] for t in self.tools]
        sections = [
            "You are an AI DevOps assistant. Act, don't explain.",
            f"Available tools: {', '.join(tool_names)}",
            f"Working directory: {WORKDIR}",
            f"Current time: {datetime.now().isoformat(timespec='seconds')}",
            "Skills catalog:\n" + list_skills() + "\nUse load_skill(name) when a skill is relevant.",
        ]
        if self._last_user_query:
            memories_text = self.memory.format_relevant(
                self._last_user_query,
                scope=self.memory_scope,
            )
            if not memories_text.startswith("(no relevant"):
                sections.append("Relevant memories:\n" + memories_text)
        mcp_names = [s["name"] for s in list_connected_mcp()]
        if mcp_names:
            sections.append(f"Connected MCP servers: {', '.join(mcp_names)}")
            sections.append("MCP tools are prefixed mcp__{server}__{tool}.")
        return "\n\n".join(sections)

    def _call_api(self, messages: list):
        # 动态合并 MCP 工具：每次调用 API 前把已连接的 MCP 服务器工具合并进来
        tools, _ = assemble_tool_pool(self.tools, self.handlers)
        # 刷新系统提示（MCP 连接可能变化）
        system_prompt = self._build_system_prompt()

        def _call():
            return self.client.messages.create(
                model=self.recovery.current_model,
                system=system_prompt,
                messages=messages,
                tools=tools,
                max_tokens=self.recovery.current_max_tokens,
            )

        return with_retry(_call, self.recovery)

    def _compact_if_needed(self, messages: list) -> list:
        messages = tool_result_budget(messages)
        messages = micro_compact(messages)
        if estimate_size(messages) > CONTEXT_LIMIT:
            messages = snip_compact(messages)
        return messages

    def _handle_tool_call(self, block):
        blocked = trigger_hooks("PreToolUse", block)
        if blocked:
            return str(blocked)

        if block.name == "bash" and should_run_background(block.name, block.input):
            bg_id = start_background_task(
                block, self.handlers,
                lambda blk, out: trigger_hooks("PostToolUse", blk, out),
            )
            return f"Background task started: {bg_id}\nCheck results with list_background_tasks."

        # 动态获取 handlers（包含 MCP 工具）
        _, handlers = assemble_tool_pool(self.tools, self.handlers)
        handler = handlers.get(block.name)
        output = call_tool_handler(handler, block.input, block.name)
        trigger_hooks("PostToolUse", block, output)
        return output

    @staticmethod
    def _is_cancelled(cancel_event) -> bool:
        return cancel_event is not None and cancel_event.is_set()

    def _cancelled_event(self) -> dict:
        text = "已停止生成。"
        self.messages.append({
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
        })
        return {"type": "cancelled", "text": text}

    def run(self, user_message: str, cancel_event=None) -> str:
        """同步执行 Agent 循环（非流式，保持原有行为不变）。"""
        final_text = None
        for event in self.run_stream(user_message, cancel_event):
            if event["type"] == "done":
                final_text = event["text"]
            elif event["type"] == "cancelled":
                final_text = event["text"]
            elif event["type"] == "error":
                raise RuntimeError(event["message"])
        return final_text or ""

    def run_stream(self, user_message: str, cancel_event=None):
        """流式执行 Agent 循环，每步 yield 一个事件 dict。

        事件类型：
          {"type": "status", "message": str, "turn": int}
          {"type": "tool_use", "tool": str, "input": dict, "turn": int}
          {"type": "tool_result", "tool": str, "output": str, "turn": int, "duration_ms": int}
          {"type": "thinking", "turn": int}
          {"type": "done", "text": str, "total_turns": int}
          {"type": "cancelled", "text": str}
          {"type": "error", "message": str}
        """
        trigger_hooks("UserPromptSubmit", user_message)
        self._last_user_query = user_message
        self.messages.append({"role": "user", "content": user_message})
        logger.info(f"[user] {user_message[:200]}")

        if self._is_cancelled(cancel_event):
            yield self._cancelled_event()
            return

        yield {"type": "status", "message": "准备中...", "turn": 0}

        bg_notifications = collect_background_results()
        if bg_notifications:
            self.messages.append({
                "role": "user",
                "content": "\n\n".join(bg_notifications),
            })
            yield {"type": "status", "message": f"收到 {len(bg_notifications)} 条后台任务通知", "turn": 0}
            logger.info(f"[bg] 收到 {len(bg_notifications)} 条后台任务通知")

        max_turns = 50
        final_text = ""
        last_assistant_text = ""
        context_recovery_attempts = 0
        max_context_recovery_attempts = 2

        for turn in range(max_turns):
            if self._is_cancelled(cancel_event):
                yield self._cancelled_event()
                return

            yield {"type": "status", "message": f"第 {turn+1} 轮：压缩上下文", "turn": turn+1}
            self.messages = self._compact_if_needed(self.messages)

            yield {"type": "thinking", "turn": turn+1}
            yield {"type": "status", "message": f"第 {turn+1} 轮：调用大模型 ({self.model})", "turn": turn+1}
            logger.info(f"[turn {turn+1}] 调用 {self.recovery.current_model} (ctx {estimate_size(self.messages)} bytes)")

            try:
                response = self._call_api(self.messages)
            except Exception as e:
                if is_prompt_too_long_error(e):
                    if context_recovery_attempts >= max_context_recovery_attempts:
                        yield {
                            "type": "error",
                            "message": "上下文压缩后仍然超过模型限制",
                        }
                        return

                    context_recovery_attempts += 1
                    yield {
                        "type": "status",
                        "message": "Prompt 过长，执行上下文恢复压缩...",
                        "turn": turn + 1,
                    }
                    logger.warning(
                        f"[turn {turn+1}] Prompt 过长，执行 "
                        "recover_context_overflow"
                    )

                    try:
                        compacted, stats = recover_context_overflow(
                            self.messages,
                            self.client,
                            self.recovery.current_model,
                        )
                    except Exception as compact_error:
                        logger.error(
                            f"[turn {turn+1}] 上下文压缩失败: {compact_error}"
                        )
                        yield {
                            "type": "error",
                            "message": f"上下文压缩失败: {compact_error}",
                        }
                        return

                    self.messages = compacted
                    logger.info(
                        f"[turn {turn+1}] context recovery: "
                        f"{stats['before']} -> {stats['after']} bytes"
                    )
                    if not stats["reduced"]:
                        yield {
                            "type": "error",
                            "message": "上下文压缩未有效缩小输入，无法继续调用模型",
                        }
                        return
                    continue

                if is_output_limit_error(e):
                    if escalate_tokens(self.recovery):
                        yield {
                            "type": "status",
                            "message": (
                                "输出 Token 上限扩容到 "
                                f"{self.recovery.current_max_tokens}"
                            ),
                            "turn": turn + 1,
                        }
                        logger.warning(
                            f"[turn {turn+1}] 输出 Token 上限扩容到 "
                            f"{self.recovery.current_max_tokens}"
                        )
                        continue

                yield {"type": "error", "message": str(e)}
                logger.error(f"[turn {turn+1}] API 异常: {e}")
                return

            if self._is_cancelled(cancel_event):
                yield self._cancelled_event()
                return

            self.messages.append({"role": "assistant", "content": response.content})

            # 收集这段文字回复（如果有）
            for block in response.content:
                if block.type == "text":
                    last_assistant_text = block.text

            if not has_tool_use(response.content):
                # LLM 认为不需要调工具了，输出最终文字
                final_text = extract_text(response.content)
                logger.info(f"[turn {turn+1}] 完成: {len(final_text or '')} 字符")
                if final_text:
                    # 逐字流式输出最终文字（前端能看到逐字出现）
                    for word in final_text.split(" "):
                        yield {"type": "text_delta", "delta": word + " "}
                break

            # 执行所有工具调用
            results = []
            for block_index, block in enumerate(response.content):
                if block.type != "tool_use":
                    continue

                if self._is_cancelled(cancel_event):
                    for remaining in response.content[block_index:]:
                        if remaining.type == "tool_use":
                            results.append({
                                "type": "tool_result",
                                "tool_use_id": remaining.id,
                                "content": "Error: cancelled by user",
                            })
                    if results:
                        self.messages.append({"role": "user", "content": results})
                    yield self._cancelled_event()
                    return

                logger.info(f"[turn {turn+1}] tool_use: {block.name}")
                yield {
                    "type": "tool_use",
                    "tool": block.name,
                    "input": block.input if isinstance(block.input, dict) else {"input": str(block.input)},
                    "turn": turn+1,
                }

                t0 = time.time()
                try:
                    output = self._handle_tool_call(block)
                except Exception as tool_err:
                    output = f"Error: {tool_err}"
                    logger.error(f"[turn {turn+1}] tool {block.name} 异常: {tool_err}")
                duration_ms = int((time.time() - t0) * 1000)
                logger.info(f"[turn {turn+1}] tool_done: {block.name} ({duration_ms}ms)")

                output_str = str(output)
                # 截断太长的输出
                if len(output_str) > 2000:
                    output_str = output_str[:2000] + "\n... (truncated)"

                yield {
                    "type": "tool_result",
                    "tool": block.name,
                    "output": output_str,
                    "turn": turn+1,
                    "duration_ms": duration_ms,
                }

                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(output),
                })

            self.messages.append({"role": "user", "content": results})

            if self._pending_compaction:
                self.messages = compact_history(
                    self.messages,
                    self.client,
                    self.recovery.current_model,
                )
                self._pending_compaction = False

        trigger_hooks("Stop", self.messages)

        # 如果循环结束但没拿到 final_text，从后往前找
        if not final_text:
            for msg in reversed(self.messages):
                if msg["role"] == "assistant":
                    final_text = extract_text(msg["content"])
                    if final_text:
                        break

        yield {"type": "done", "text": final_text, "total_turns": turn + 1}
        logger.info(f"[done] 共 {turn + 1} 轮, 输出 {len(final_text)} 字符")

    def get_messages(self) -> list:
        return list(self.messages)

    def reset(self):
        self.messages = []
        self._pending_compaction = False
        self.recovery = RecoveryState()


def create_devops_agent() -> ComprehensiveAgent:
    """创建一个 DevOps 场景的 Agent 实例。"""
    return ComprehensiveAgent()
