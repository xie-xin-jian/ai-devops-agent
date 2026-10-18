"""PostgreSQL repository for audit events."""

from __future__ import annotations

import time

from sqlalchemy import delete as sql_delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

from agent.persistence.database import session_scope
from agent.persistence.models import AuditEventRecord


def _event_dict(event) -> dict:
    if isinstance(event, dict):
        return event
    to_dict = getattr(event, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    raise TypeError("audit event must be a dict or expose to_dict()")


def persist_audit_event(event) -> bool:
    data = _event_dict(event)
    values = {
        "id": str(data.get("id") or ""),
        "occurred_at": float(data.get("occurred_at") or time.time()),
        "event_type": str(data.get("event_type") or "unknown"),
        "title": str(data.get("title") or "")[:300],
        "summary": str(data.get("summary") or ""),
        "result": str(data.get("result") or "success"),
        "severity": str(data.get("severity") or "info"),
        "actor": str(data.get("actor") or "system")[:100],
        "session_id": str(data.get("session_id") or ""),
        "run_id": str(data.get("run_id") or ""),
        "action_id": str(data.get("action_id") or ""),
        "action_code": str(data.get("action_code") or ""),
        "tool_name": str(data.get("tool_name") or ""),
        "risk_level": str(data.get("risk_level") or ""),
        "correlation_id": str(data.get("correlation_id") or ""),
        "payload": data.get("payload") or {},
        "event_metadata": data.get("metadata") or {},
        "created_at": time.time(),
    }
    if not values["id"]:
        return False

    with session_scope() as session:
        bind = session.get_bind()
        if bind.dialect.name == "postgresql":
            statement = (
                pg_insert(AuditEventRecord)
                .values(**values)
                .on_conflict_do_nothing(
                    index_elements=[AuditEventRecord.id]
                )
            )
            session.execute(statement)
        else:
            session.merge(AuditEventRecord(**values))
    return True


def delete_audit_event(event_id: str) -> bool:
    """Remove one mirrored audit row (mirror maintenance only)."""
    event_id = str(event_id or "")
    if not event_id:
        return False
    with session_scope() as session:
        result = session.execute(
            sql_delete(AuditEventRecord).where(
                AuditEventRecord.id == event_id
            )
        )
        return bool(result.rowcount)


def delete_audit_events_for(
    *,
    session_id: str = "",
    run_id: str = "",
) -> int:
    """Delete every mirrored audit row of a session or run.

    Mirror maintenance only, and deliberately refuses to run without a
    filter: wiping the audit trail must always be scoped to named records.
    """
    if not session_id and not run_id:
        raise ValueError("session_id or run_id is required")
    with session_scope() as session:
        statement = sql_delete(AuditEventRecord)
        if session_id and run_id:
            statement = statement.where(
                (AuditEventRecord.session_id == str(session_id))
                | (AuditEventRecord.run_id == str(run_id))
            )
        elif session_id:
            statement = statement.where(
                AuditEventRecord.session_id == str(session_id)
            )
        else:
            statement = statement.where(
                AuditEventRecord.run_id == str(run_id)
            )
        result = session.execute(statement)
        return int(result.rowcount or 0)


__all__ = [
    "delete_audit_event",
    "delete_audit_events_for",
    "persist_audit_event",
]
