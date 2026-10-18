"""PostgreSQL repository for deployment targets."""

from __future__ import annotations

import time

from sqlalchemy import delete as sql_delete, func, select

from agent.persistence.database import session_scope
from agent.persistence.models import TargetRecord
from agent.persistence.repositories.common import (
    record_to_dict,
    update_row_if_version,
    upsert_row,
)


_UPDATE_COLUMNS = (
    "name",
    "root",
    "description",
    "service",
    "health_url",
    "deploy_command",
    "restart_command",
    "log_path",
    "created_at",
    "updated_at",
)


def _values(record: dict) -> dict:
    now = time.time()
    return {
        "id": str(record.get("id") or ""),
        "name": str(record.get("name") or "")[:200],
        "root": str(record.get("root") or ""),
        "description": str(record.get("description") or ""),
        "service": str(record.get("service") or "")[:120],
        "health_url": str(record.get("health_url") or ""),
        "deploy_command": str(record.get("deploy_command") or ""),
        "restart_command": str(record.get("restart_command") or ""),
        "log_path": str(record.get("log_path") or ""),
        "created_at": float(record.get("created_at") or now),
        "updated_at": float(record.get("updated_at") or now),
        "version": 1,
    }


def _row_to_dict(row: TargetRecord) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "root": row.root,
        "description": row.description,
        "service": row.service,
        "health_url": row.health_url,
        "deploy_command": row.deploy_command,
        "restart_command": row.restart_command,
        "log_path": row.log_path,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def upsert_target(
    record,
    *,
    expected_version: int | None = None,
    force: bool = False,
) -> bool:
    """Create or update one target. Returns False when the id is unusable."""
    values = _values(record_to_dict(record))
    if not values["id"]:
        return False

    with session_scope() as session:
        if expected_version is None:
            upsert_row(
                session,
                TargetRecord,
                values,
                conflict_columns=["id"],
                update_columns=_UPDATE_COLUMNS,
                force=force,
            )
            return True
        return update_row_if_version(
            session,
            TargetRecord,
            values["id"],
            int(expected_version),
            values,
        )


def delete_target(target_id: str) -> bool:
    target_id = str(target_id or "")
    if not target_id:
        return False
    with session_scope() as session:
        result = session.execute(
            sql_delete(TargetRecord).where(TargetRecord.id == target_id)
        )
        return bool(result.rowcount)


def fetch_target(target_id: str) -> dict | None:
    target_id = str(target_id or "")
    if not target_id:
        return None
    with session_scope() as session:
        row = session.get(TargetRecord, target_id)
        return _row_to_dict(row) if row is not None else None


def fetch_targets() -> list[dict]:
    with session_scope() as session:
        rows = session.execute(
            select(TargetRecord).order_by(TargetRecord.name)
        ).scalars()
        return [_row_to_dict(row) for row in rows]


def count_targets() -> int:
    with session_scope() as session:
        return int(session.execute(select(func.count(TargetRecord.id))).scalar() or 0)


__all__ = [
    "count_targets",
    "delete_target",
    "fetch_target",
    "fetch_targets",
    "upsert_target",
]
