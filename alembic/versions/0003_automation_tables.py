"""create pending action, cron and background tables

Revision ID: 0003_automation_tables
Revises: 0002_domain_tables
Create Date: 2026-10-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0003_automation_tables"
down_revision: Union[str, None] = "0002_domain_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pending_actions",
        sa.Column("id", sa.String(length=80), primary_key=True),
        sa.Column("session_id", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("target_id", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("run_id", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("tool_use_id", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("owner_id", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("action_code", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("title", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("risk_level", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("agent_mode", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("source_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "steps",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("impact", sa.Text(), nullable=False, server_default=""),
        sa.Column("rollback_plan", sa.Text(), nullable=False, server_default=""),
        sa.Column("verification", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "result_payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.Column("confirmed_by", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("confirmed_at", sa.Float(), nullable=True),
        sa.Column("canceled_by", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("canceled_at", sa.Float(), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_pending_actions_session_id", "pending_actions", ["session_id"])
    op.create_index("ix_pending_actions_run_id", "pending_actions", ["run_id"])
    op.create_index("ix_pending_actions_tool_use_id", "pending_actions", ["tool_use_id"])
    op.create_index("ix_pending_actions_owner_id", "pending_actions", ["owner_id"])
    op.create_index("ix_pending_actions_status", "pending_actions", ["status"])
    op.create_index("ix_pending_actions_created_at", "pending_actions", ["created_at"])
    op.create_index("ix_pending_actions_updated_at", "pending_actions", ["updated_at"])
    op.create_index(
        "ix_pending_actions_status_time",
        "pending_actions",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_pending_actions_session_time",
        "pending_actions",
        ["session_id", "created_at"],
    )

    op.create_table(
        "cron_jobs",
        sa.Column("id", sa.String(length=80), primary_key=True),
        sa.Column("cron", sa.String(length=120), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("recurring", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("durable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.Column("last_fired_at", sa.Float(), nullable=True),
        sa.Column("fire_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_cron_jobs_enabled", "cron_jobs", ["enabled"])
    op.create_index("ix_cron_jobs_updated_at", "cron_jobs", ["updated_at"])

    op.create_table(
        "cron_logs",
        sa.Column("id", sa.String(length=160), primary_key=True),
        sa.Column("job_id", sa.String(length=80), nullable=False),
        sa.Column("cron", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("fired_at", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("fired_at_epoch", sa.Float(), nullable=False, server_default="0"),
        sa.Column("finished_at", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("output", sa.Text(), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("run_id", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("session_id", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("created_at", sa.Float(), nullable=False),
    )
    op.create_index("ix_cron_logs_job_id", "cron_logs", ["job_id"])
    op.create_index("ix_cron_logs_run_id", "cron_logs", ["run_id"])
    op.create_index("ix_cron_logs_fired_at_epoch", "cron_logs", ["fired_at_epoch"])
    op.create_index("ix_cron_logs_created_at", "cron_logs", ["created_at"])

    op.create_table(
        "background_tasks",
        sa.Column("id", sa.String(length=80), primary_key=True),
        sa.Column("tool_use_id", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("command", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="running"),
        sa.Column("run_id", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("parent_run_id", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("session_id", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("owner_id", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="background"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("interruption_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("output", sa.Text(), nullable=False, server_default=""),
        sa.Column("notified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_background_tasks_status", "background_tasks", ["status"])
    op.create_index("ix_background_tasks_run_id", "background_tasks", ["run_id"])
    op.create_index("ix_background_tasks_parent_run_id", "background_tasks", ["parent_run_id"])
    op.create_index("ix_background_tasks_session_id", "background_tasks", ["session_id"])
    op.create_index("ix_background_tasks_owner_id", "background_tasks", ["owner_id"])
    op.create_index("ix_background_tasks_updated_at", "background_tasks", ["updated_at"])
    op.create_index(
        "ix_background_tasks_status_time",
        "background_tasks",
        ["status", "updated_at"],
    )


def downgrade() -> None:
    for index_name in (
        "ix_background_tasks_status_time",
        "ix_background_tasks_updated_at",
        "ix_background_tasks_owner_id",
        "ix_background_tasks_session_id",
        "ix_background_tasks_parent_run_id",
        "ix_background_tasks_run_id",
        "ix_background_tasks_status",
    ):
        op.drop_index(index_name, table_name="background_tasks")
    op.drop_table("background_tasks")

    for index_name in (
        "ix_cron_logs_created_at",
        "ix_cron_logs_fired_at_epoch",
        "ix_cron_logs_run_id",
        "ix_cron_logs_job_id",
    ):
        op.drop_index(index_name, table_name="cron_logs")
    op.drop_table("cron_logs")

    op.drop_index("ix_cron_jobs_updated_at", table_name="cron_jobs")
    op.drop_index("ix_cron_jobs_enabled", table_name="cron_jobs")
    op.drop_table("cron_jobs")

    for index_name in (
        "ix_pending_actions_session_time",
        "ix_pending_actions_status_time",
        "ix_pending_actions_updated_at",
        "ix_pending_actions_created_at",
        "ix_pending_actions_status",
        "ix_pending_actions_owner_id",
        "ix_pending_actions_tool_use_id",
        "ix_pending_actions_run_id",
        "ix_pending_actions_session_id",
    ):
        op.drop_index(index_name, table_name="pending_actions")
    op.drop_table("pending_actions")
