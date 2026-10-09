"""Central policy metadata and access decisions for agent tools.

The model proposes tool calls, but the platform owns the decision about whether
a tool is visible or executable in a given context. This module is deliberately
free of FastAPI and Agent-loop dependencies so it can be reused by tasks, cron,
background work, and future audit code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


READ_ONLY = "read_only"
LOW = "low"
MEDIUM = "medium"
HIGH = "high"
CRITICAL = "critical"
VALID_RISK_LEVELS = {READ_ONLY, LOW, MEDIUM, HIGH, CRITICAL}

FILESYSTEM_READ = "filesystem.read"
FILESYSTEM_WRITE = "filesystem.write"
SHELL_EXECUTE = "shell.execute"
OPS_READ = "ops.read"
TASK_READ = "task.read"
TASK_WRITE = "task.write"
MEMORY_READ = "memory.read"
MEMORY_WRITE = "memory.write"
MEMORY_MANAGE = "memory.manage"
SKILL_READ = "skill.read"
CONTEXT_WRITE = "context.write"
AGENT_EXECUTE = "agent.execute"
CRON_READ = "cron.read"
CRON_WRITE = "cron.write"
BACKGROUND_READ = "background.read"
MCP_CONNECT = "mcp.connect"
MCP_EXECUTE = "mcp.execute"
ACTION_PROPOSE = "agent.propose"
UNKNOWN_TOOL = "tool.unknown"

_MCP_READ_ONLY_NAME = re.compile(
    r"^(query|get|list|search|describe|read|show|check|inspect)([_\-.]|$)",
    re.IGNORECASE,
)
_MCP_WRITE_MARKER = re.compile(
    r"(^|[_\-.])(create|update|delete|remove|write|patch|mutate|execute|"
    r"run|apply|drop|truncate|grant|revoke)([_\-.]|$)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ToolPolicy:
    name: str
    read_only: bool
    risk_level: str
    requires_approval: bool
    required_scopes: tuple[str, ...] = ()
    timeout_seconds: int = 30
    idempotent: bool = True
    sandbox_required: bool = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "read_only": self.read_only,
            "risk_level": self.risk_level,
            "requires_approval": self.requires_approval,
            "required_scopes": list(self.required_scopes),
            "timeout_seconds": self.timeout_seconds,
            "idempotent": self.idempotent,
            "sandbox_required": self.sandbox_required,
        }


@dataclass(frozen=True)
class ToolPolicyContext:
    """Capabilities supplied by the caller for one Agent run."""

    permissions: frozenset[str] = field(
        default_factory=lambda: frozenset({"*"})
    )
    allowed_tools: frozenset[str] | None = None
    write_enabled: bool = True
    execute_enabled: bool = True


@dataclass(frozen=True)
class ToolPolicyDecision:
    tool_name: str
    allowed: bool
    requires_approval: bool
    reason: str
    policy: ToolPolicy


def _make_policy(
    name: str,
    *,
    read_only: bool,
    risk_level: str,
    requires_approval: bool,
    required_scopes: tuple[str, ...] = (),
    timeout_seconds: int = 30,
    idempotent: bool = True,
    sandbox_required: bool = False,
) -> ToolPolicy:
    if risk_level not in VALID_RISK_LEVELS:
        raise ValueError(f"Invalid risk level for {name}: {risk_level}")
    if read_only and risk_level != READ_ONLY:
        raise ValueError(f"Read-only tool {name} must use risk level {READ_ONLY}")
    return ToolPolicy(
        name=name,
        read_only=read_only,
        risk_level=risk_level,
        requires_approval=requires_approval,
        required_scopes=required_scopes,
        timeout_seconds=timeout_seconds,
        idempotent=idempotent,
        sandbox_required=sandbox_required,
    )


def _build_builtin_policies() -> dict[str, ToolPolicy]:
    policies = [
        _make_policy(
            "read_file",
            read_only=True,
            risk_level=READ_ONLY,
            requires_approval=False,
            required_scopes=(FILESYSTEM_READ,),
            sandbox_required=True,
        ),
        _make_policy(
            "write_file",
            read_only=False,
            risk_level=MEDIUM,
            requires_approval=False,
            required_scopes=(FILESYSTEM_WRITE,),
            idempotent=False,
            sandbox_required=True,
        ),
        _make_policy(
            "edit_file",
            read_only=False,
            risk_level=MEDIUM,
            requires_approval=False,
            required_scopes=(FILESYSTEM_WRITE,),
            idempotent=False,
            sandbox_required=True,
        ),
        _make_policy(
            "glob",
            read_only=True,
            risk_level=READ_ONLY,
            requires_approval=False,
            required_scopes=(FILESYSTEM_READ,),
            sandbox_required=True,
        ),
        _make_policy(
            "bash",
            read_only=False,
            risk_level=HIGH,
            requires_approval=True,
            required_scopes=(SHELL_EXECUTE,),
            timeout_seconds=120,
            idempotent=False,
            sandbox_required=True,
        ),
        _make_policy(
            "service_status",
            read_only=True,
            risk_level=READ_ONLY,
            requires_approval=False,
            required_scopes=(OPS_READ,),
        ),
        _make_policy(
            "disk_usage",
            read_only=True,
            risk_level=READ_ONLY,
            requires_approval=False,
            required_scopes=(OPS_READ,),
        ),
        _make_policy(
            "system_info",
            read_only=True,
            risk_level=READ_ONLY,
            requires_approval=False,
            required_scopes=(OPS_READ,),
        ),
        _make_policy(
            "memory_usage",
            read_only=True,
            risk_level=READ_ONLY,
            requires_approval=False,
            required_scopes=(OPS_READ,),
        ),
        _make_policy(
            "cpu_usage",
            read_only=True,
            risk_level=READ_ONLY,
            requires_approval=False,
            required_scopes=(OPS_READ,),
        ),
        _make_policy(
            "process_top",
            read_only=True,
            risk_level=READ_ONLY,
            requires_approval=False,
            required_scopes=(OPS_READ,),
        ),
        _make_policy(
            "process_search",
            read_only=True,
            risk_level=READ_ONLY,
            requires_approval=False,
            required_scopes=(OPS_READ,),
        ),
        _make_policy(
            "network_interfaces",
            read_only=True,
            risk_level=READ_ONLY,
            requires_approval=False,
            required_scopes=(OPS_READ,),
        ),
        _make_policy(
            "port_listen",
            read_only=True,
            risk_level=READ_ONLY,
            requires_approval=False,
            required_scopes=(OPS_READ,),
        ),
        _make_policy(
            "ping_host",
            read_only=True,
            risk_level=READ_ONLY,
            requires_approval=False,
            required_scopes=(OPS_READ,),
        ),
        _make_policy(
            "disk_io",
            read_only=True,
            risk_level=READ_ONLY,
            requires_approval=False,
            required_scopes=(OPS_READ,),
        ),
        _make_policy(
            "system_logs",
            read_only=True,
            risk_level=READ_ONLY,
            requires_approval=False,
            required_scopes=(OPS_READ,),
        ),
        _make_policy(
            "todo_write",
            read_only=False,
            risk_level=LOW,
            requires_approval=False,
            required_scopes=(CONTEXT_WRITE,),
            idempotent=False,
        ),
        _make_policy(
            "create_task",
            read_only=False,
            risk_level=LOW,
            requires_approval=False,
            required_scopes=(TASK_WRITE,),
            idempotent=False,
        ),
        _make_policy(
            "list_tasks",
            read_only=True,
            risk_level=READ_ONLY,
            requires_approval=False,
            required_scopes=(TASK_READ,),
        ),
        _make_policy(
            "get_task",
            read_only=True,
            risk_level=READ_ONLY,
            requires_approval=False,
            required_scopes=(TASK_READ,),
        ),
        _make_policy(
            "claim_task",
            read_only=False,
            risk_level=LOW,
            requires_approval=False,
            required_scopes=(TASK_WRITE,),
            idempotent=False,
        ),
        _make_policy(
            "complete_task",
            read_only=False,
            risk_level=LOW,
            requires_approval=False,
            required_scopes=(TASK_WRITE,),
            idempotent=False,
        ),
        _make_policy(
            "list_skills",
            read_only=True,
            risk_level=READ_ONLY,
            requires_approval=False,
            required_scopes=(SKILL_READ,),
        ),
        _make_policy(
            "load_skill",
            read_only=True,
            risk_level=READ_ONLY,
            requires_approval=False,
            required_scopes=(SKILL_READ,),
        ),
        _make_policy(
            "add_memory",
            read_only=False,
            risk_level=MEDIUM,
            requires_approval=False,
            required_scopes=(MEMORY_WRITE,),
            idempotent=False,
        ),
        _make_policy(
            "search_memory",
            read_only=True,
            risk_level=READ_ONLY,
            requires_approval=False,
            required_scopes=(MEMORY_READ,),
        ),
        _make_policy(
            "update_memory",
            read_only=False,
            risk_level=MEDIUM,
            requires_approval=False,
            required_scopes=(MEMORY_WRITE,),
            idempotent=False,
        ),
        _make_policy(
            "archive_memory",
            read_only=False,
            risk_level=HIGH,
            requires_approval=False,
            required_scopes=(MEMORY_MANAGE,),
            idempotent=False,
        ),
        _make_policy(
            "delete_memory",
            read_only=False,
            risk_level=HIGH,
            requires_approval=False,
            required_scopes=(MEMORY_MANAGE,),
            idempotent=False,
        ),
        _make_policy(
            "restore_memory",
            read_only=False,
            risk_level=MEDIUM,
            requires_approval=False,
            required_scopes=(MEMORY_MANAGE,),
            idempotent=False,
        ),
        _make_policy(
            "approve_memory",
            read_only=False,
            risk_level=MEDIUM,
            requires_approval=False,
            required_scopes=(MEMORY_MANAGE,),
            idempotent=False,
        ),
        _make_policy(
            "spawn_subagent",
            read_only=False,
            risk_level=HIGH,
            requires_approval=False,
            required_scopes=(AGENT_EXECUTE,),
            timeout_seconds=900,
            idempotent=False,
            sandbox_required=True,
        ),
        _make_policy(
            "compact",
            read_only=False,
            risk_level=LOW,
            requires_approval=False,
            required_scopes=(CONTEXT_WRITE,),
            idempotent=False,
        ),
        _make_policy(
            "schedule_cron",
            read_only=False,
            risk_level=HIGH,
            requires_approval=False,
            required_scopes=(CRON_WRITE,),
            idempotent=False,
        ),
        _make_policy(
            "list_crons",
            read_only=True,
            risk_level=READ_ONLY,
            requires_approval=False,
            required_scopes=(CRON_READ,),
        ),
        _make_policy(
            "cancel_cron",
            read_only=False,
            risk_level=MEDIUM,
            requires_approval=False,
            required_scopes=(CRON_WRITE,),
            idempotent=False,
        ),
        _make_policy(
            "list_cron_logs",
            read_only=True,
            risk_level=READ_ONLY,
            requires_approval=False,
            required_scopes=(CRON_READ,),
        ),
        _make_policy(
            "connect_mcp",
            read_only=False,
            risk_level=MEDIUM,
            requires_approval=False,
            required_scopes=(MCP_CONNECT,),
            idempotent=False,
        ),
        _make_policy(
            "list_background_tasks",
            read_only=True,
            risk_level=READ_ONLY,
            requires_approval=False,
            required_scopes=(BACKGROUND_READ,),
        ),
    ]
    return {policy.name: policy for policy in policies}


BUILTIN_TOOL_POLICIES = _build_builtin_policies()


def _dynamic_mcp_policy(name: str) -> ToolPolicy:
    from agent.mcp.registry import is_destructive_mcp_tool

    tool_name = name.split("__", 2)[-1]
    read_only = (
        bool(_MCP_READ_ONLY_NAME.match(tool_name))
        and not _MCP_WRITE_MARKER.search(tool_name)
    )
    if "deploy" in name.lower() or is_destructive_mcp_tool(name):
        read_only = False

    if read_only:
        return _make_policy(
            name,
            read_only=True,
            risk_level=READ_ONLY,
            requires_approval=False,
            required_scopes=(MCP_EXECUTE,),
        )
    return _make_policy(
        name,
        read_only=False,
        risk_level=HIGH,
        requires_approval=True,
        required_scopes=(MCP_EXECUTE,),
        idempotent=False,
    )


def get_tool_policy(name: str) -> ToolPolicy:
    """Return explicit policy metadata, or a conservative dynamic policy."""
    if name in BUILTIN_TOOL_POLICIES:
        return BUILTIN_TOOL_POLICIES[name]
    if name.startswith("mcp__"):
        return _dynamic_mcp_policy(name)
    return _make_policy(
        name,
        read_only=False,
        risk_level=HIGH,
        requires_approval=True,
        required_scopes=(UNKNOWN_TOOL,),
        idempotent=False,
    )


def _has_permission(context: ToolPolicyContext, scope: str) -> bool:
    return "*" in context.permissions or scope in context.permissions


def evaluate_tool_policy(
    name: str,
    context: ToolPolicyContext | None = None,
) -> ToolPolicyDecision:
    """Evaluate visibility and the approval requirement for one tool call."""
    context = context or ToolPolicyContext()
    policy = get_tool_policy(name)

    if context.allowed_tools is not None and name not in context.allowed_tools:
        return ToolPolicyDecision(
            name,
            allowed=False,
            requires_approval=policy.requires_approval,
            reason="Tool is not in the run allowlist",
            policy=policy,
        )

    missing_scopes = [
        scope for scope in policy.required_scopes
        if not _has_permission(context, scope)
    ]
    if missing_scopes:
        return ToolPolicyDecision(
            name,
            allowed=False,
            requires_approval=policy.requires_approval,
            reason=f"Missing permissions: {', '.join(missing_scopes)}",
            policy=policy,
        )

    if not policy.read_only and not context.write_enabled:
        return ToolPolicyDecision(
            name,
            allowed=False,
            requires_approval=policy.requires_approval,
            reason="Write operations are disabled for this run",
            policy=policy,
        )

    if policy.risk_level in {HIGH, CRITICAL} and not context.execute_enabled:
        return ToolPolicyDecision(
            name,
            allowed=False,
            requires_approval=policy.requires_approval,
            reason="High-risk execution is disabled for this run",
            policy=policy,
        )

    return ToolPolicyDecision(
        name,
        allowed=True,
        requires_approval=policy.requires_approval,
        reason="allowed",
        policy=policy,
    )


def filter_tool_definitions(
    tools: list[dict],
    context: ToolPolicyContext | None = None,
) -> list[dict]:
    """Filter model-visible tool definitions with the same policy decision."""
    return [
        tool for tool in tools
        if evaluate_tool_policy(tool.get("name", ""), context).allowed
    ]


__all__ = [
    "BUILTIN_TOOL_POLICIES",
    "ToolPolicy",
    "ToolPolicyContext",
    "ToolPolicyDecision",
    "evaluate_tool_policy",
    "filter_tool_definitions",
    "get_tool_policy",
]
