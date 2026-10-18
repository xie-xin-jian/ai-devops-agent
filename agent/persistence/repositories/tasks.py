"""PostgreSQL repository for tasks and their dependency edges."""

from __future__ import annotations

import time

from sqlalchemy import delete as sql_delete, func, select

from agent.persistence.database import session_scope
from agent.persistence.models import TaskDependencyRecord, TaskRecord
from agent.persistence.repositories.common import (
    record_to_dict,
    update_row_if_version,
    upsert_row,
)


VALID_PRIORITIES = {"low", "medium", "high"}

_UPDATE_COLUMNS = (
    "subject",
    "description",
    "status",
    "owner",
    "run_id",
    "source",
    "priority",
    "result",
    "task_metadata",
    "created_at",
    "updated_at",
)


def _dependency_ids(record: dict) -> list[str]:
    raw = record.get("blockedBy") or []
    if not isinstance(raw, (list, tuple, set)):
        return []
    seen: list[str] = []
    for item in raw:
        value = str(item or "").strip()
        if value and value not in seen:
            seen.append(value)
    return seen


def _values(record: dict) -> dict:
    now = time.time()
    priority = str(record.get("priority") or "medium").strip().lower()
    owner = record.get("owner")
    metadata = record.get("metadata")
    return {
        "id": str(record.get("id") or ""),
        "subject": str(record.get("subject") or "")[:300],
        "description": str(record.get("description") or ""),
        "status": str(record.get("status") or "pending")[:32],
        "owner": str(owner) if owner else None,
        "run_id": str(record.get("run_id") or ""),
        "source": str(record.get("source") or "task")[:32],
        "priority": priority if priority in VALID_PRIORITIES else "medium",
        "result": str(record.get("result") or ""),
        "task_metadata": dict(metadata) if isinstance(metadata, dict) else {},
        "created_at": float(record.get("created_at") or now),
        "updated_at": float(record.get("updated_at") or now),
        "version": 1,
    }


def _row_to_dict(row: TaskRecord, blocked_by: list[str]) -> dict:
    return {
        "id": row.id,
        "subject": row.subject,
        "description": row.description,
        "status": row.status,
        "owner": row.owner,
        "blockedBy": list(blocked_by),
        "run_id": row.run_id,
        "source": row.source,
        "metadata": dict(row.task_metadata or {}),
        "priority": row.priority,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "result": row.result,
    }


def _sync_dependencies(session, task_id: str, depends_on: list[str]) -> None:
    """Rewrite the edge set so PG matches the JSON ``blockedBy`` list.

    ``position`` keeps the caller's ordering, which makes a future
    JSON-vs-PG consistency check a straight list comparison.
    """
    wanted = list(dict.fromkeys(str(item) for item in depends_on if str(item).strip()))
    existing = set(
        session.execute(
            select(TaskDependencyRecord.depends_on_id).where(
                TaskDependencyRecord.task_id == task_id
            )
        ).scalars()
    )

    stale = existing - set(wanted)
    if stale:
        session.execute(
            sql_delete(TaskDependencyRecord).where(
                TaskDependencyRecord.task_id == task_id,
                TaskDependencyRecord.depends_on_id.in_(sorted(stale)),
            )
        )

    now = time.time()
    for position, depends_on_id in enumerate(wanted):
        upsert_row(
            session,
            TaskDependencyRecord,
            {
                "task_id": task_id,
                "depends_on_id": depends_on_id,
                "position": position,
                "created_at": now,
            },
            conflict_columns=["task_id", "depends_on_id"],
            update_columns=["position"],
        )


def upsert_task(
    record,
    *,
    expected_version: int | None = None,
    force: bool = False,
) -> bool:
    """Create or update one task plus its dependency edges."""
    data = record_to_dict(record)
    values = _values(data)
    if not values["id"]:
        return False
    depends_on = _dependency_ids(data)

    with session_scope() as session:
        if expected_version is None:
            upsert_row(
                session,
                TaskRecord,
                values,
                conflict_columns=["id"],
                update_columns=_UPDATE_COLUMNS,
                force=force,
            )
        elif not update_row_if_version(
            session,
            TaskRecord,
            values["id"],
            int(expected_version),
            values,
        ):
            return False
        _sync_dependencies(session, values["id"], depends_on)
    return True


def delete_task(task_id: str) -> bool:
    task_id = str(task_id or "")
    if not task_id:
        return False
    with session_scope() as session:
        session.execute(
            sql_delete(TaskDependencyRecord).where(
                TaskDependencyRecord.task_id == task_id
            )
        )
        result = session.execute(
            sql_delete(TaskRecord).where(TaskRecord.id == task_id)
        )
        return bool(result.rowcount)


def _dependencies_for(session, task_ids: list[str]) -> dict[str, list[str]]:
    if not task_ids:
        return {}
    rows = session.execute(
        select(
            TaskDependencyRecord.task_id,
            TaskDependencyRecord.depends_on_id,
        )
        .where(TaskDependencyRecord.task_id.in_(task_ids))
        .order_by(
            TaskDependencyRecord.task_id,
            TaskDependencyRecord.position,
        )
    ).all()
    grouped: dict[str, list[str]] = {}
    for task_id, depends_on_id in rows:
        grouped.setdefault(task_id, []).append(depends_on_id)
    return grouped


def fetch_task(task_id: str) -> dict | None:
    task_id = str(task_id or "")
    if not task_id:
        return None
    with session_scope() as session:
        row = session.get(TaskRecord, task_id)
        if row is None:
            return None
        blocked_by = _dependencies_for(session, [task_id]).get(task_id, [])
        return _row_to_dict(row, blocked_by)


def fetch_tasks() -> list[dict]:
    with session_scope() as session:
        rows = list(
            session.execute(
                select(TaskRecord).order_by(TaskRecord.created_at, TaskRecord.id)
            ).scalars()
        )
        grouped = _dependencies_for(session, [row.id for row in rows])
        return [
            _row_to_dict(row, grouped.get(row.id, []))
            for row in rows
        ]


def count_tasks() -> int:
    with session_scope() as session:
        return int(session.execute(select(func.count(TaskRecord.id))).scalar() or 0)


def count_task_dependencies() -> int:
    with session_scope() as session:
        return int(
            session.execute(
                select(func.count()).select_from(TaskDependencyRecord)
            ).scalar()
            or 0
        )


__all__ = [
    "count_task_dependencies",
    "count_tasks",
    "delete_task",
    "fetch_task",
    "fetch_tasks",
    "upsert_task",
]
