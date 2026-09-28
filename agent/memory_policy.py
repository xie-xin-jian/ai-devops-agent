"""Scope and ownership rules for governed long-term memory."""

from __future__ import annotations

from agent.rbac import (
    MEMORY_GLOBAL_WRITE,
    MEMORY_MANAGE,
    MEMORY_READ,
    MEMORY_WRITE,
    SESSION_MANAGE,
    Principal,
)


def _has_global_manage(principal: Principal) -> bool:
    return (
        principal.has(MEMORY_GLOBAL_WRITE)
        or principal.has(SESSION_MANAGE)
    )


def can_read_scope(
    principal: Principal,
    scope: str,
    *,
    owner_id: str = "",
    session_id: str = "",
) -> bool:
    if not principal.has(MEMORY_READ):
        return False
    if _has_global_manage(principal):
        return True

    scope = str(scope or "global")
    if scope.startswith("user:"):
        return scope == f"user:{principal.id}"
    if scope.startswith("session:"):
        return (
            bool(session_id)
            and scope == f"session:{session_id}"
        )
    if owner_id and owner_id != principal.id:
        return False
    return True


def can_write_scope(
    principal: Principal,
    scope: str,
    *,
    owner_id: str = "",
    session_id: str = "",
) -> bool:
    if not principal.has(MEMORY_WRITE):
        return False
    if (
        owner_id
        and owner_id != principal.id
        and not _has_global_manage(principal)
    ):
        return False

    scope = str(scope or "global")
    if scope.startswith("user:"):
        return (
            scope == f"user:{principal.id}"
            or _has_global_manage(principal)
        )
    if scope.startswith("session:"):
        return (
            bool(session_id)
            and scope == f"session:{session_id}"
        ) or _has_global_manage(principal)
    if scope == "global":
        return _has_global_manage(principal)
    return True


def can_manage_record(
    principal: Principal,
    memory: dict,
    *,
    session_id: str = "",
) -> bool:
    if _has_global_manage(principal):
        return True
    if not (
        principal.has(MEMORY_WRITE)
        or principal.has(MEMORY_MANAGE)
    ):
        return False
    owner_id = str(memory.get("owner_id") or "")
    if owner_id and owner_id != principal.id:
        return False
    scope = str(memory.get("scope") or "global")
    if scope.startswith("user:"):
        return scope == f"user:{principal.id}"
    if scope.startswith("session:"):
        return (
            bool(session_id)
            and scope == f"session:{session_id}"
        )
    return False


def readable_scopes(
    principal: Principal,
    *,
    default_scope: str,
    session_id: str = "",
) -> set[str]:
    if _has_global_manage(principal):
        return {default_scope}
    scopes = {"global", default_scope}
    scopes.add(f"user:{principal.id}")
    if session_id:
        scopes.add(f"session:{session_id}")
    return scopes


__all__ = [
    "can_manage_record",
    "can_read_scope",
    "can_write_scope",
    "readable_scopes",
]
