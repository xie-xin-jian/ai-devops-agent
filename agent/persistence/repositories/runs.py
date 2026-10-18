"""PostgreSQL repository for runs and their resume snapshots."""

from __future__ import annotations

import time

from sqlalchemy import (
    delete as sql_delete,
    func,
    or_,
    select,
    update as sql_update,
)

from agent.persistence.database import session_scope
from agent.persistence.models import RunRecord, RunSnapshotRecord
from agent.persistence.repositories.common import (
    record_to_dict,
    upsert_row,
)
from agent.persistence.repositories.sessions import (
    content_hash,
    normalize_messages,
)


RUN_STATUS_RUNNING = "running"
RUN_STATUS_COMPLETED = "completed"
RUN_STATUS_FAILED = "failed"
RUN_STATUS_CANCELED = "canceled"
RUN_STATUS_INTERRUPTED = "interrupted"

TERMINAL_RUN_STATUSES = (
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    RUN_STATUS_CANCELED,
    RUN_STATUS_INTERRUPTED,
)

_UPDATE_COLUMNS = (
    "session_id",
    "owner_id",
    "source",
    "status",
    "phase",
    "user_message",
    "safe_to_resume",
    "active_tool",
    "interruption_reason",
    "resume_count",
    "message_count",
    "created_at",
    "updated_at",
    "finished_at",
)

_SNAPSHOT_UPDATE_COLUMNS = (
    "session_id",
    "messages",
    "message_count",
    "content_hash",
    "updated_at",
)


def _run_values(record: dict) -> dict:
    now = time.time()

    def _optional_float(value):
        return None if value in (None, "") else float(value)

    return {
        "run_id": str(record.get("run_id") or ""),
        "session_id": str(record.get("session_id") or "")[:120],
        "owner_id": str(record.get("owner_id") or "")[:120],
        "source": str(record.get("source") or "chat")[:32],
        "status": str(record.get("status") or RUN_STATUS_RUNNING)[:32],
        "phase": str(record.get("phase") or "model")[:40],
        "user_message": str(record.get("user_message") or ""),
        # A record without the flag is not resumable.
        "safe_to_resume": bool(record.get("safe_to_resume", False)),
        "active_tool": str(record.get("active_tool") or "")[:120],
        "interruption_reason": str(record.get("interruption_reason") or ""),
        "resume_count": int(record.get("resume_count") or 0),
        "message_count": int(record.get("message_count") or 0),
        "created_at": float(record.get("created_at") or now),
        "updated_at": float(record.get("updated_at") or now),
        "finished_at": _optional_float(record.get("finished_at")),
        "version": 1,
    }


def _run_to_dict(row: RunRecord) -> dict:
    return {
        "run_id": row.run_id,
        "session_id": row.session_id,
        "owner_id": row.owner_id,
        "source": row.source,
        "status": row.status,
        "phase": row.phase,
        "user_message": row.user_message,
        "safe_to_resume": bool(row.safe_to_resume),
        "active_tool": row.active_tool,
        "interruption_reason": row.interruption_reason,
        "resume_count": row.resume_count,
        "message_count": row.message_count,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "finished_at": row.finished_at,
        "version": row.version,
    }


def upsert_run(record, *, force: bool = False) -> bool:
    """Mirror a run row and its message snapshot.

    The snapshot is a single JSONB document, so an unchanged snapshot is
    detected with a content hash and skipped instead of being rewritten on
    every phase transition.
    """
    data = record_to_dict(record)
    messages = normalize_messages(data.get("messages"))
    data = {**data, "message_count": len(messages)}
    values = _run_values(data)
    if not values["run_id"] or len(values["run_id"]) > 120:
        return False
    digest = content_hash(messages)

    with session_scope() as session:
        upsert_row(
            session,
            RunRecord,
            values,
            conflict_columns=["run_id"],
            update_columns=_UPDATE_COLUMNS,
            force=force,
        )
        existing = session.get(RunSnapshotRecord, values["run_id"])
        if (
            not force
            and existing is not None
            and existing.content_hash == digest
        ):
            return True
        upsert_row(
            session,
            RunSnapshotRecord,
            {
                "run_id": values["run_id"],
                "session_id": values["session_id"],
                "messages": messages,
                "message_count": len(messages),
                "content_hash": digest,
                "created_at": (
                    existing.created_at if existing is not None else values["created_at"]
                ),
                "updated_at": values["updated_at"],
            },
            conflict_columns=["run_id"],
            update_columns=_SNAPSHOT_UPDATE_COLUMNS,
        )
    return True


def delete_run(run_id: str) -> bool:
    run_id = str(run_id or "")
    if not run_id:
        return False
    with session_scope() as session:
        session.execute(
            sql_delete(RunSnapshotRecord).where(
                RunSnapshotRecord.run_id == run_id
            )
        )
        result = session.execute(
            sql_delete(RunRecord).where(RunRecord.run_id == run_id)
        )
        return bool(result.rowcount)


def fetch_run(run_id: str, *, include_messages: bool = True) -> dict | None:
    run_id = str(run_id or "")
    if not run_id:
        return None
    with session_scope() as session:
        row = session.get(RunRecord, run_id)
        if row is None:
            return None
        record = _run_to_dict(row)
        if include_messages:
            snapshot = session.get(RunSnapshotRecord, run_id)
            record["messages"] = list(snapshot.messages or []) if snapshot else []
    return record


def fetch_runs(
    *,
    owner_id: str | None = None,
    session_id: str | None = None,
    status: str | None = None,
    statuses: set[str] | None = None,
    limit: int = 100,
) -> list[dict]:
    statement = select(RunRecord)
    if owner_id:
        # Runs without an owner stay visible.
        statement = statement.where(
            or_(
                RunRecord.owner_id == str(owner_id),
                RunRecord.owner_id == "",
            )
        )
    if session_id:
        statement = statement.where(RunRecord.session_id == str(session_id))
    if status:
        statement = statement.where(RunRecord.status == str(status))
    if statuses:
        statement = statement.where(
            RunRecord.status.in_(sorted(str(item) for item in statuses))
        )
    statement = statement.order_by(
        RunRecord.updated_at.desc(),
        RunRecord.run_id.desc(),
    ).limit(max(1, min(int(limit), 500)))

    with session_scope() as session:
        return [_run_to_dict(row) for row in session.execute(statement).scalars()]


def interrupt_stale_runs(reason: str) -> int:
    """Mark every non-terminal run as interrupted; returns rows changed."""
    now = time.time()
    with session_scope() as session:
        result = session.execute(
            sql_update(RunRecord)
            .where(RunRecord.status.not_in(list(TERMINAL_RUN_STATUSES)))
            .values(
                status=RUN_STATUS_INTERRUPTED,
                phase="interrupted",
                interruption_reason=str(reason),
                active_tool="",
                updated_at=now,
                finished_at=now,
                version=RunRecord.version + 1,
            )
        )
        return int(result.rowcount or 0)


def count_runs() -> int:
    with session_scope() as session:
        return int(session.execute(select(func.count(RunRecord.run_id))).scalar() or 0)


def count_run_snapshots() -> int:
    with session_scope() as session:
        return int(
            session.execute(
                select(func.count(RunSnapshotRecord.run_id))
            ).scalar()
            or 0
        )


__all__ = [
    "RUN_STATUS_CANCELED",
    "RUN_STATUS_COMPLETED",
    "RUN_STATUS_FAILED",
    "RUN_STATUS_INTERRUPTED",
    "RUN_STATUS_RUNNING",
    "TERMINAL_RUN_STATUSES",
    "count_run_snapshots",
    "count_runs",
    "delete_run",
    "fetch_run",
    "fetch_runs",
    "interrupt_stale_runs",
    "upsert_run",
]
