"""PostgreSQL repository for pending actions with CAS state transitions.

Every transition is a conditional UPDATE. The database decides who wins, so
two approvals arriving at the same time cannot both succeed and cannot
silently overwrite each other.
"""

from __future__ import annotations

import time
from typing import Sequence

from sqlalchemy import (
    delete as sql_delete,
    func,
    select,
    update as sql_update,
)

from agent.persistence.database import session_scope
from agent.persistence.models import PendingActionRecord
from agent.persistence.repositories.common import (
    record_to_dict,
    update_row_if_version,
    upsert_row,
)


STATUS_PENDING = "pending"
STATUS_CONFIRMED = "confirmed"
STATUS_CANCELED = "canceled"
STATUS_EXECUTED = "executed"
STATUS_FAILED = "failed"


_UPDATE_COLUMNS = (
    "session_id",
    "target_id",
    "run_id",
    "tool_use_id",
    "owner_id",
    "action_code",
    "title",
    "risk_level",
    "agent_mode",
    "status",
    "source_message",
    "summary",
    "payload",
    "steps",
    "impact",
    "rollback_plan",
    "verification",
    "result_payload",
    "created_at",
    "updated_at",
    "confirmed_by",
    "confirmed_at",
    "canceled_by",
    "canceled_at",
    "cancel_reason",
)


def _values(record: dict) -> dict:
    now = time.time()

    def _optional_float(value):
        return None if value in (None, "") else float(value)

    return {
        "id": str(record.get("id") or ""),
        "session_id": str(record.get("session_id") or "")[:120],
        "target_id": str(record.get("target_id") or "")[:120],
        "run_id": str(record.get("run_id") or "")[:120],
        "tool_use_id": str(record.get("tool_use_id") or "")[:120],
        "owner_id": str(record.get("owner_id") or "")[:120],
        "action_code": str(record.get("action_code") or "")[:160],
        "title": str(record.get("title") or "")[:300],
        "risk_level": str(record.get("risk_level") or "")[:32],
        "agent_mode": str(record.get("agent_mode") or "")[:32],
        "status": str(record.get("status") or STATUS_PENDING)[:32],
        "source_message": str(record.get("source_message") or ""),
        "summary": str(record.get("summary") or ""),
        "payload": dict(record.get("payload") or {}),
        "steps": list(record.get("steps") or []),
        "impact": str(record.get("impact") or ""),
        "rollback_plan": str(record.get("rollback_plan") or ""),
        "verification": str(record.get("verification") or ""),
        "result_payload": dict(record.get("result_payload") or {}),
        "created_at": float(record.get("created_at") or now),
        "updated_at": float(record.get("updated_at") or now),
        "confirmed_by": str(record.get("confirmed_by") or "")[:120],
        "confirmed_at": _optional_float(record.get("confirmed_at")),
        "canceled_by": str(record.get("canceled_by") or "")[:120],
        "canceled_at": _optional_float(record.get("canceled_at")),
        "cancel_reason": str(record.get("cancel_reason") or ""),
        "version": 1,
    }


def _row_to_dict(row: PendingActionRecord) -> dict:
    return {
        "id": row.id,
        "session_id": row.session_id,
        "target_id": row.target_id,
        "run_id": row.run_id,
        "tool_use_id": row.tool_use_id,
        "owner_id": row.owner_id,
        "action_code": row.action_code,
        "title": row.title,
        "risk_level": row.risk_level,
        "agent_mode": row.agent_mode,
        "status": row.status,
        "source_message": row.source_message,
        "summary": row.summary,
        "payload": dict(row.payload or {}),
        "steps": list(row.steps or []),
        "impact": row.impact,
        "rollback_plan": row.rollback_plan,
        "verification": row.verification,
        "result_payload": dict(row.result_payload or {}),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "confirmed_by": row.confirmed_by,
        "confirmed_at": row.confirmed_at,
        "canceled_by": row.canceled_by,
        "canceled_at": row.canceled_at,
        "cancel_reason": row.cancel_reason,
        "version": row.version,
    }


def upsert_action(
    record,
    *,
    expected_version: int | None = None,
    force: bool = False,
) -> bool:
    """Mirror the current action state, or apply an optimistic update."""
    values = _values(record_to_dict(record))
    if not values["id"] or len(values["id"]) > 80:
        return False

    with session_scope() as session:
        if expected_version is None:
            upsert_row(
                session,
                PendingActionRecord,
                values,
                conflict_columns=["id"],
                update_columns=_UPDATE_COLUMNS,
                force=force,
            )
            return True
        return update_row_if_version(
            session,
            PendingActionRecord,
            values["id"],
            int(expected_version),
            values,
        )


def transition_action(
    action_id: str,
    *,
    expect_statuses: Sequence[str],
    new_status: str,
    fields: dict | None = None,
) -> dict | None:
    """Compare-and-set one status transition.

    Returns the updated row, or ``None`` when the action is missing or is no
    longer in one of ``expect_statuses`` — meaning another approver already
    moved it.
    """
    action_id = str(action_id or "")
    allowed = [str(status) for status in expect_statuses if str(status)]
    if not action_id or not allowed:
        return None

    payload = {
        key: value
        for key, value in (fields or {}).items()
        if key in _UPDATE_COLUMNS
    }
    payload["status"] = str(new_status)
    payload["updated_at"] = time.time()

    with session_scope() as session:
        result = session.execute(
            sql_update(PendingActionRecord)
            .where(
                PendingActionRecord.id == action_id,
                PendingActionRecord.status.in_(allowed),
            )
            .values(**payload, version=PendingActionRecord.version + 1)
        )
        if not result.rowcount:
            return None
        row = session.get(PendingActionRecord, action_id)
        return _row_to_dict(row) if row is not None else None


def confirm_action(action_id: str, record) -> dict | None:
    """pending -> confirmed, refusing to confirm twice."""
    return transition_action(
        action_id,
        expect_statuses=[STATUS_PENDING],
        new_status=STATUS_CONFIRMED,
        fields=record_to_dict(record),
    )


def cancel_action(action_id: str, record) -> dict | None:
    """pending|confirmed -> canceled."""
    return transition_action(
        action_id,
        expect_statuses=[STATUS_PENDING, STATUS_CONFIRMED],
        new_status=STATUS_CANCELED,
        fields=record_to_dict(record),
    )


def finish_action(action_id: str, record) -> dict | None:
    """confirmed -> executed|failed, carrying the execution result."""
    status = str(record_to_dict(record).get("status") or "")
    if status not in {STATUS_EXECUTED, STATUS_FAILED}:
        raise ValueError(f"Invalid terminal status: {status}")
    return transition_action(
        action_id,
        expect_statuses=[STATUS_CONFIRMED],
        new_status=status,
        fields=record_to_dict(record),
    )


def recover_interrupted_actions(reason: str) -> int:
    """Fail every confirmed-but-unfinished action; returns rows changed."""
    now = time.time()
    with session_scope() as session:
        result = session.execute(
            sql_update(PendingActionRecord)
            .where(PendingActionRecord.status == STATUS_CONFIRMED)
            .values(
                status=STATUS_FAILED,
                result_payload={
                    "execution_enabled": True,
                    "success": False,
                    "error": str(reason),
                    "interrupted": True,
                },
                updated_at=now,
                version=PendingActionRecord.version + 1,
            )
        )
        return int(result.rowcount or 0)


def fetch_action(action_id: str) -> dict | None:
    action_id = str(action_id or "")
    if not action_id:
        return None
    with session_scope() as session:
        row = session.get(PendingActionRecord, action_id)
        return _row_to_dict(row) if row is not None else None


def delete_action(action_id: str) -> bool:
    """Remove one mirrored action row.

    The domain never hard-deletes an action, so this exists for mirror
    maintenance (cleanup after a verification run, removing a bad import).
    """
    action_id = str(action_id or "")
    if not action_id:
        return False
    with session_scope() as session:
        result = session.execute(
            sql_delete(PendingActionRecord).where(
                PendingActionRecord.id == action_id
            )
        )
        return bool(result.rowcount)


def fetch_actions(
    *,
    session_id: str | None = None,
    status: str | None = None,
    limit: int = 200,
) -> list[dict]:
    statement = select(PendingActionRecord)
    if session_id:
        statement = statement.where(PendingActionRecord.session_id == session_id)
    if status:
        statement = statement.where(PendingActionRecord.status == status)
    statement = statement.order_by(
        PendingActionRecord.created_at.desc(),
        PendingActionRecord.id.desc(),
    )
    if limit and int(limit) > 0:
        statement = statement.limit(int(limit))

    with session_scope() as session:
        return [_row_to_dict(row) for row in session.execute(statement).scalars()]


def count_actions() -> int:
    with session_scope() as session:
        return int(
            session.execute(select(func.count(PendingActionRecord.id))).scalar() or 0
        )


__all__ = [
    "STATUS_CANCELED",
    "STATUS_CONFIRMED",
    "STATUS_EXECUTED",
    "STATUS_FAILED",
    "STATUS_PENDING",
    "cancel_action",
    "confirm_action",
    "count_actions",
    "delete_action",
    "fetch_action",
    "fetch_actions",
    "finish_action",
    "recover_interrupted_actions",
    "transition_action",
    "upsert_action",
]
