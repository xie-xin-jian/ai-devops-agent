"""create session, message, run and run snapshot tables

Revision ID: 0004_session_tables
Revises: 0003_automation_tables
Create Date: 2026-10-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0004_session_tables"
down_revision: Union[str, None] = "0003_automation_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("session_id", sa.String(length=120), primary_key=True),
        sa.Column("owner_id", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("target_id", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.Column("expires_at", sa.Float(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_sessions_owner_id", "sessions", ["owner_id"])
    op.create_index("ix_sessions_status", "sessions", ["status"])
    op.create_index("ix_sessions_updated_at", "sessions", ["updated_at"])
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])

    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("session_id", sa.String(length=120), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="user"),
        sa.Column(
            "content",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.UniqueConstraint("session_id", "seq", name="uq_messages_session_seq"),
    )
    op.create_index("ix_messages_session_id", "messages", ["session_id"])
    op.create_index("ix_messages_updated_at", "messages", ["updated_at"])
    op.create_index("ix_messages_session_seq", "messages", ["session_id", "seq"])

    op.create_table(
        "runs",
        sa.Column("run_id", sa.String(length=120), primary_key=True),
        sa.Column("session_id", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("owner_id", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="chat"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="running"),
        sa.Column("phase", sa.String(length=40), nullable=False, server_default="model"),
        sa.Column("user_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("safe_to_resume", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("active_tool", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("interruption_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("resume_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.Column("finished_at", sa.Float(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_runs_session_id", "runs", ["session_id"])
    op.create_index("ix_runs_owner_id", "runs", ["owner_id"])
    op.create_index("ix_runs_status", "runs", ["status"])
    op.create_index("ix_runs_updated_at", "runs", ["updated_at"])
    op.create_index("ix_runs_status_time", "runs", ["status", "updated_at"])
    op.create_index("ix_runs_session_time", "runs", ["session_id", "updated_at"])

    op.create_table(
        "run_snapshots",
        sa.Column(
            "run_id",
            sa.String(length=120),
            sa.ForeignKey("runs.run_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("session_id", sa.String(length=120), nullable=False, server_default=""),
        sa.Column(
            "messages",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
    )
    op.create_index("ix_run_snapshots_session_id", "run_snapshots", ["session_id"])
    op.create_index("ix_run_snapshots_updated_at", "run_snapshots", ["updated_at"])


def downgrade() -> None:
    op.drop_index("ix_run_snapshots_updated_at", table_name="run_snapshots")
    op.drop_index("ix_run_snapshots_session_id", table_name="run_snapshots")
    op.drop_table("run_snapshots")

    for index_name in (
        "ix_runs_session_time",
        "ix_runs_status_time",
        "ix_runs_updated_at",
        "ix_runs_status",
        "ix_runs_owner_id",
        "ix_runs_session_id",
    ):
        op.drop_index(index_name, table_name="runs")
    op.drop_table("runs")

    for index_name in (
        "ix_messages_session_seq",
        "ix_messages_updated_at",
        "ix_messages_session_id",
    ):
        op.drop_index(index_name, table_name="messages")
    op.drop_table("messages")

    for index_name in (
        "ix_sessions_expires_at",
        "ix_sessions_updated_at",
        "ix_sessions_status",
        "ix_sessions_owner_id",
    ):
        op.drop_index(index_name, table_name="sessions")
    op.drop_table("sessions")
