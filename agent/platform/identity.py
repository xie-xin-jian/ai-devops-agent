"""Minimal identity model.

The project currently runs as a single-user assistant. API authentication and
session ownership remain, but fine-grained role permissions are intentionally
removed from the runtime path.
"""

from __future__ import annotations

from dataclasses import dataclass

import agent.platform.config as config
from agent.tools.policy import ToolPolicyContext


# Compatibility constants used by API route signatures.
AGENT_CHAT = "agent.chat"
ACTION_APPROVE = "action.approve"
SESSION_MANAGE = "session.manage"
AUDIT_VIEW = "audit.view"
MCP_VIEW = "mcp.view"
CRON_READ = "cron.read"
CRON_WRITE = "cron.write"
MCP_CONNECT = "mcp.connect"
MEMORY_MANAGE = "memory.manage"
MEMORY_READ = "memory.read"
SKILL_READ = "skill.read"
TASK_READ = "task.read"
TASK_WRITE = "task.write"


@dataclass(frozen=True)
class Principal:
    id: str
    roles: frozenset[str]
    authenticated: bool = True

    def has(self, permission: str) -> bool:
        if not self.authenticated:
            return False
        if permission in {SESSION_MANAGE, AUDIT_VIEW}:
            return bool(
                {"admin", "platform-admin"} & set(self.roles)
            )
        return True

    def has_all(self, permissions) -> bool:
        return all(self.has(permission) for permission in permissions or ())

    def missing(self, permissions) -> list[str]:
        return [
            permission
            for permission in permissions or ()
            if not self.has(permission)
        ]

    def to_tool_policy_context(self) -> ToolPolicyContext:
        return ToolPolicyContext(
            permissions=frozenset({"*"}),
            write_enabled=True,
            execute_enabled=True,
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "roles": sorted(self.roles),
            "authenticated": self.authenticated,
        }


def principal_from_roles(
    user_id: str,
    roles,
    *,
    authenticated: bool = True,
) -> Principal:
    return Principal(
        id=str(user_id or "api-user"),
        roles=frozenset(str(role).strip() for role in roles or () if str(role).strip()),
        authenticated=authenticated,
    )


def system_admin_principal() -> Principal:
    return principal_from_roles("system", {"admin"})


def configured_api_principal() -> Principal:
    return principal_from_roles(
        config.API_AUTH_USER,
        config.API_AUTH_ROLES or ["admin"],
    )


__all__ = [
    "ACTION_APPROVE",
    "AGENT_CHAT",
    "AUDIT_VIEW",
    "MCP_CONNECT",
    "Principal",
    "SESSION_MANAGE",
    "configured_api_principal",
    "principal_from_roles",
    "system_admin_principal",
]
