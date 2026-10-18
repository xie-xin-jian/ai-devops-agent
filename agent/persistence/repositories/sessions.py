"""PostgreSQL repository for sessions and their message rows."""

from __future__ import annotations

import hashlib
import json
import time

from sqlalchemy import (
    delete as sql_delete,
    func,
    or_,
    select,
    update as sql_update,
)

from agent.persistence.database import session_scope
from agent.persistence.models import MessageRecord, SessionRecord
from agent.persistence.repositories.common import (
    record_to_dict,
    upsert_row,
)


DEFAULT_SESSION_TTL_SECONDS = 2 * 60 * 60

_UPDATE_COLUMNS = (
    "owner_id",
    "status",
    "target_id",
    "title",
    "message_count",
    "created_at",
    "updated_at",
    "expires_at",
)

_MESSAGE_UPDATE_COLUMNS = (
    "role",
    "content",
    "content_hash",
    "updated_at",
)


def content_hash(value) -> str:
    """Stable hash of one message content payload."""
    try:
        serialized = json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )
    except (TypeError, ValueError):
        serialized = str(value)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _normalize_message(message) -> dict:
    if not isinstance(message, dict):
        return {"role": "user", "content": ""}
    return {
        "role": str(message.get("role") or "user")[:32],
        "content": message.get("content", ""),
    }


def normalize_messages(messages) -> list[dict]:
    return [
        _normalize_message(message)
        for message in (messages or [])
        if isinstance(message, dict)
    ]


def _session_values(record: dict, *, ttl_seconds: float | None) -> dict:
    now = time.time()
    updated_at = float(record.get("updated_at") or now)
    ttl = float(ttl_seconds or DEFAULT_SESSION_TTL_SECONDS)
    return {
        "session_id": str(record.get("session_id") or ""),
        "owner_id": str(record.get("owner_id") or "")[:120],
        "status": str(record.get("status") or "active")[:32],
        "target_id": str(record.get("target_id") or "")[:120],
        "title": str(record.get("title") or "")[:200],
        "message_count": int(record.get("message_count") or 0),
        "created_at": float(record.get("created_at") or now),
        "updated_at": updated_at,
        "expires_at": updated_at + ttl,
        "version": 1,
    }


def _session_to_dict(row: SessionRecord) -> dict:
    return {
        "session_id": row.session_id,
        "owner_id": row.owner_id,
        "status": row.status,
        "target_id": row.target_id,
        "title": row.title,
        "message_count": row.message_count,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "expires_at": row.expires_at,
        "version": row.version,
    }


def _sync_messages(session, session_id: str, messages: list[dict]) -> int:
    """Rewrite the message rows for one session, touching only changes.

    The JSON store keeps the whole message list and rewrites it on every
    save (context compaction can rewrite history, not just append), so the
    mirror compares content hashes per ``seq`` and only writes the rows that
    actually differ.
    """
    existing = dict(
        session.execute(
            select(MessageRecord.seq, MessageRecord.content_hash).where(
                MessageRecord.session_id == session_id
            )
        ).all()
    )
    now = time.time()
    incoming = []
    for seq, message in enumerate(messages):
        normalized = _normalize_message(message)
        incoming.append((
            seq,
            normalized["role"],
            normalized["content"],
            content_hash(normalized["content"]),
        ))

    stale = [seq for seq in existing if seq >= len(incoming)]
    if stale:
        session.execute(
            sql_delete(MessageRecord).where(
                MessageRecord.session_id == session_id,
                MessageRecord.seq.in_(stale),
            )
        )

    written = 0
    for seq, role, content, digest in incoming:
        if existing.get(seq) == digest:
            continue
        upsert_row(
            session,
            MessageRecord,
            {
                "session_id": session_id,
                "seq": seq,
                "role": role,
                "content": content,
                "content_hash": digest,
                "created_at": now,
                "updated_at": now,
            },
            conflict_columns=["session_id", "seq"],
            update_columns=_MESSAGE_UPDATE_COLUMNS,
        )
        written += 1
    return written


def upsert_session(
    record,
    *,
    ttl_seconds: float | None = None,
    force: bool = False,
) -> bool:
    """Mirror a session record plus its message rows."""
    data = record_to_dict(record)
    messages = normalize_messages(data.get("messages"))
    data = {**data, "message_count": len(messages)}
    values = _session_values(data, ttl_seconds=ttl_seconds)
    if not values["session_id"] or len(values["session_id"]) > 120:
        return False

    with session_scope() as session:
        upsert_row(
            session,
            SessionRecord,
            values,
            conflict_columns=["session_id"],
            update_columns=_UPDATE_COLUMNS,
            force=force,
        )
        _sync_messages(session, values["session_id"], messages)
    return True


def rename_session(session_id: str, title: str) -> bool:
    """Mirror a title change without touching ``updated_at``.

    Sidebar ordering must not change just because a session was renamed,
    which is why this is a targeted UPDATE instead of a full upsert.
    """
    session_id = str(session_id or "")
    if not session_id:
        return False
    with session_scope() as session:
        result = session.execute(
            sql_update(SessionRecord)
            .where(SessionRecord.session_id == session_id)
            .values(
                title=str(title or "")[:200],
                version=SessionRecord.version + 1,
            )
        )
        return bool(result.rowcount)


def delete_session(session_id: str) -> bool:
    session_id = str(session_id or "")
    if not session_id:
        return False
    with session_scope() as session:
        session.execute(
            sql_delete(MessageRecord).where(
                MessageRecord.session_id == session_id
            )
        )
        result = session.execute(
            sql_delete(SessionRecord).where(
                SessionRecord.session_id == session_id
            )
        )
        return bool(result.rowcount)


def fetch_messages(session_id: str) -> list[dict]:
    with session_scope() as session:
        rows = session.execute(
            select(MessageRecord)
            .where(MessageRecord.session_id == str(session_id))
            .order_by(MessageRecord.seq)
        ).scalars()
        return [
            {"role": row.role, "content": row.content}
            for row in rows
        ]


def first_user_message(session_id: str):
    """Content of the earliest user message, or ``None``.

    The sidebar derives a session title from it, so a list read needs this one
    message even when it deliberately skips the rest of the history.
    """
    session_id = str(session_id or "")
    if not session_id:
        return None
    with session_scope() as session:
        return session.execute(
            select(MessageRecord.content)
            .where(
                MessageRecord.session_id == session_id,
                MessageRecord.role == "user",
            )
            .order_by(MessageRecord.seq)
            .limit(1)
        ).scalar()


def fetch_session(session_id: str, *, include_messages: bool = True) -> dict | None:
    session_id = str(session_id or "")
    if not session_id:
        return None
    with session_scope() as session:
        row = session.get(SessionRecord, session_id)
        if row is None:
            return None
        record = _session_to_dict(row)
    if include_messages:
        record["messages"] = fetch_messages(session_id)
    return record


def fetch_sessions(
    *,
    owner_id: str | None = None,
    include_messages: bool = False,
    limit: int = 500,
) -> list[dict]:
    statement = select(SessionRecord)
    if owner_id:
        # Matches the local store: sessions without an owner stay visible.
        statement = statement.where(
            or_(
                SessionRecord.owner_id == str(owner_id),
                SessionRecord.owner_id == "",
            )
        )
    statement = statement.order_by(
        SessionRecord.updated_at.desc(),
        SessionRecord.session_id.desc(),
    ).limit(max(1, int(limit)))

    with session_scope() as session:
        records = [_session_to_dict(row) for row in session.execute(statement).scalars()]
        if not include_messages:
            for record in records:
                record["first_user_message"] = first_user_message(
                    record["session_id"]
                )
            return records
        for record in records:
            record["messages"] = [
                {"role": row.role, "content": row.content}
                for row in session.execute(
                    select(MessageRecord)
                    .where(MessageRecord.session_id == record["session_id"])
                    .order_by(MessageRecord.seq)
                ).scalars()
            ]
        return records


def count_sessions() -> int:
    with session_scope() as session:
        return int(
            session.execute(select(func.count(SessionRecord.session_id))).scalar() or 0
        )


def count_messages(session_id: str | None = None) -> int:
    statement = select(func.count(MessageRecord.id))
    if session_id:
        statement = statement.where(
            MessageRecord.session_id == str(session_id)
        )
    with session_scope() as session:
        return int(session.execute(statement).scalar() or 0)


__all__ = [
    "DEFAULT_SESSION_TTL_SECONDS",
    "content_hash",
    "count_messages",
    "count_sessions",
    "delete_session",
    "fetch_messages",
    "fetch_session",
    "fetch_sessions",
    "first_user_message",
    "normalize_messages",
    "rename_session",
    "upsert_session",
]
