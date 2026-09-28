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
import uuid
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
    is_mcp_tool, is_destructive_mcp_tool, get_mcp_tool_names,
)
from .logger import logger
from .action_router import (
    filter_action_tools,
    get_action,
    route_action,
)
from .tool_policy import (
    ToolPolicyContext,
    evaluate_tool_policy,
    filter_tool_definitions,
)
from .pending_actions import (
    PendingActionStore,
    build_preflight,
)
from .audit import (
    RESULT_BLOCKED,
    RESULT_CANCELED,
    RESULT_FAILED,
    RESULT_SUCCESS,
    SEVERITY_HIGH,
    SEVERITY_INFO,
    record_event,
)
from .rbac import MEMORY_MANAGE, Principal, system_admin_principal
from .memory_policy import (
    can_manage_record,
    can_read_scope,
    can_write_scope,
    readable_scopes,
)
from .sandbox import (
    SandboxManager,
    SandboxTimeout,
    SandboxUnavailable,
)
from .run_checkpoint import (
    PHASE_ACTION_SELECTED,
    PHASE_CANCELED,
    PHASE_COMPLETED,
    PHASE_FAILED,
    PHASE_MODEL_RESPONSE,
    PHASE_TOOLS_RUNNING,
    PHASE_WAITING_APPROVAL,
    STATUS_CANCELED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_INTERRUPTED,
    STATUS_RUNNING,
    STATUS_WAITING_APPROVAL,
    RunCheckpoint,
    RunCheckpointStore,
    repair_pending_tool_results,
    serialize_message,
)


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
        tool_context: ToolPolicyContext | None = None,
        session_id: str = "",
        principal: Principal | None = None,
        run_id: str = "",
        run_source: str = "chat",
        parent_run_id: str = "",
        resource_id: str = "",
        run_metadata: dict | None = None,
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
        self.principal = principal or system_admin_principal()
        requested_memory_scope = (memory_scope or MEMORY_SCOPE).strip() or "global"
        if (
            memory_scope is None
            and not self.principal.has(MEMORY_MANAGE)
        ):
            requested_memory_scope = f"user:{self.principal.id}"
        self.memory_scope = requested_memory_scope
        self.tool_context = (
            tool_context
            or self.principal.to_tool_policy_context()
        )
        self.current_action = get_action("general.chat")
        self.session_id = session_id
        self.audit_enabled = bool(session_id)
        self.current_run_id = ""
        self.initial_run_id = str(run_id or "")
        self.run_source = str(run_source or "chat")
        self.parent_run_id = str(parent_run_id or "")
        self.resource_id = str(resource_id or "")
        self.run_metadata = dict(run_metadata or {})
        self.pending_action_store = PendingActionStore()
        self._pending_action_notifications: list[dict] = []
        self._run_pending_action_ids: list[str] = []
        self.run_checkpoint_store = RunCheckpointStore()
        self._resume_sandbox_workspace = ""
        self.sandbox_manager = SandboxManager()
        self.sandbox_session = None
        self._last_user_query = ""
        self.messages: list = []
        self._pending_compaction = False
        self._register_default_hooks()
        self._register_default_tools()
        self.system_prompt = system_prompt or self._build_system_prompt()

    def _audit(self, event_type: str, title: str, **kwargs):
        if not getattr(self, "audit_enabled", False):
            return None
        kwargs.setdefault("session_id", getattr(self, "session_id", ""))
        kwargs.setdefault("run_id", getattr(self, "current_run_id", ""))
        return record_event(event_type, title, **kwargs)

    def _recovery_snapshot(self) -> dict:
        recovery = getattr(self, "recovery", None)
        if recovery is None:
            return {}
        return {
            "has_escalated": bool(getattr(recovery, "has_escalated", False)),
            "recovery_count": int(getattr(recovery, "recovery_count", 0)),
            "consecutive_529": int(getattr(recovery, "consecutive_529", 0)),
            "current_model": str(getattr(recovery, "current_model", "")),
            "current_max_tokens": int(
                getattr(recovery, "current_max_tokens", 0)
            ),
        }

    def _save_checkpoint(
        self,
        status: str = STATUS_RUNNING,
        phase: str = PHASE_ACTION_SELECTED,
        *,
        last_error: str = "",
    ) -> RunCheckpoint | None:
        store = getattr(self, "run_checkpoint_store", None)
        run_id = getattr(self, "current_run_id", "")
        if store is None or not run_id:
            return None

        existing = store.get(run_id)
        sandbox_workspace = ""
        session = getattr(self, "sandbox_session", None)
        if session is not None:
            sandbox_workspace = session.workspace_host_path
        if not sandbox_workspace:
            sandbox_workspace = getattr(
                self,
                "_resume_sandbox_workspace",
                "",
            )
        checkpoint = RunCheckpoint(
            run_id=run_id,
            session_id=getattr(self, "session_id", ""),
            owner_id=getattr(
                getattr(self, "principal", None),
                "id",
                "",
            ),
            source=getattr(self, "run_source", "chat"),
            parent_run_id=getattr(self, "parent_run_id", ""),
            resource_id=getattr(self, "resource_id", ""),
            status=status,
            phase=phase,
            user_message=getattr(self, "_last_user_query", ""),
            action_code=getattr(
                getattr(self, "current_action", None),
                "code",
                "",
            ),
            messages=[
                serialize_message(message)
                for message in getattr(self, "messages", [])
            ],
            recovery=self._recovery_snapshot(),
            turn=int(getattr(self, "_current_turn", 0)),
            pending_action_ids=list(
                getattr(self, "_run_pending_action_ids", [])
            ),
            sandbox_workspace=sandbox_workspace,
            metadata=dict(getattr(self, "run_metadata", {})),
            last_error=str(last_error or ""),
            created_at=(
                existing.created_at
                if existing is not None
                else time.time()
            ),
            resume_count=(
                existing.resume_count
                if existing is not None
                else 0
            ),
            finished_at=(
                time.time()
                if status in {
                    STATUS_COMPLETED,
                    STATUS_CANCELED,
                    STATUS_FAILED,
                }
                else None
            ),
        )
        return store.save(checkpoint)

    def apply_checkpoint(self, checkpoint: RunCheckpoint) -> list[str]:
        self.current_run_id = checkpoint.run_id
        self.session_id = checkpoint.session_id
        self.run_source = checkpoint.source
        self.parent_run_id = checkpoint.parent_run_id
        self.resource_id = checkpoint.resource_id
        self.run_metadata = dict(checkpoint.metadata)
        self._last_user_query = checkpoint.user_message
        self.messages, repaired_ids = repair_pending_tool_results(
            checkpoint.messages
        )
        self.current_action = (
            get_action(checkpoint.action_code)
            or get_action("general.chat")
        )
        self._run_pending_action_ids = list(
            checkpoint.pending_action_ids
        )
        self._resume_sandbox_workspace = checkpoint.sandbox_workspace
        self._pending_action_notifications = []
        self._pending_compaction = False
        self._current_turn = checkpoint.turn

        recovery = RecoveryState()
        for key, value in checkpoint.recovery.items():
            if hasattr(recovery, key):
                setattr(recovery, key, value)
        self.recovery = recovery
        self._audit(
            "run.resumed",
            "Agent run resumed from checkpoint",
            result=RESULT_SUCCESS,
            severity=SEVERITY_INFO,
            actor="agent",
            correlation_id=checkpoint.run_id,
            payload={
                "checkpoint_phase": checkpoint.phase,
                "resume_count": checkpoint.resume_count + 1,
                "repaired_tool_use_ids": repaired_ids,
            },
        )
        return repaired_ids

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
        self._add_governance_tools()

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
            "claim_task": lambda task_id: claim_task(
                task_id,
                run_id=getattr(self, "current_run_id", ""),
            ),
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
            {
                "name": "approve_memory",
                "description": "Approve a candidate memory and make it active.",
                "input_schema": {
                    "type": "object",
                    "properties": {"memory_id": {"type": "string"}},
                    "required": ["memory_id"],
                },
            },
        ]

        principal = (
            getattr(self, "principal", None)
            or system_admin_principal()
        )
        session_id = getattr(self, "session_id", "")
        run_id = getattr(self, "current_run_id", "")

        def _memory_audit(
            event_type,
            memory,
            *,
            summary="",
            result=RESULT_SUCCESS,
            severity=SEVERITY_INFO,
        ):
            self._audit(
                event_type,
                f"{event_type}: {memory.get('id', '')}",
                summary=summary,
                result=result,
                severity=severity,
                action_code=getattr(
                    getattr(self, "current_action", None),
                    "code",
                    "",
                ),
                correlation_id=memory.get("id", ""),
                payload={
                    "memory_id": memory.get("id", ""),
                    "scope": memory.get("scope", ""),
                    "owner_id": memory.get("owner_id", ""),
                    "session_id": memory.get("session_id", ""),
                    "run_id": memory.get("run_id", ""),
                    "status": memory.get("status", ""),
                },
            )

        def _deny(tool_name, reason):
            self._audit(
                "memory.access_denied",
                f"Memory access denied: {tool_name}",
                summary=reason,
                result=RESULT_BLOCKED,
                severity=SEVERITY_HIGH,
                tool_name=tool_name,
                action_code=getattr(
                    getattr(self, "current_action", None),
                    "code",
                    "",
                ),
                correlation_id=run_id,
                payload={"reason": reason},
            )
            return f"Permission denied: {reason}"

        def _read_scopes(scope=None):
            if scope:
                if not can_read_scope(
                    principal,
                    scope,
                    session_id=session_id,
                ):
                    return None
                return {scope}
            return readable_scopes(
                principal,
                default_scope=self.memory_scope,
                session_id=session_id,
            )

        def _get_manageable(memory_id):
            memory = self.memory.get(memory_id)
            if memory is None:
                return None, f"Memory not found: {memory_id}"
            if not can_manage_record(
                principal,
                memory,
                session_id=session_id,
            ):
                return None, "memory scope is not accessible"
            return memory, None

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
            target_scope = str(scope or self.memory_scope).strip() or "global"
            if not can_write_scope(
                principal,
                target_scope,
                session_id=session_id,
            ):
                return _deny(
                    "add_memory",
                    f"cannot write memory scope '{target_scope}'",
                )
            memory = self.memory.add(
                content,
                importance,
                category,
                memory_type=memory_type,
                entity_type=entity_type,
                entity_key=entity_key,
                entity_value=entity_value,
                tags=tags,
                scope=target_scope,
                owner_id=principal.id,
                session_id=session_id,
                run_id=run_id,
                confidence=confidence,
            )
            if memory.get("status") == "candidate":
                _memory_audit(
                    "memory.candidate_created",
                    memory,
                    summary=content[:300],
                )
                return (
                    f"Memory saved as candidate (id={memory['id']}): "
                    f"{content[:80]}"
                )
            _memory_audit(
                "memory.created",
                memory,
                summary=content[:300],
            )
            return f"Memory saved (id={memory['id']}): {content[:80]}"

        def _search_memory(query, scope=None, memory_type=None):
            scopes = _read_scopes(scope)
            if scopes is None:
                return _deny(
                    "search_memory",
                    f"cannot read memory scope '{scope}'",
                )
            return self.memory.format_relevant(
                query,
                scopes=scopes,
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
            current, error = _get_manageable(memory_id)
            if error:
                return _deny("update_memory", error)
            if scope is not None and not can_write_scope(
                principal,
                scope,
                owner_id=current.get("owner_id", ""),
                session_id=session_id,
            ):
                return _deny(
                    "update_memory",
                    f"cannot move memory to scope '{scope}'",
                )
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
            _memory_audit(
                "memory.updated",
                memory,
                summary=content[:300] if content else "",
            )
            return f"Memory updated: {memory['id']} (version={memory['version']})"

        def _archive_memory(memory_id):
            _, error = _get_manageable(memory_id)
            if error:
                return _deny("archive_memory", error)
            memory = self.memory.archive(memory_id)
            _memory_audit("memory.archived", memory)
            return f"Memory archived: {memory['id']}"

        def _delete_memory(memory_id):
            _, error = _get_manageable(memory_id)
            if error:
                return _deny("delete_memory", error)
            memory = self.memory.delete(memory_id)
            _memory_audit("memory.deleted", memory)
            return f"Memory soft-deleted: {memory['id']}"

        def _restore_memory(memory_id):
            _, error = _get_manageable(memory_id)
            if error:
                return _deny("restore_memory", error)
            memory = self.memory.restore(memory_id)
            _memory_audit("memory.restored", memory)
            return f"Memory restored: {memory['id']}"

        def _approve_memory(memory_id):
            current, error = _get_manageable(memory_id)
            if error:
                return _deny("approve_memory", error)
            if current.get("status") != "candidate":
                return f"Error: memory {memory_id} is not a candidate"
            memory = self.memory.approve(memory_id)
            _memory_audit("memory.approved", memory)
            return f"Memory approved: {memory['id']}"

        handlers = {
            "add_memory": _add_memory,
            "search_memory": _search_memory,
            "update_memory": _update_memory,
            "archive_memory": _archive_memory,
            "delete_memory": _delete_memory,
            "restore_memory": _restore_memory,
            "approve_memory": _approve_memory,
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
            self.client,
            self.recovery.current_model,
            description,
            sandbox_manager=getattr(self, "sandbox_manager", None),
            run_id=getattr(self, "current_run_id", ""),
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
        self.handlers["connect_mcp"] = lambda name: connect_mcp(
            name,
            owner_id=getattr(
                getattr(self, "principal", None),
                "id",
                "",
            ),
            session_id=getattr(self, "session_id", ""),
            run_id=getattr(self, "current_run_id", ""),
            source="agent",
        )

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

    def _add_governance_tools(self):
        schema = {
            "name": "propose_action",
            "description": (
                "Create a persistent pending-action proposal for a "
                "state-changing operation. This does not execute the "
                "operation. Use it after read-only investigation and before "
                "any approval-required tool."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "payload": {
                        "type": "object",
                        "additionalProperties": True,
                    },
                    "steps": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "tool": {"type": "string"},
                                "description": {"type": "string"},
                            },
                            "required": ["tool", "description"],
                        },
                    },
                    "impact": {"type": "string"},
                    "rollback_plan": {"type": "string"},
                    "verification": {"type": "string"},
                },
                "required": ["summary", "payload", "steps"],
            },
        }
        self.tools.append(schema)
        self.handlers["propose_action"] = self._propose_action

    def _propose_action(
        self,
        summary,
        payload=None,
        steps=None,
        impact="",
        rollback_plan="",
        verification="",
    ):
        action = getattr(self, "current_action", None)
        if action is None or not action.preflight_required:
            return "Error: propose_action is only available for preflight actions"
        if not str(summary or "").strip():
            return "Error: summary is required"
        if not isinstance(payload, dict):
            return "Error: payload must be an object"
        if not isinstance(steps, list) or not steps:
            return "Error: steps must be a non-empty array"

        normalized_steps = []
        for step in steps:
            if not isinstance(step, dict):
                return "Error: every step must be an object"
            tool_name = str(step.get("tool") or "").strip()
            description = str(step.get("description") or "").strip()
            if not tool_name or not description:
                return "Error: every step needs tool and description"
            if (
                tool_name not in {"preflight", "answer"}
                and tool_name not in action.allowed_tools
            ):
                return (
                    f"Error: step tool '{tool_name}' is not allowed for "
                    f"action '{action.code}'"
                )
            normalized_steps.append({
                **step,
                "tool": tool_name,
                "description": description,
            })

        merged_payload = {
            **payload,
            "impact": impact or payload.get("impact", ""),
            "rollback_plan": (
                rollback_plan or payload.get("rollback_plan", "")
            ),
            "verification": (
                verification or payload.get("verification", "")
            ),
        }
        preflight = build_preflight(action, merged_payload)
        if not preflight.ready:
            self._audit(
                "preflight.failed",
                f"Preflight failed: {action.code}",
                summary=(
                    "Missing fields: "
                    + ", ".join(preflight.missing_fields)
                ),
                result=RESULT_FAILED,
                severity=SEVERITY_HIGH,
                action_code=action.code,
                risk_level=action.risk_level,
                correlation_id=getattr(self, "current_run_id", ""),
                payload={"missing_fields": preflight.missing_fields},
            )
            return (
                "Preflight incomplete. Missing fields: "
                f"{', '.join(preflight.missing_fields)}"
            )

        self._audit(
            "preflight.completed",
            f"Preflight completed: {action.code}",
            result=RESULT_SUCCESS,
            severity=SEVERITY_INFO,
            action_code=action.code,
            risk_level=action.risk_level,
            correlation_id=getattr(self, "current_run_id", ""),
            payload=merged_payload,
        )
        record = self.pending_action_store.create(
            action,
            session_id=getattr(self, "session_id", ""),
            owner_id=getattr(
                getattr(self, "principal", None),
                "id",
                "",
            ),
            source_message=getattr(self, "_last_user_query", ""),
            summary=summary,
            payload=merged_payload,
            steps=normalized_steps,
            impact=impact or merged_payload.get("impact", ""),
            rollback_plan=(
                rollback_plan or merged_payload.get("rollback_plan", "")
            ),
            verification=(
                verification or merged_payload.get("verification", "")
            ),
        )
        self._audit(
            "pending_action.created",
            f"Pending action created: {action.code}",
            result=RESULT_SUCCESS,
            severity=SEVERITY_INFO,
            action_id=record.id,
            action_code=action.code,
            risk_level=action.risk_level,
            correlation_id=record.id,
            payload={
                "summary": record.summary,
                "steps": record.steps,
                "impact": record.impact,
            },
        )
        pending_ids = getattr(self, "_run_pending_action_ids", None)
        if pending_ids is None:
            self._run_pending_action_ids = []
            pending_ids = self._run_pending_action_ids
        if record.id not in pending_ids:
            pending_ids.append(record.id)
        notifications = getattr(
            self,
            "_pending_action_notifications",
            None,
        )
        if notifications is None:
            self._pending_action_notifications = []
            notifications = self._pending_action_notifications
        notifications.append(record.to_dict())
        return (
            f"Pending action created: {record.id}\n"
            f"Status: {record.status}\n"
            "Await user approval before execution."
        )

    def _build_system_prompt(self) -> str:
        tool_context = getattr(self, "tool_context", None)
        action = getattr(self, "current_action", None)
        visible_builtin = filter_tool_definitions(
            self.tools,
            tool_context,
        )
        visible_mcp = filter_tool_definitions(
            [
                {"name": name}
                for name in get_mcp_tool_names(self._mcp_context())
            ],
            tool_context,
        )
        if action is not None:
            visible_builtin = filter_action_tools(
                visible_builtin,
                action,
                tool_context,
                preflight_mode=action.preflight_required,
            )
            visible_mcp = filter_action_tools(
                visible_mcp,
                action,
                tool_context,
                preflight_mode=action.preflight_required,
            )
        tool_names = (
            [t["name"] for t in visible_builtin]
            + [t["name"] for t in visible_mcp]
        )
        sections = [
            "You are an AI DevOps assistant. Act, don't explain.",
            f"Available tools: {', '.join(tool_names)}",
            f"Working directory: {WORKDIR}",
            f"Current time: {datetime.now().isoformat(timespec='seconds')}",
            "Skills catalog:\n" + list_skills() + "\nUse load_skill(name) when a skill is relevant.",
        ]
        if action is not None:
            mode_guidance = {
                "direct": "Use Direct mode: answer or produce the requested artifact without unnecessary tool turns.",
                "react": "Use ReAct mode: gather evidence with tools, then answer. Do not mutate state.",
                "plan_react": "Use Plan+ReAct mode: prepare a concrete plan and preflight before any state-changing action.",
            }.get(
                action.agent_mode,
                "Use ReAct mode: gather evidence before answering.",
            )
            sections.append(
                f"Selected action: {action.code} ({action.display_name})\n"
                f"Risk: {action.risk_level}; approval required: "
                f"{action.requires_approval}; preflight required: "
                f"{action.preflight_required}.\n{mode_guidance}"
            )
            if action.preflight_required:
                sections.append(
                    "State-changing tools are hidden until approval. "
                    "Use propose_action with a concrete summary, payload, "
                    "steps, impact, rollback_plan, and verification."
                )
        if self._last_user_query:
            principal = (
                getattr(self, "principal", None)
                or system_admin_principal()
            )
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

    def _call_api(self, messages: list):
        # 动态合并 MCP 工具：每次调用 API 前把已连接的 MCP 服务器工具合并进来
        tools, _ = assemble_tool_pool(
            self.tools,
            self.handlers,
            self._mcp_context(),
        )
        tools = filter_tool_definitions(tools, self.tool_context)
        action = getattr(self, "current_action", None)
        if action is not None:
            tools = filter_action_tools(
                tools,
                action,
                self.tool_context,
                preflight_mode=action.preflight_required,
            )
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

    def _ensure_sandbox(self):
        manager = getattr(self, "sandbox_manager", None)
        if manager is None:
            raise SandboxUnavailable("Sandbox manager is not configured")
        run_id = getattr(self, "current_run_id", "")
        session = manager.get(run_id)
        if session is not None:
            self.sandbox_session = session
            return session

        self._audit(
            "sandbox.creating",
            "Creating Docker sandbox",
            result=RESULT_SUCCESS,
            severity=SEVERITY_INFO,
            actor="agent",
            correlation_id=run_id,
            payload={"image": manager.spec.image},
        )
        try:
            resume_workspace = getattr(
                self,
                "_resume_sandbox_workspace",
                "",
            )
            reuse_existing = bool(
                resume_workspace
                and Path(resume_workspace).exists()
            )
            session = manager.create(
                run_id,
                source_workspace=(
                    None if reuse_existing else WORKDIR
                ),
                reuse_existing_workspace=reuse_existing,
                owner_id=getattr(
                    getattr(self, "principal", None),
                    "id",
                    "",
                ),
                source=getattr(self, "run_source", "chat"),
            )
            self._resume_sandbox_workspace = ""
        except SandboxUnavailable as exc:
            self._audit(
                "sandbox.failed",
                "Docker sandbox unavailable",
                summary=str(exc),
                result=RESULT_FAILED,
                severity=SEVERITY_HIGH,
                actor="agent",
                correlation_id=run_id,
            )
            raise
        self.sandbox_session = session
        self._audit(
            "sandbox.created",
            "Docker sandbox created",
            result=RESULT_SUCCESS,
            severity=SEVERITY_INFO,
            actor="agent",
            correlation_id=run_id,
            payload=session.to_dict(),
        )
        return session

    def _cleanup_sandbox(self):
        manager = getattr(self, "sandbox_manager", None)
        if manager is None:
            return
        run_id = getattr(self, "current_run_id", "")
        session = manager.get(run_id)
        if session is None:
            return
        manager.cleanup(run_id, remove_workspace=True)
        self.sandbox_session = None
        self._audit(
            "sandbox.removed",
            "Docker sandbox removed",
            result=RESULT_SUCCESS,
            severity=SEVERITY_INFO,
            actor="agent",
            correlation_id=run_id,
            payload={
                "sandbox_id": session.id,
                "container_id": session.container_id,
            },
        )

    def _execute_sandbox_tool(self, block, decision) -> str:
        run_id = getattr(self, "current_run_id", "")
        try:
            self._ensure_sandbox()
        except SandboxUnavailable as exc:
            return f"Error: Docker sandbox unavailable: {exc}"

        tool_input = (
            block.input
            if isinstance(block.input, dict)
            else {}
        )
        try:
            if block.name == "bash":
                if tool_input.get("run_in_background"):
                    return (
                        "Error: background sandbox execution is not "
                        "enabled yet"
                    )
                return self.sandbox_manager.run(
                    run_id,
                    tool_input.get("command", ""),
                    cwd=tool_input.get("cwd"),
                    timeout_seconds=decision.policy.timeout_seconds,
                )
            if block.name == "read_file":
                return self.sandbox_manager.read_file(
                    run_id,
                    tool_input.get("path", ""),
                    limit=tool_input.get("limit"),
                    offset=tool_input.get("offset", 0),
                )
            if block.name == "write_file":
                return self.sandbox_manager.write_file(
                    run_id,
                    tool_input.get("path", ""),
                    tool_input.get("content", ""),
                )
            if block.name == "edit_file":
                return self.sandbox_manager.edit_file(
                    run_id,
                    tool_input.get("path", ""),
                    tool_input.get("old_text", ""),
                    tool_input.get("new_text", ""),
                )
            if block.name == "glob":
                return self.sandbox_manager.glob(
                    run_id,
                    tool_input.get("pattern", ""),
                )
            if block.name == "spawn_subagent":
                return spawn_subagent(
                    self.client,
                    self.recovery.current_model,
                    tool_input.get("description", ""),
                    sandbox_manager=self.sandbox_manager,
                    run_id=run_id,
                )
            return (
                f"Error: tool '{block.name}' is host-inspection only and "
                "is not available inside the Docker sandbox"
            )
        except SandboxTimeout as exc:
            self._audit(
                "sandbox.timeout",
                f"Sandbox tool timed out: {block.name}",
                summary=str(exc),
                result=RESULT_FAILED,
                severity=SEVERITY_HIGH,
                actor="agent",
                tool_name=block.name,
                correlation_id=run_id,
                payload={"input": tool_input},
            )
            return f"Error: {exc}"
        except SandboxUnavailable as exc:
            return f"Error: Docker sandbox unavailable: {exc}"
        except Exception as exc:
            return f"Error: sandbox tool failed: {exc}"

    def _handle_tool_call(self, block):
        decision = evaluate_tool_policy(
            block.name,
            getattr(self, "tool_context", None),
        )
        if not decision.allowed:
            self._audit(
                "policy.blocked",
                f"Tool policy blocked: {block.name}",
                summary=decision.reason,
                result=RESULT_BLOCKED,
                severity=SEVERITY_HIGH,
                tool_name=block.name,
                risk_level=decision.policy.risk_level,
                correlation_id=getattr(self, "current_run_id", ""),
                payload={"input": block.input},
                metadata={"reason": decision.reason},
            )
            return f"Policy denied: {decision.reason}"

        action = getattr(self, "current_action", None)
        if action is not None and block.name not in action.allowed_tools:
            self._audit(
                "policy.blocked",
                f"Action scope blocked: {block.name}",
                summary=f"Not allowed for action {action.code}",
                result=RESULT_BLOCKED,
                severity=SEVERITY_HIGH,
                action_code=action.code,
                tool_name=block.name,
                risk_level=decision.policy.risk_level,
                correlation_id=getattr(self, "current_run_id", ""),
                payload={"input": block.input},
            )
            return (
                f"Action denied: tool '{block.name}' is not allowed for "
                f"action '{action.code}'"
            )

        if (
            action is not None
            and action.preflight_required
            and decision.requires_approval
            and block.name != "propose_action"
        ):
            self._audit(
                "policy.preflight_required",
                f"Preflight required: {block.name}",
                summary=(
                    "State-changing tool blocked until a pending action "
                    "is approved"
                ),
                result=RESULT_BLOCKED,
                severity=SEVERITY_HIGH,
                action_code=action.code,
                tool_name=block.name,
                risk_level=decision.policy.risk_level,
                correlation_id=getattr(self, "current_run_id", ""),
                payload={"input": block.input},
            )
            return (
                "Preflight required: create a pending action with "
                "propose_action and wait for approval before executing "
                f"'{block.name}'"
            )

        self._audit(
            "policy.allowed",
            f"Tool policy allowed: {block.name}",
            result=RESULT_SUCCESS,
            severity=SEVERITY_INFO,
            action_code=action.code if action else "",
            tool_name=block.name,
            risk_level=decision.policy.risk_level,
            correlation_id=getattr(self, "current_run_id", ""),
            payload={"input": block.input},
            metadata={"requires_approval": decision.requires_approval},
        )

        blocked = trigger_hooks("PreToolUse", block)
        if blocked:
            self._audit(
                "policy.blocked",
                f"PreToolUse hook blocked: {block.name}",
                summary=str(blocked),
                result=RESULT_BLOCKED,
                severity=SEVERITY_HIGH,
                tool_name=block.name,
                correlation_id=getattr(self, "current_run_id", ""),
                payload={"input": block.input},
            )
            return str(blocked)

        if block.name == "bash" and should_run_background(block.name, block.input):
            bg_id = start_background_task(
                block,
                self.handlers,
                lambda blk, out: trigger_hooks("PostToolUse", blk, out),
                principal=getattr(self, "principal", None),
                session_id=getattr(self, "session_id", ""),
                parent_run_id=getattr(self, "current_run_id", ""),
            )
            return f"Background task started: {bg_id}\nCheck results with list_background_tasks."

        if (
            decision.policy.sandbox_required
            and getattr(self, "sandbox_manager", None) is not None
        ):
            return self._execute_sandbox_tool(block, decision)

        # 动态获取 handlers（包含 MCP 工具）
        _, handlers = assemble_tool_pool(
            self.tools,
            self.handlers,
            self._mcp_context(),
        )
        handler = handlers.get(block.name)
        output = call_tool_handler(handler, block.input, block.name)
        trigger_hooks("PostToolUse", block, output)
        return output

    @staticmethod
    def _is_cancelled(cancel_event) -> bool:
        return cancel_event is not None and cancel_event.is_set()

    def _cancelled_event(self) -> dict:
        text = "已停止生成。"
        self._audit(
            "run.canceled",
            "Agent run canceled",
            summary=text,
            result=RESULT_CANCELED,
            severity=SEVERITY_INFO,
            actor="user",
            correlation_id=getattr(self, "current_run_id", ""),
            payload={},
        )
        self.messages.append({
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
        })
        self._save_checkpoint(
            STATUS_CANCELED,
            PHASE_CANCELED,
        )
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
        """Run the Agent and always clean up the per-run Docker sandbox."""
        try:
            for event in self._run_stream_impl(
                user_message,
                cancel_event,
                resume=False,
            ):
                yield event
        except Exception as exc:
            self._save_checkpoint(
                STATUS_FAILED,
                PHASE_FAILED,
                last_error=str(exc),
            )
            raise
        finally:
            self._cleanup_sandbox()

    def resume_stream(self, checkpoint: RunCheckpoint, cancel_event=None):
        """Resume an interrupted checkpoint under the same run_id."""
        self.apply_checkpoint(checkpoint)
        try:
            for event in self._run_stream_impl(
                "",
                cancel_event,
                resume=True,
            ):
                yield event
        except Exception as exc:
            self._save_checkpoint(
                STATUS_FAILED,
                PHASE_FAILED,
                last_error=str(exc),
            )
            raise
        finally:
            self._cleanup_sandbox()

    def _run_stream_impl(
        self,
        user_message: str,
        cancel_event=None,
        *,
        resume: bool = False,
    ):
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
        if not resume:
            self.current_run_id = (
                getattr(self, "initial_run_id", "")
                or f"run_{uuid.uuid4().hex}"
            )
            self._run_pending_action_ids = []
            self._audit(
                "run.started",
                "Agent run started",
                summary=user_message[:300],
                result=RESULT_SUCCESS,
                severity=SEVERITY_INFO,
                actor="agent",
                correlation_id=self.current_run_id,
                payload={"message": user_message},
            )
            trigger_hooks("UserPromptSubmit", user_message)
            self._last_user_query = user_message
            self.current_action = route_action(user_message)
        else:
            self._audit(
                "run.resume.started",
                "Agent run resume started",
                result=RESULT_SUCCESS,
                severity=SEVERITY_INFO,
                actor="agent",
                correlation_id=self.current_run_id,
                payload={"phase": PHASE_ACTION_SELECTED},
            )
        principal = getattr(self, "principal", None) or system_admin_principal()
        missing_action_permissions = principal.missing(
            self.current_action.rbac_permissions
        )
        if missing_action_permissions:
            self._audit(
                "rbac.denied",
                f"Action permission denied: {self.current_action.code}",
                summary=(
                    "Missing permissions: "
                    + ", ".join(missing_action_permissions)
                ),
                result=RESULT_BLOCKED,
                severity=SEVERITY_HIGH,
                actor=principal.id,
                action_code=self.current_action.code,
                risk_level=self.current_action.risk_level,
                correlation_id=self.current_run_id,
                payload={
                    "missing_permissions": missing_action_permissions,
                    "roles": sorted(principal.roles),
                },
            )
            yield {
                "type": "permission_denied",
                "message": (
                    f"Permission denied for action "
                    f"'{self.current_action.code}'"
                ),
                "missing_permissions": missing_action_permissions,
                "action": self.current_action.to_dict(),
                "turn": 0,
            }
            yield {
                "type": "error",
                "message": (
                    "Permission denied. Missing permissions: "
                    + ", ".join(missing_action_permissions)
                ),
            }
            self._save_checkpoint(
                STATUS_FAILED,
                PHASE_FAILED,
                last_error="permission denied",
            )
            return
        self._audit(
            "action.selected",
            f"Action selected: {self.current_action.code}",
            summary=self.current_action.display_name,
            result=RESULT_SUCCESS,
            severity=SEVERITY_INFO,
            actor="agent",
            action_code=self.current_action.code,
            risk_level=self.current_action.risk_level,
            correlation_id=self.current_run_id,
            payload=self.current_action.to_dict(),
        )
        yield {
            "type": "action",
            "action": self.current_action.to_dict(),
            "turn": 0,
        }
        if not resume:
            self.messages.append({"role": "user", "content": user_message})
            logger.info(f"[user] {user_message[:200]}")
        self._save_checkpoint(
            STATUS_RUNNING,
            PHASE_ACTION_SELECTED,
        )

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
            self._current_turn = turn + 1
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
                        self._audit(
                            "run.failed",
                            "Context recovery exhausted",
                            summary="Context remained over the model limit",
                            result=RESULT_FAILED,
                            severity=SEVERITY_HIGH,
                            actor="agent",
                            correlation_id=self.current_run_id,
                        )
                        yield {
                            "type": "error",
                            "message": "上下文压缩后仍然超过模型限制",
                        }
                        self._save_checkpoint(
                            STATUS_FAILED,
                            PHASE_FAILED,
                            last_error="context recovery exhausted",
                        )
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
                        self._audit(
                            "run.failed",
                            "Context compaction failed",
                            summary=str(compact_error),
                            result=RESULT_FAILED,
                            severity=SEVERITY_HIGH,
                            actor="agent",
                            correlation_id=self.current_run_id,
                        )
                        yield {
                            "type": "error",
                            "message": f"上下文压缩失败: {compact_error}",
                        }
                        self._save_checkpoint(
                            STATUS_FAILED,
                            PHASE_FAILED,
                            last_error=str(compact_error),
                        )
                        return

                    self.messages = compacted
                    logger.info(
                        f"[turn {turn+1}] context recovery: "
                        f"{stats['before']} -> {stats['after']} bytes"
                    )
                    if not stats["reduced"]:
                        self._audit(
                            "run.failed",
                            "Context compaction did not reduce input",
                            summary="No effective context reduction",
                            result=RESULT_FAILED,
                            severity=SEVERITY_HIGH,
                            actor="agent",
                            correlation_id=self.current_run_id,
                        )
                        yield {
                            "type": "error",
                            "message": "上下文压缩未有效缩小输入，无法继续调用模型",
                        }
                        self._save_checkpoint(
                            STATUS_FAILED,
                            PHASE_FAILED,
                            last_error="context compaction ineffective",
                        )
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

                self._audit(
                    "run.failed",
                    "Agent API call failed",
                    summary=str(e),
                    result=RESULT_FAILED,
                    severity=SEVERITY_HIGH,
                    actor="agent",
                    correlation_id=self.current_run_id,
                )
                yield {"type": "error", "message": str(e)}
                self._save_checkpoint(
                    STATUS_FAILED,
                    PHASE_FAILED,
                    last_error=str(e),
                )
                logger.error(f"[turn {turn+1}] API 异常: {e}")
                return

            if self._is_cancelled(cancel_event):
                yield self._cancelled_event()
                return

            self.messages.append({"role": "assistant", "content": response.content})
            self._save_checkpoint(
                STATUS_RUNNING,
                PHASE_MODEL_RESPONSE,
            )

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
            self._save_checkpoint(
                STATUS_RUNNING,
                PHASE_TOOLS_RUNNING,
            )
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
                tool_input = (
                    block.input
                    if isinstance(block.input, dict)
                    else {"input": str(block.input)}
                )
                self._audit(
                    "tool.started",
                    f"Tool started: {block.name}",
                    result=RESULT_SUCCESS,
                    severity=SEVERITY_INFO,
                    actor="agent",
                    action_code=getattr(
                        getattr(self, "current_action", None),
                        "code",
                        "",
                    ),
                    tool_name=block.name,
                    correlation_id=self.current_run_id,
                    payload={"input": tool_input},
                )
                yield {
                    "type": "tool_use",
                    "tool": block.name,
                    "input": tool_input,
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
                blocked_prefixes = (
                    "Policy denied:",
                    "Action denied:",
                    "Preflight required:",
                )
                if output_str.startswith(blocked_prefixes):
                    tool_result = RESULT_BLOCKED
                    tool_severity = SEVERITY_HIGH
                elif output_str.startswith("Error:"):
                    tool_result = RESULT_FAILED
                    tool_severity = SEVERITY_HIGH
                else:
                    tool_result = RESULT_SUCCESS
                    tool_severity = SEVERITY_INFO
                self._audit(
                    "tool.completed",
                    f"Tool completed: {block.name}",
                    summary=output_str[:500],
                    result=tool_result,
                    severity=tool_severity,
                    actor="agent",
                    action_code=getattr(
                        getattr(self, "current_action", None),
                        "code",
                        "",
                    ),
                    tool_name=block.name,
                    correlation_id=self.current_run_id,
                    payload={"input": tool_input},
                    metadata={
                        "duration_ms": duration_ms,
                        "output_preview": output_str[:1000],
                    },
                )
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

                pending_notifications = getattr(
                    self,
                    "_pending_action_notifications",
                    None,
                )
                if pending_notifications:
                    while pending_notifications:
                        pending_action = pending_notifications.pop(0)
                        yield {
                            "type": "pending_action",
                            "pending_action": pending_action,
                            "turn": turn+1,
                        }

                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(output),
                })

            self.messages.append({"role": "user", "content": results})
            self._save_checkpoint(
                STATUS_RUNNING,
                PHASE_MODEL_RESPONSE,
            )

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

        self._audit(
            "run.completed",
            "Agent run completed",
            summary=(final_text or "")[:300],
            result=RESULT_SUCCESS,
            severity=SEVERITY_INFO,
            actor="agent",
            correlation_id=self.current_run_id,
            payload={"total_turns": turn + 1},
        )
        final_status = (
            STATUS_WAITING_APPROVAL
            if getattr(self, "_run_pending_action_ids", [])
            else STATUS_COMPLETED
        )
        final_phase = (
            PHASE_WAITING_APPROVAL
            if final_status == STATUS_WAITING_APPROVAL
            else PHASE_COMPLETED
        )
        self._save_checkpoint(final_status, final_phase)
        yield {"type": "done", "text": final_text, "total_turns": turn + 1}
        logger.info(f"[done] 共 {turn + 1} 轮, 输出 {len(final_text)} 字符")

    def get_messages(self) -> list:
        return list(self.messages)

    def reset(self):
        self.messages = []
        self._pending_compaction = False
        self.recovery = RecoveryState()
        self.current_action = get_action("general.chat")
        self._pending_action_notifications = []
        self._run_pending_action_ids = []
        self._resume_sandbox_workspace = ""
        self.current_run_id = ""
        self.initial_run_id = ""
        self._current_turn = 0


def create_devops_agent() -> ComprehensiveAgent:
    """创建一个 DevOps 场景的 Agent 实例。"""
    return ComprehensiveAgent()
