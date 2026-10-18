"""PostgreSQL repository for Cron jobs, their claim protocol and run logs."""

from __future__ import annotations

import time
from typing import Iterable

from sqlalchemy import delete as sql_delete, func, select

from agent.persistence.database import session_scope
from agent.persistence.models import CronJobRecord, CronLogRecord
from agent.persistence.repositories.common import record_to_dict, upsert_row


_UPDATE_COLUMNS = (
    "cron_expr",
    "prompt",
    "recurring",
    "durable",
    "name",
    "description",
    "enabled",
    "created_at",
    "updated_at",
)

_LOG_UPDATE_COLUMNS = (
    "job_id",
    "cron_expr",
    "prompt",
    "fired_at",
    "fired_at_epoch",
    "finished_at",
    "success",
    "output",
    "error",
    "run_id",
    "session_id",
    "created_at",
)


def _job_values(record: dict) -> dict:
    now = time.time()
    return {
        "id": str(record.get("id") or ""),
        "cron_expr": str(record.get("cron") or record.get("cron_expr") or "")[:120],
        "prompt": str(record.get("prompt") or ""),
        "recurring": bool(record.get("recurring", True)),
        "durable": bool(record.get("durable", True)),
        "name": str(record.get("name") or "")[:200],
        "description": str(record.get("description") or ""),
        "enabled": bool(record.get("enabled", True)),
        "created_at": float(record.get("created_at") or now),
        "updated_at": float(record.get("updated_at") or now),
        "fire_count": 0,
        "version": 1,
    }


def _job_to_dict(row: CronJobRecord) -> dict:
    return {
        "id": row.id,
        "cron": row.cron_expr,
        "prompt": row.prompt,
        "recurring": bool(row.recurring),
        "durable": bool(row.durable),
        "name": row.name,
        "description": row.description,
        "enabled": bool(row.enabled),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "last_fired_at": row.last_fired_at,
        "fire_count": row.fire_count,
        "version": row.version,
    }


def _log_values(record: dict) -> dict:
    now = time.time()
    fired_at = str(record.get("fired_at") or "")
    epoch = record.get("fired_at_epoch")
    if epoch in (None, ""):
        epoch = _epoch_from_iso(fired_at, now)
    log_id = str(record.get("id") or "")
    if not log_id:
        log_id = f"{record.get('job_id') or ''}__{fired_at}"
    return {
        "id": log_id[:160],
        "job_id": str(record.get("job_id") or "")[:80],
        "cron_expr": str(record.get("cron") or "")[:120],
        "prompt": str(record.get("prompt") or ""),
        "fired_at": fired_at[:40],
        "fired_at_epoch": float(epoch or 0.0),
        "finished_at": str(record.get("finished_at") or "")[:40],
        "success": bool(record.get("success", True)),
        "output": str(record.get("output") or ""),
        "error": str(record.get("error") or ""),
        "run_id": str(record.get("run_id") or "")[:120],
        "session_id": str(record.get("session_id") or "")[:120],
        "created_at": float(record.get("created_at") or now),
    }


def _epoch_from_iso(value: str, fallback: float) -> float:
    from datetime import datetime

    try:
        return datetime.fromisoformat(value).timestamp()
    except (TypeError, ValueError):
        return fallback


def _log_to_dict(row: CronLogRecord) -> dict:
    return {
        "id": row.id,
        "job_id": row.job_id,
        "cron": row.cron_expr,
        "prompt": row.prompt,
        "fired_at": row.fired_at,
        "fired_at_epoch": row.fired_at_epoch,
        "finished_at": row.finished_at,
        "success": bool(row.success),
        "output": row.output,
        "error": row.error,
        "run_id": row.run_id,
        "session_id": row.session_id,
    }


def upsert_cron_job(record, *, force: bool = False) -> bool:
    values = _job_values(record_to_dict(record))
    if not values["id"] or len(values["id"]) > 80:
        return False
    with session_scope() as session:
        upsert_row(
            session,
            CronJobRecord,
            values,
            conflict_columns=["id"],
            update_columns=_UPDATE_COLUMNS,
            force=force,
        )
    return True


def upsert_cron_jobs(records, *, force: bool = False) -> int:
    count = 0
    for record in records:
        if upsert_cron_job(record, force=force):
            count += 1
    return count


def delete_cron_job(job_id: str) -> bool:
    job_id = str(job_id or "")
    if not job_id:
        return False
    with session_scope() as session:
        result = session.execute(
            sql_delete(CronJobRecord).where(CronJobRecord.id == job_id)
        )
        return bool(result.rowcount)


def delete_cron_log(log_id: str) -> bool:
    """Remove one mirrored cron log row (mirror maintenance only)."""
    log_id = str(log_id or "")
    if not log_id:
        return False
    with session_scope() as session:
        result = session.execute(
            sql_delete(CronLogRecord).where(CronLogRecord.id == log_id)
        )
        return bool(result.rowcount)


def fetch_cron_jobs() -> list[dict]:
    with session_scope() as session:
        rows = session.execute(
            select(CronJobRecord).order_by(CronJobRecord.created_at)
        ).scalars()
        return [_job_to_dict(row) for row in rows]


def claim_due_cron_jobs(
    job_ids: Iterable[str],
    *,
    minute_epoch: float,
) -> list[str]:
    """Claim the jobs this process is allowed to fire right now.

    Candidate rows are locked with ``FOR UPDATE SKIP LOCKED`` so parallel
    schedulers split the work instead of waiting on each other, and
    ``last_fired_at`` is written inside the same transaction. That write is
    the real dedupe: a job can be claimed for a given minute exactly once,
    across processes and across restarts.

    The caller decides which jobs are due (cron matching stays in Python);
    this method only answers "did this process win the minute".
    """
    ids = [str(job_id) for job_id in job_ids if str(job_id)]
    claimed: list[str] = []
    if not ids:
        return claimed

    with session_scope() as session:
        rows = session.execute(
            select(CronJobRecord)
            .where(
                CronJobRecord.id.in_(ids),
                CronJobRecord.enabled.is_(True),
            )
            .order_by(CronJobRecord.id)
            .with_for_update(skip_locked=True)
        ).scalars().all()

        for row in rows:
            if row.last_fired_at is not None and row.last_fired_at >= minute_epoch:
                continue
            row.last_fired_at = float(minute_epoch)
            row.fire_count = int(row.fire_count or 0) + 1
            row.updated_at = time.time()
            claimed.append(row.id)

    return claimed


def upsert_cron_log(record) -> bool:
    values = _log_values(record_to_dict(record))
    if not values["id"] or not values["job_id"]:
        return False
    with session_scope() as session:
        upsert_row(
            session,
            CronLogRecord,
            values,
            conflict_columns=["id"],
            update_columns=_LOG_UPDATE_COLUMNS,
        )
    return True


def fetch_cron_logs(job_id: str | None = None, limit: int = 20) -> list[dict]:
    statement = select(CronLogRecord)
    if job_id:
        statement = statement.where(CronLogRecord.job_id == str(job_id))
    statement = statement.order_by(
        CronLogRecord.fired_at_epoch.desc(),
        CronLogRecord.id.desc(),
    ).limit(max(1, int(limit)))

    with session_scope() as session:
        return [_log_to_dict(row) for row in session.execute(statement).scalars()]


def count_cron_jobs() -> int:
    with session_scope() as session:
        return int(session.execute(select(func.count(CronJobRecord.id))).scalar() or 0)


def count_cron_logs() -> int:
    with session_scope() as session:
        return int(session.execute(select(func.count(CronLogRecord.id))).scalar() or 0)


__all__ = [
    "claim_due_cron_jobs",
    "count_cron_jobs",
    "count_cron_logs",
    "delete_cron_job",
    "delete_cron_log",
    "fetch_cron_jobs",
    "fetch_cron_logs",
    "upsert_cron_job",
    "upsert_cron_jobs",
    "upsert_cron_log",
]
