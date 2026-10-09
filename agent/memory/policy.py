"""Scope and ownership rules for governed long-term memory."""

from __future__ import annotations

from agent.platform.identity import Principal


def _is_admin(principal: Principal) -> bool:
    return bool({"admin", "platform-admin"} & set(principal.roles))


def _is_read_only(principal: Principal) -> bool:
    return "viewer" in principal.roles


def can_read_scope(
    principal: Principal,
    scope: str,
    *,
    owner_id: str = "",
    session_id: str = "",
) -> bool:
    if not principal.authenticated:
        return False
    if _is_admin(principal):
        return True

    scope = str(scope or "global")
    if scope.startswith("user:"):
        return scope == f"user:{principal.id}"
    if scope.startswith("session:"):
        return bool(session_id) and scope == f"session:{session_id}"
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
    if not principal.authenticated or _is_read_only(principal):
        return False
    if owner_id and owner_id != principal.id and not _is_admin(principal):
        return False

    scope = str(scope or "global")
    if scope.startswith("user:"):
        return scope == f"user:{principal.id}" or _is_admin(principal)
    if scope.startswith("session:"):
        return (bool(session_id) and scope == f"session:{session_id}") or _is_admin(
            principal
        )
    if scope == "global":
        return _is_admin(principal)
    return True


def can_manage_record(
    principal: Principal,
    memory: dict,
    *,
    session_id: str = "",
) -> bool:
    if _is_admin(principal):
        return True
    if not principal.authenticated or _is_read_only(principal):
        return False
    owner_id = str(memory.get("owner_id") or "")
    if owner_id and owner_id != principal.id:
        return False
    scope = str(memory.get("scope") or "global")
    if scope.startswith("user:"):
        return scope == f"user:{principal.id}"
    if scope.startswith("session:"):
        return bool(session_id) and scope == f"session:{session_id}"
    return False


def readable_scopes(
    principal: Principal,
    *,
    default_scope: str,
    session_id: str = "",
) -> set[str]:
    if _is_admin(principal):
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
