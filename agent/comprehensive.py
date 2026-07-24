"""
s20 风格的综合 Agent —— 所有机制组装在一个 loop 里。

基于 learn-claude-code s20 的设计理念，将以下机制整合到同一个 agent loop 中：
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

与 s20 教学版的区别：模块化拆分，可通过类实例化配置。
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
    CLI_ACTIVE,
)
from .hooks import HOOKS, register_hook, trigger_hooks
from .permission import permission_hook
from .todo import todo_write, CURRENT_TODOS
from .tools import ALL_TOOL_SCHEMAS, ALL_TOOL_HANDLERS
from .tools.shell import run_bash
from .tools.file_tools import run_read, run_write, run_edit, run_glob
from .skill import list_skills, load_skill
from .subagent import spawn_subagent, extract_text, has_tool_use, call_tool_handler
from .context_compact import (
    estimate_size, tool_result_budget, micro_compact, snip_compact,
    compact_history, reactive_compact, write_transcript,
)
from .error_recovery import (
    RecoveryState, with_retry, is_prompt_too_long_error, escalate_tokens,
)
from .task_system import (
    create_task, list_tasks, load_task, claim_task, complete_task,
    get_task_json, can_start,
)
from .background import (
    should_run_background, start_background_task, collect_background_results,
)
from .cron import (
    schedule_job, cancel_job, consume_cron_queue, cron_scheduler_loop,
    load_durable_jobs,
)
from .memory import MemorySystem
from .mcp import (
    connect_mcp, disconnect_mcp, assemble_tool_pool, list_connected_mcp,
    is_mcp_tool, is_destructive_mcp_tool,
)


class ComprehensiveAgent:
    """综合 Agent —— 所有 harness 机制在一个 loop 里。"""

    def __init__(self, system_prompt: str = None, enable_cron: bool = False, api_key: str = None):
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
        self.messages: list = []
        self._register_default_hooks()
        self._register_default_tools()
        self.system_prompt = system_prompt or self._build_system_prompt()
        self._cron_thread = None
        if enable_cron:
            self._start_cron()

    def _register_default_hooks(self):
        register_hook("PreToolUse", permission_hook)

        def log_hook(block):
            name = getattr(block, "name", None) or (block.get("name") if isinstance(block, dict) else None)
            return None

        register_hook("PreToolUse", log_hook)

        def large_output_hook(block, output):
            return None

        register_hook("PostToolUse", large_output_hook)

        def stop_hook(messages):
            return None

        register_hook("Stop", stop_hook)

        def user_prompt_hook(query):
            return None

        register_hook("UserPromptSubmit", user_prompt_hook)

    def _register_default_tools(self):
        self.tools = list(ALL_TOOL_SCHEMAS)
        self.handlers = dict(ALL_TOOL_HANDLERS)
        self._add_todo_tool()
        self._add_task_tools()
        self._add_skill_tools()
        self._add_subagent_tool()
        self._add_compact_tool()
        self._add_cron_tools()
        self._add_mcp_tools()

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
                    "properties": {"task_id": {"type": "string"}},
                    "required": ["task_id"],
                },
            },
        ]
        handlers = {
            "create_task": lambda subject, description="", blockedBy=None: (
                json.dumps({"id": create_task(subject, description, blockedBy).id})
            ),
            "list_tasks": lambda: "\n".join(
                f"  {t.id}: {t.subject} [{t.status}]" + (f" (owner: {t.owner})" if t.owner else "")
                for t in list_tasks()
            ) or "No tasks.",
            "get_task": lambda task_id: get_task_json(task_id),
            "claim_task": lambda task_id: claim_task(task_id),
            "complete_task": lambda task_id: complete_task(task_id),
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
            summarized = compact_history(self.messages, self.client, self.recovery.current_model)
            self.messages = summarized
            return "History compacted. Conversation continued from summary."

        self.handlers["compact"] = _compact

    def _add_cron_tools(self):
        tools = [
            {
                "name": "schedule_cron",
                "description": "Schedule a recurring prompt using cron syntax (5 fields: min hour dom month dow).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "cron": {"type": "string"},
                        "prompt": {"type": "string"},
                        "recurring": {"type": "boolean", "default": True},
                    },
                    "required": ["cron", "prompt"],
                },
            },
            {
                "name": "list_crons",
                "description": "List all scheduled cron jobs.",
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
        ]
        from .cron import scheduled_jobs

        handlers = {
            "schedule_cron": lambda cron, prompt, recurring=True: (
                lambda j: f"Scheduled {j.id} ({j.cron})" if hasattr(j, "id") else str(j)
            )(schedule_job(cron, prompt, recurring)),
            "list_crons": lambda: "\n".join(
                f"  {j.id}: {j.cron} {'recurring' if j.recurring else 'once'} - {j.prompt[:50]}"
                for j in scheduled_jobs.values()
            ) or "No scheduled jobs.",
            "cancel_cron": lambda job_id: cancel_job(job_id),
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

    def _build_system_prompt(self) -> str:
        tool_names = [t["name"] for t in self.tools]
        sections = [
            "You are an AI DevOps assistant. Act, don't explain.",
            f"Available tools: {', '.join(tool_names)}",
            f"Working directory: {WORKDIR}",
            f"Current time: {datetime.now().isoformat(timespec='seconds')}",
            "Skills catalog:\n" + list_skills() + "\nUse load_skill(name) when a skill is relevant.",
        ]
        mcp_names = [s["name"] for s in list_connected_mcp()]
        if mcp_names:
            sections.append(f"Connected MCP servers: {', '.join(mcp_names)}")
            sections.append("MCP tools are prefixed mcp__{server}__{tool}.")
        return "\n\n".join(sections)

    def _start_cron(self):
        load_durable_jobs()
        self._cron_thread = threading.Thread(target=cron_scheduler_loop, daemon=True)
        self._cron_thread.start()

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
            return f"Background task started: {bg_id}\nCheck results with collect_background_results."

        # 动态获取 handlers（包含 MCP 工具）
        _, handlers = assemble_tool_pool(self.tools, self.handlers)
        handler = handlers.get(block.name)
        output = call_tool_handler(handler, block.input, block.name)
        trigger_hooks("PostToolUse", block, output)
        return output

    async def run(self, user_message: str) -> str:
        trigger_hooks("UserPromptSubmit", user_message)
        self.messages.append({"role": "user", "content": user_message})

        bg_notifications = collect_background_results()
        if bg_notifications:
            self.messages.append({
                "role": "user",
                "content": "\n\n".join(bg_notifications),
            })

        cron_jobs = consume_cron_queue()
        for job in cron_jobs:
            self.messages.append({
                "role": "user",
                "content": f"<cron_job>\n<id>{job.id}</id>\n<schedule>{job.cron}</schedule>\n<prompt>{job.prompt}</prompt>\n</cron_job>",
            })

        max_turns = 30
        for turn in range(max_turns):
            self.messages = self._compact_if_needed(self.messages)

            try:
                response = self._call_api(self.messages)
            except Exception as e:
                if is_prompt_too_long_error(e):
                    if not self.recovery.has_attempted_reactive_compact:
                        self.recovery.has_attempted_reactive_compact = True
                        self.messages = reactive_compact(
                            self.messages, self.client, self.recovery.current_model
                        )
                        continue
                    if escalate_tokens(self.recovery):
                        continue
                raise

            self.messages.append({"role": "assistant", "content": response.content})

            if not has_tool_use(response.content):
                break

            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                output = self._handle_tool_call(block)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(output),
                })

            self.messages.append({"role": "user", "content": results})

        trigger_hooks("Stop", self.messages)

        final_text = ""
        for msg in reversed(self.messages):
            if msg["role"] == "assistant":
                final_text = extract_text(msg["content"])
                if final_text:
                    break

        return final_text

    def get_messages(self) -> list:
        return list(self.messages)

    def reset(self):
        self.messages = []
        self.recovery = RecoveryState()


def create_devops_agent() -> ComprehensiveAgent:
    """创建一个 DevOps 场景的 Agent 实例。"""
    agent = ComprehensiveAgent(enable_cron=False)
    return agent
