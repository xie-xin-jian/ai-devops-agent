"""PostgreSQL repository for long-term memory records."""

from __future__ import annotations

import time

from sqlalchemy import delete as sql_delete, func, select

from agent.persistence.database import session_scope
from agent.persistence.models import MemoryEntryRecord
from agent.persistence.repositories.common import (
    build_upsert_statement,
    record_to_dict,
    update_row_if_version,
    upsert_row,
)


MAX_ID_LENGTH = 64
MIRROR_CHUNK_SIZE = 200

_UPDATE_COLUMNS = (
    "content",
    "memory_type",
    "entity_type",
    "entity_key",
    "entity_value",
    "category",
    "tags",
    "scope",
    "owner_id",
    "session_id",
    "run_id",
    "source",
    "confidence",
    "importance",
    "status",
    "content_hash",
    "supersedes",
    "superseded_by",
    "created_at",
    "updated_at",
    "last_accessed_at",
    "access_count",
)


def _clip_list(value) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return [str(item) for item in value if str(item).strip()]


def _values(record: dict) -> dict:
    now = time.time()
    return {
        "id": str(record.get("id") or ""),
        "content": str(record.get("content") or ""),
        "memory_type": str(record.get("memory_type") or "semantic")[:32],
        "entity_type": str(record.get("entity_type") or "")[:60],
        "entity_key": str(record.get("entity_key") or "")[:200],
        "entity_value": str(record.get("entity_value") or ""),
        "category": str(record.get("category") or "general")[:120],
        "tags": _clip_list(record.get("tags")),
        "scope": str(record.get("scope") or "global")[:120],
        "owner_id": str(record.get("owner_id") or "")[:120],
        "session_id": str(record.get("session_id") or "")[:120],
        "run_id": str(record.get("run_id") or "")[:120],
        "source": str(record.get("source") or "agent")[:60],
        "confidence": float(record.get("confidence") or 0.0),
        "importance": int(record.get("importance") or 3),
        "status": str(record.get("status") or "active")[:32],
        "content_hash": str(record.get("content_hash") or "")[:64],
        "supersedes": _clip_list(record.get("supersedes")),
        "superseded_by": str(record.get("superseded_by") or "")[:64],
        "created_at": float(record.get("created_at") or now),
        "updated_at": float(record.get("updated_at") or now),
        "last_accessed_at": float(record.get("last_accessed_at") or 0.0),
        "access_count": max(0, int(record.get("access_count") or 0)),
        "version": 1,
    }


def _row_to_dict(row: MemoryEntryRecord) -> dict:
    return {
        "id": row.id,
        "content": row.content,
        "memory_type": row.memory_type,
        "entity_type": row.entity_type,
        "entity_key": row.entity_key,
        "entity_value": row.entity_value,
        "category": row.category,
        "tags": list(row.tags or []),
        "scope": row.scope,
        "owner_id": row.owner_id,
        "session_id": row.session_id,
        "run_id": row.run_id,
        "source": row.source,
        "confidence": row.confidence,
        "importance": row.importance,
        "status": row.status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "last_accessed_at": row.last_accessed_at,
        "access_count": row.access_count,
        "content_hash": row.content_hash,
        "version": row.version,
        "supersedes": list(row.supersedes or []),
        "superseded_by": row.superseded_by,
    }


def upsert_memory(
    record,
    *,
    expected_version: int | None = None,
    force: bool = False,
) -> bool:
    """Create or update one memory record."""
    values = _values(record_to_dict(record))
    if not values["id"] or len(values["id"]) > MAX_ID_LENGTH:
        return False

    with session_scope() as session:
        if expected_version is None:
            upsert_row(
                session,
                MemoryEntryRecord,
                values,
                conflict_columns=["id"],
                update_columns=_UPDATE_COLUMNS,
                force=force,
            )
            return True
        return update_row_if_version(
            session,
            MemoryEntryRecord,
            values["id"],
            int(expected_version),
            values,
        )


def upsert_memories(records, *, force: bool = False) -> int:
    """Mirror a whole memory list in one transaction.

    The JSON store rewrites its file as a whole, so the mirror keeps the
    same shape: one transaction per save, with rows sent in chunks so a
    large list costs a few round trips instead of one per record.
    """
    rows = []
    for record in records:
        values = _values(record_to_dict(record))
        if not values["id"] or len(values["id"]) > MAX_ID_LENGTH:
            continue
        rows.append(values)

    if not rows:
        return 0

    with session_scope() as session:
        dialect = session.get_bind().dialect.name
        for start in range(0, len(rows), MIRROR_CHUNK_SIZE):
            chunk = rows[start : start + MIRROR_CHUNK_SIZE]
            statement = build_upsert_statement(
                MemoryEntryRecord,
                chunk[0],
                dialect=dialect,
                conflict_columns=["id"],
                update_columns=_UPDATE_COLUMNS,
                force=force,
            )
            if statement is None:
                for values in chunk:
                    upsert_row(
                        session,
                        MemoryEntryRecord,
                        values,
                        conflict_columns=["id"],
                        update_columns=_UPDATE_COLUMNS,
                        force=force,
                    )
                continue
            session.execute(statement, chunk)
    return len(rows)


def delete_memory(memory_id: str) -> bool:
    memory_id = str(memory_id or "")
    if not memory_id:
        return False
    with session_scope() as session:
        result = session.execute(
            sql_delete(MemoryEntryRecord).where(MemoryEntryRecord.id == memory_id)
        )
        return bool(result.rowcount)


def fetch_memory(memory_id: str) -> dict | None:
    memory_id = str(memory_id or "")
    if not memory_id:
        return None
    with session_scope() as session:
        row = session.get(MemoryEntryRecord, memory_id)
        return _row_to_dict(row) if row is not None else None


def fetch_memories(
    *,
    scope: str | None = None,
    status: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    statement = select(MemoryEntryRecord)
    if scope:
        statement = statement.where(MemoryEntryRecord.scope == scope)
    if status:
        statement = statement.where(MemoryEntryRecord.status == status)
    statement = statement.order_by(MemoryEntryRecord.updated_at.desc())
    if limit is not None:
        statement = statement.limit(max(1, int(limit)))

    with session_scope() as session:
        return [_row_to_dict(row) for row in session.execute(statement).scalars()]


def count_memories() -> int:
    with session_scope() as session:
        return int(
            session.execute(select(func.count(MemoryEntryRecord.id))).scalar() or 0
        )


__all__ = [
    "count_memories",
    "delete_memory",
    "fetch_memories",
    "fetch_memory",
    "upsert_memories",
    "upsert_memory",
]
