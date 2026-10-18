"""PostgreSQL repository for background tasks."""

from __future__ import annotations

import time

from sqlalchemy import (
    delete as sql_delete,
    func,
    select,
    update as sql_update,
)

from agent.persistence.database import session_scope
from agent.persistence.models import BackgroundTaskRecord
from agent.persistence.repositories.common import record_to_dict, upsert_row


STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

_UPDATE_COLUMNS = (
    "tool_use_id",
    "command",
    "status",
    "run_id",
    "parent_run_id",
    "session_id",
    "owner_id",
    "source",
    "error",
    "interruption_reason",
    "output",
    "notified",
    "created_at",
    "updated_at",
)


def _values(record: dict) -> dict:
    now = time.time()
    updated_at = float(record.get("updated_at") or now)
    return {
        "id": str(record.get("background_id") or record.get("id") or ""),
        "tool_use_id": str(record.get("tool_use_id") or "")[:120],
        "command": str(record.get("command") or ""),
        "status": str(record.get("status") or STATUS_RUNNING)[:32],
        "run_id": str(record.get("run_id") or "")[:120],
        "parent_run_id": str(record.get("parent_run_id") or "")[:120],
        "session_id": str(record.get("session_id") or "")[:120],
        "owner_id": str(record.get("owner_id") or "")[:120],
        "source": str(record.get("source") or "background")[:32],
        "error": str(record.get("error") or ""),
        "interruption_reason": str(record.get("interruption_reason") or ""),
        "output": str(record.get("output") or ""),
        "notified": bool(record.get("notified", False)),
        "created_at": float(record.get("created_at") or updated_at),
        "updated_at": updated_at,
        "version": 1,
    }


def _row_to_dict(row: BackgroundTaskRecord) -> dict:
    return {
        "background_id": row.id,
        "tool_use_id": row.tool_use_id,
        "command": row.command,
        "status": row.status,
        "run_id": row.run_id,
        "parent_run_id": row.parent_run_id,
        "session_id": row.session_id,
        "owner_id": row.owner_id,
        "source": row.source,
        "error": row.error,
        "interruption_reason": row.interruption_reason,
        "output": row.output,
        "notified": bool(row.notified),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "version": row.version,
    }


def upsert_background_task(record, *, force: bool = False) -> bool:
    values = _values(record_to_dict(record))
    if not values["id"] or len(values["id"]) > 80:
        return False
    with session_scope() as session:
        upsert_row(
            session,
            BackgroundTaskRecord,
            values,
            conflict_columns=["id"],
            update_columns=_UPDATE_COLUMNS,
            force=force,
        )
    return True


def mark_background_interrupted(
    background_id: str,
    *,
    reason: str,
    at: float | None = None,
) -> bool:
    """CAS the running -> failed transition for one task.

    Returns False when the row is missing or already finished, so a second
    process performing the same recovery cannot claim it again.
    """
    background_id = str(background_id or "")
    if not background_id:
        return False
    with session_scope() as session:
        result = session.execute(
            sql_update(BackgroundTaskRecord)
            .where(
                BackgroundTaskRecord.id == background_id,
                BackgroundTaskRecord.status == STATUS_RUNNING,
            )
            .values(
                status=STATUS_FAILED,
                error=str(reason),
                interruption_reason=str(reason),
                updated_at=float(at or time.time()),
                version=BackgroundTaskRecord.version + 1,
            )
        )
        return bool(result.rowcount)


def fetch_background_tasks() -> list[dict]:
    with session_scope() as session:
        rows = session.execute(
            select(BackgroundTaskRecord).order_by(
                BackgroundTaskRecord.created_at.desc(),
                BackgroundTaskRecord.id.desc(),
            )
        ).scalars()
        return [_row_to_dict(row) for row in rows]


def fetch_background_task(background_id: str) -> dict | None:
    background_id = str(background_id or "")
    if not background_id:
        return None
    with session_scope() as session:
        row = session.get(BackgroundTaskRecord, background_id)
        return _row_to_dict(row) if row is not None else None


def delete_background_task(background_id: str) -> bool:
    """Remove one mirrored background row (mirror maintenance only)."""
    background_id = str(background_id or "")
    if not background_id:
        return False
    with session_scope() as session:
        result = session.execute(
            sql_delete(BackgroundTaskRecord).where(
                BackgroundTaskRecord.id == background_id
            )
        )
        return bool(result.rowcount)


def count_background_tasks() -> int:
    with session_scope() as session:
        return int(
            session.execute(select(func.count(BackgroundTaskRecord.id))).scalar() or 0
        )


__all__ = [
    "STATUS_COMPLETED",
    "STATUS_FAILED",
    "STATUS_RUNNING",
    "count_background_tasks",
    "delete_background_task",
    "fetch_background_task",
    "fetch_background_tasks",
    "mark_background_interrupted",
    "upsert_background_task",
]
