"""Role-based access control and capability resolution."""

from __future__ import annotations

from dataclasses import dataclass

import agent.config as config
from agent.tool_policy import (
    ACTION_PROPOSE,
    AGENT_EXECUTE,
    BACKGROUND_READ,
    CONTEXT_WRITE,
    CRON_READ,
    CRON_WRITE,
    FILESYSTEM_READ,
    FILESYSTEM_WRITE,
    MCP_CONNECT,
    MCP_EXECUTE,
    MEMORY_MANAGE,
    MEMORY_READ,
    MEMORY_WRITE,
    OPS_READ,
    SHELL_EXECUTE,
    SKILL_READ,
    TASK_READ,
    TASK_WRITE,
    ToolPolicyContext,
)


AGENT_CHAT = "agent.chat"
ACTION_APPROVE = "action.approve"
SESSION_MANAGE = "session.manage"
AUDIT_VIEW = "audit.view"
AUDIT_MANAGE = "audit.manage"
MCP_VIEW = "mcp.view"
MEMORY_GLOBAL_WRITE = "memory.global.write"

PERMISSION_DEFINITIONS = (
    (AGENT_CHAT, "Use the Agent chat", "agent"),
    (ACTION_PROPOSE, "Create pending action proposals", "agent"),
    (AGENT_EXECUTE, "Run delegated Agents and background agents", "agent"),
    (ACTION_APPROVE, "Approve or cancel pending actions", "agent"),
    (SESSION_MANAGE, "Manage sessions owned by other users", "agent"),
    (FILESYSTEM_READ, "Read workspace files", "filesystem"),
    (FILESYSTEM_WRITE, "Create and modify workspace files", "filesystem"),
    (SHELL_EXECUTE, "Execute shell commands through governed runs", "shell"),
    (OPS_READ, "Inspect hosts, services, processes, and system logs", "ops"),
    (TASK_READ, "View tasks", "task"),
    (TASK_WRITE, "Create and update tasks", "task"),
    (MEMORY_READ, "Search long-term memory", "memory"),
    (MEMORY_WRITE, "Create and update memory records", "memory"),
    (MEMORY_MANAGE, "Archive, delete, and restore memory records", "memory"),
    (MEMORY_GLOBAL_WRITE, "Write global or cross-owner memory", "memory"),
    (SKILL_READ, "Read Agent skills", "skill"),
    (CONTEXT_WRITE, "Manage run planning and context state", "context"),
    (CRON_READ, "View scheduled jobs", "cron"),
    (CRON_WRITE, "Create and cancel scheduled jobs", "cron"),
    (BACKGROUND_READ, "View background task output", "background"),
    (MCP_VIEW, "View MCP server configuration", "mcp"),
    (MCP_CONNECT, "Connect and configure MCP servers", "mcp"),
    (MCP_EXECUTE, "Invoke MCP tools", "mcp"),
    (AUDIT_VIEW, "View audit events and run timelines", "audit"),
    (AUDIT_MANAGE, "Manage audit retention", "audit"),
)

ALL_PERMISSIONS = frozenset(
    code for code, _name, _category in PERMISSION_DEFINITIONS
)

READ_PERMISSIONS = frozenset({
    AGENT_CHAT,
    FILESYSTEM_READ,
    OPS_READ,
    TASK_READ,
    MEMORY_READ,
    SKILL_READ,
    CONTEXT_WRITE,
    CRON_READ,
    BACKGROUND_READ,
    MCP_VIEW,
})

ROLE_DEFINITIONS = {
    "platform-admin": {
        "name": "Platform administrator",
        "description": "Full platform and Agent capability.",
        "permissions": {"*"},
    },
    "ops-operator": {
        "name": "Operations operator",
        "description": "Can inspect, propose, approve, and execute operations.",
        "permissions": {
            *READ_PERMISSIONS,
            FILESYSTEM_WRITE,
            SHELL_EXECUTE,
            TASK_WRITE,
            MEMORY_WRITE,
            MEMORY_MANAGE,
            MEMORY_GLOBAL_WRITE,
            ACTION_PROPOSE,
            ACTION_APPROVE,
            AGENT_EXECUTE,
            CRON_WRITE,
            MCP_CONNECT,
            MCP_EXECUTE,
            AUDIT_VIEW,
        },
    },
    "developer": {
        "name": "Developer",
        "description": "Can inspect systems, edit files, and manage memory.",
        "permissions": {
            *READ_PERMISSIONS,
            FILESYSTEM_WRITE,
            TASK_WRITE,
            MEMORY_WRITE,
            MEMORY_MANAGE,
            ACTION_PROPOSE,
            ACTION_APPROVE,
        },
    },
    "auditor": {
        "name": "Security auditor",
        "description": "Read-only access plus audit timelines.",
        "permissions": {
            *READ_PERMISSIONS,
            AUDIT_VIEW,
        },
    },
    "viewer": {
        "name": "Read-only viewer",
        "description": "Can inspect system state without mutation.",
        "permissions": set(READ_PERMISSIONS),
    },
}


@dataclass(frozen=True)
class Principal:
    id: str
    roles: frozenset[str]
    permissions: frozenset[str]
    authenticated: bool = True

    def has(self, permission: str) -> bool:
        return "*" in self.permissions or permission in self.permissions

    def has_all(self, permissions) -> bool:
        return all(self.has(permission) for permission in permissions or ())

    def missing(self, permissions) -> list[str]:
        return [
            permission
            for permission in permissions or ()
            if not self.has(permission)
        ]

    def to_tool_policy_context(self) -> ToolPolicyContext:
        write_permissions = {
            FILESYSTEM_WRITE,
            TASK_WRITE,
            MEMORY_WRITE,
            MEMORY_MANAGE,
            CRON_WRITE,
            MCP_CONNECT,
            ACTION_PROPOSE,
        }
        execute_permissions = {
            SHELL_EXECUTE,
            AGENT_EXECUTE,
            MCP_EXECUTE,
        }
        return ToolPolicyContext(
            permissions=frozenset(self.permissions),
            write_enabled=any(self.has(code) for code in write_permissions),
            execute_enabled=any(
                self.has(code) for code in execute_permissions
            ),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "roles": sorted(self.roles),
            "permissions": sorted(self.permissions),
            "authenticated": self.authenticated,
        }


def resolve_role_permissions(roles) -> frozenset[str]:
    permissions: set[str] = set()
    for role in roles or ():
        definition = ROLE_DEFINITIONS.get(str(role))
        if definition is None:
            continue
        role_permissions = definition["permissions"]
        if "*" in role_permissions:
            return ALL_PERMISSIONS
        permissions.update(role_permissions)
    return frozenset(permissions)


def principal_from_roles(
    user_id: str,
    roles,
    *,
    authenticated: bool = True,
) -> Principal:
    role_set = frozenset(
        str(role).strip()
        for role in roles or ()
        if str(role).strip()
    )
    return Principal(
        id=str(user_id or "anonymous"),
        roles=role_set,
        permissions=resolve_role_permissions(role_set),
        authenticated=authenticated,
    )


def system_admin_principal() -> Principal:
    return principal_from_roles("system", {"platform-admin"})


def configured_api_principal() -> Principal:
    return principal_from_roles(
        config.API_AUTH_USER,
        config.API_AUTH_ROLES,
    )


def get_permission_catalog() -> list[dict]:
    return [
        {
            "code": code,
            "name": name,
            "category": category,
        }
        for code, name, category in PERMISSION_DEFINITIONS
    ]


def get_role_catalog() -> list[dict]:
    return [
        {
            "code": code,
            "name": definition["name"],
            "description": definition["description"],
            "permissions": (
                ["*"]
                if "*" in definition["permissions"]
                else sorted(definition["permissions"])
            ),
        }
        for code, definition in ROLE_DEFINITIONS.items()
    ]


__all__ = [
    "ACTION_APPROVE",
    "AGENT_CHAT",
    "ALL_PERMISSIONS",
    "AUDIT_MANAGE",
    "AUDIT_VIEW",
    "MCP_VIEW",
    "MEMORY_GLOBAL_WRITE",
    "PERMISSION_DEFINITIONS",
    "Principal",
    "ROLE_DEFINITIONS",
    "SESSION_MANAGE",
    "configured_api_principal",
    "get_permission_catalog",
    "get_role_catalog",
    "principal_from_roles",
    "resolve_role_permissions",
    "system_admin_principal",
]
