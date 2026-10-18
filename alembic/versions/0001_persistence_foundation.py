"""create audit events and run usage tables

Revision ID: 0001_persistence_foundation
Revises:
Create Date: 2026-10-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0001_persistence_foundation"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("occurred_at", sa.Float(), nullable=False),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("result", sa.String(length=32), nullable=False, server_default="success"),
        sa.Column("severity", sa.String(length=32), nullable=False, server_default="info"),
        sa.Column("actor", sa.String(length=100), nullable=False, server_default="system"),
        sa.Column("session_id", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("run_id", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("action_id", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("action_code", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("tool_name", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("risk_level", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("correlation_id", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.Float(), nullable=False),
    )
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"])
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"])
    op.create_index("ix_audit_events_session_id", "audit_events", ["session_id"])
    op.create_index("ix_audit_events_run_id", "audit_events", ["run_id"])
    op.create_index("ix_audit_events_action_id", "audit_events", ["action_id"])
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])
    op.create_index("ix_audit_events_session_time", "audit_events", ["session_id", "occurred_at"])
    op.create_index("ix_audit_events_run_time", "audit_events", ["run_id", "occurred_at"])

    op.create_table(
        "run_usage",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("run_id", sa.String(length=120), nullable=False),
        sa.Column("session_id", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("turn", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("model_id", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost_cny", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.Float(), nullable=False),
    )
    op.create_index("ix_run_usage_run_id", "run_usage", ["run_id"])
    op.create_index("ix_run_usage_session_id", "run_usage", ["session_id"])
    op.create_index("ix_run_usage_created_at", "run_usage", ["created_at"])
    op.create_index("ix_run_usage_run_turn", "run_usage", ["run_id", "turn"])


def downgrade() -> None:
    op.drop_index("ix_run_usage_run_turn", table_name="run_usage")
    op.drop_index("ix_run_usage_created_at", table_name="run_usage")
    op.drop_index("ix_run_usage_session_id", table_name="run_usage")
    op.drop_index("ix_run_usage_run_id", table_name="run_usage")
    op.drop_table("run_usage")

    op.drop_index("ix_audit_events_run_time", table_name="audit_events")
    op.drop_index("ix_audit_events_session_time", table_name="audit_events")
    op.drop_index("ix_audit_events_created_at", table_name="audit_events")
    op.drop_index("ix_audit_events_action_id", table_name="audit_events")
    op.drop_index("ix_audit_events_run_id", table_name="audit_events")
    op.drop_index("ix_audit_events_session_id", table_name="audit_events")
    op.drop_index("ix_audit_events_event_type", table_name="audit_events")
    op.drop_index("ix_audit_events_occurred_at", table_name="audit_events")
    op.drop_table("audit_events")
