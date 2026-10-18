"""Application-level projections shared by drift detection and shadow reads.

Both the periodic JSON-vs-PostgreSQL check and the per-request shadow read
must compare "what the application would show", not the raw stored shape:
PostgreSQL rows carry mirror-only columns (``version``, ``expires_at``),
legacy JSON records omit fields that the domain fills with defaults, and
message bodies live in a different structure on each side.

Keeping the projection in one module means there is a single definition of
that view to keep honest.
"""

from __future__ import annotations


def _get(record, field: str, default=None):
    if isinstance(record, dict):
        return record.get(field, default)
    return getattr(record, field, default)


def _text(value) -> str:
    return str(value or "")


def _messages(value) -> list[dict]:
    return [
        {
            "role": _text(message.get("role")),
            "content": message.get("content", ""),
        }
        for message in value or []
        if isinstance(message, dict)
    ]


def view_target(record) -> dict:
    return {
        "id": _text(_get(record, "id")),
        "name": _text(_get(record, "name")),
        "root": _text(_get(record, "root")),
        "description": _text(_get(record, "description")),
        "service": _text(_get(record, "service")),
        "health_url": _text(_get(record, "health_url")),
        "deploy_command": _text(_get(record, "deploy_command")),
        "restart_command": _text(_get(record, "restart_command")),
        "log_path": _text(_get(record, "log_path")),
    }


def view_task(record) -> dict:
    blocked_by = _get(record, "blockedBy") or []
    return {
        "id": _text(_get(record, "id")),
        "subject": _text(_get(record, "subject")),
        "description": _text(_get(record, "description")),
        "status": _text(_get(record, "status")),
        "owner": _text(_get(record, "owner")),
        "blockedBy": [str(item) for item in blocked_by],
        "run_id": _text(_get(record, "run_id")),
        "source": _text(_get(record, "source")),
        "priority": _text(_get(record, "priority")),
        "result": _text(_get(record, "result")),
    }


def view_memory(record) -> dict:
    return {
        "id": _text(_get(record, "id")),
        "content_hash": _text(_get(record, "content_hash")),
        "status": _text(_get(record, "status")),
        "importance": int(_get(record, "importance") or 0),
        "scope": _text(_get(record, "scope")),
        "owner_id": _text(_get(record, "owner_id")),
        "access_count": int(_get(record, "access_count") or 0),
        "superseded_by": _text(_get(record, "superseded_by")),
    }


def view_action(record) -> dict:
    return {
        "id": _text(_get(record, "id")),
        "status": _text(_get(record, "status")),
        "tool_use_id": _text(_get(record, "tool_use_id")),
        "confirmed_by": _text(_get(record, "confirmed_by")),
        "canceled_by": _text(_get(record, "canceled_by")),
    }


def view_session(record) -> dict:
    return {
        "session_id": _text(_get(record, "session_id")),
        "owner_id": _text(_get(record, "owner_id")),
        "status": _text(_get(record, "status")),
        "target_id": _text(_get(record, "target_id")),
        "title": _text(_get(record, "title")),
        "messages": _messages(_get(record, "messages")),
    }


def view_run(record) -> dict:
    """Normalize a run the way the application reads it.

    Legacy run files predate ``safe_to_resume`` / ``active_tool``, so raw
    dicts differ while the application-visible values are identical.

    ``message_count`` is derived from the snapshot when the source does not
    carry it: list reads fill the field, single-record reads only carry the
    message list.
    """
    messages = _get(record, "messages")
    message_count = _get(record, "message_count")
    if message_count is None and isinstance(messages, list):
        message_count = len(messages)
    return {
        "run_id": _text(_get(record, "run_id")),
        "session_id": _text(_get(record, "session_id")),
        "owner_id": _text(_get(record, "owner_id")),
        "source": _text(_get(record, "source") or "chat"),
        "status": _text(_get(record, "status")),
        "phase": _text(_get(record, "phase")),
        "safe_to_resume": bool(_get(record, "safe_to_resume")),
        "active_tool": _text(_get(record, "active_tool")),
        "message_count": int(message_count or 0),
    }


VIEWS = {
    "targets": view_target,
    "tasks": view_task,
    "memories": view_memory,
    "actions": view_action,
    "sessions": view_session,
    "runs": view_run,
}

KEY_FIELDS = {
    "targets": "id",
    "tasks": "id",
    "memories": "id",
    "actions": "id",
    "sessions": "session_id",
    "runs": "run_id",
}


def view(domain: str, record, *, with_key: bool = True):
    """Project one record for a domain, or return it unchanged if unknown."""
    projector = VIEWS.get(domain)
    if projector is None:
        return record
    projected = projector(record)
    if with_key:
        return projected
    key_field = KEY_FIELDS[domain]
    return {
        name: value
        for name, value in projected.items()
        if name != key_field
    }


def keyed(domain: str, records) -> dict:
    """Map a record collection to ``{key: projection}``."""
    key_field = KEY_FIELDS[domain]
    result = {}
    for record in records or []:
        projected = view(domain, record)
        result[str(projected.get(key_field) or "")] = projected
    return result


__all__ = [
    "KEY_FIELDS",
    "VIEWS",
    "keyed",
    "view",
    "view_action",
    "view_memory",
    "view_run",
    "view_session",
    "view_target",
    "view_task",
]
