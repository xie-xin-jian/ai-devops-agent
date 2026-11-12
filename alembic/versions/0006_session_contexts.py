"""separate model context from complete session history

Revision ID: 0006_session_contexts
Revises: 0005_eval_tables
Create Date: 2026-11-12
"""

from __future__ import annotations

import hashlib
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0006_session_contexts"
down_revision: Union[str, None] = "0005_eval_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _content_hash(messages: list[dict]) -> str:
    payload = json.dumps(
        messages,
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def upgrade() -> None:
    op.create_table(
        "session_contexts",
        sa.Column(
            "session_id",
            sa.String(length=120),
            sa.ForeignKey(
                "sessions.session_id",
                ondelete="CASCADE",
            ),
            primary_key=True,
        ),
        sa.Column(
            "messages",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "message_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "content_hash",
            sa.String(length=64),
            nullable=False,
            server_default="",
        ),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.create_index(
        "ix_session_contexts_updated_at",
        "session_contexts",
        ["updated_at"],
    )

    # Existing sessions start with their current persisted messages as both
    # complete history and model context. Future compactions will mutate only
    # the context row.
    bind = op.get_bind()
    sessions = bind.execute(
        sa.text(
            "SELECT session_id, created_at, updated_at "
            "FROM sessions ORDER BY created_at"
        )
    ).mappings().all()
    for session_row in sessions:
        message_rows = bind.execute(
            sa.text(
                "SELECT role, content FROM messages "
                "WHERE session_id = :session_id ORDER BY seq"
            ),
            {"session_id": session_row["session_id"]},
        ).mappings().all()
        messages = []
        for message_row in message_rows:
            content = message_row["content"]
            if isinstance(content, str):
                try:
                    content = json.loads(content)
                except ValueError:
                    pass
            messages.append({
                "role": str(message_row["role"] or "user"),
                "content": content,
            })
        bind.execute(
            sa.text(
                "INSERT INTO session_contexts "
                "(session_id, messages, message_count, content_hash, "
                "created_at, updated_at, version) "
                "VALUES (:session_id, CAST(:messages AS JSONB), "
                ":message_count, :content_hash, :created_at, "
                ":updated_at, 1)"
            ),
            {
                "session_id": session_row["session_id"],
                "messages": json.dumps(messages, ensure_ascii=False),
                "message_count": len(messages),
                "content_hash": _content_hash(messages),
                "created_at": session_row["created_at"],
                "updated_at": session_row["updated_at"],
            },
        )


def downgrade() -> None:
    op.drop_index(
        "ix_session_contexts_updated_at",
        table_name="session_contexts",
    )
    op.drop_table("session_contexts")
