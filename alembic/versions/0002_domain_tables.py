"""create target, task, dependency and memory tables

Revision ID: 0002_domain_tables
Revises: 0001_persistence_foundation
Create Date: 2026-10-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0002_domain_tables"
down_revision: Union[str, None] = "0001_persistence_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "targets",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("root", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("service", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("health_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("deploy_command", sa.Text(), nullable=False, server_default=""),
        sa.Column("restart_command", sa.Text(), nullable=False, server_default=""),
        sa.Column("log_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_targets_name", "targets", ["name"])
    op.create_index("ix_targets_updated_at", "targets", ["updated_at"])

    op.create_table(
        "tasks",
        sa.Column("id", sa.String(length=80), primary_key=True),
        sa.Column("subject", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("owner", sa.String(length=120), nullable=True),
        sa.Column("run_id", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="task"),
        sa.Column("priority", sa.String(length=16), nullable=False, server_default="medium"),
        sa.Column("result", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_tasks_status", "tasks", ["status"])
    op.create_index("ix_tasks_owner", "tasks", ["owner"])
    op.create_index("ix_tasks_run_id", "tasks", ["run_id"])
    op.create_index("ix_tasks_updated_at", "tasks", ["updated_at"])
    op.create_index("ix_tasks_status_priority", "tasks", ["status", "priority"])

    op.create_table(
        "task_dependencies",
        sa.Column(
            "task_id",
            sa.String(length=80),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("depends_on_id", sa.String(length=80), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.Float(), nullable=False),
    )
    op.create_index(
        "ix_task_dependencies_depends_on_id",
        "task_dependencies",
        ["depends_on_id"],
    )

    op.create_table(
        "memories",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("memory_type", sa.String(length=32), nullable=False, server_default="semantic"),
        sa.Column("entity_type", sa.String(length=60), nullable=False, server_default=""),
        sa.Column("entity_key", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("entity_value", sa.Text(), nullable=False, server_default=""),
        sa.Column("category", sa.String(length=120), nullable=False, server_default="general"),
        sa.Column(
            "tags",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("scope", sa.String(length=120), nullable=False, server_default="global"),
        sa.Column("owner_id", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("session_id", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("run_id", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=60), nullable=False, server_default="agent"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.8"),
        sa.Column("importance", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("content_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column(
            "supersedes",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("superseded_by", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.Column("last_accessed_at", sa.Float(), nullable=False, server_default="0"),
        sa.Column("access_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_memories_memory_type", "memories", ["memory_type"])
    op.create_index("ix_memories_entity_key", "memories", ["entity_key"])
    op.create_index("ix_memories_scope", "memories", ["scope"])
    op.create_index("ix_memories_owner_id", "memories", ["owner_id"])
    op.create_index("ix_memories_status", "memories", ["status"])
    op.create_index("ix_memories_content_hash", "memories", ["content_hash"])
    op.create_index("ix_memories_updated_at", "memories", ["updated_at"])
    op.create_index("ix_memories_scope_status", "memories", ["scope", "status"])
    op.create_index("ix_memories_scope_hash", "memories", ["scope", "content_hash"])


def downgrade() -> None:
    for index_name in (
        "ix_memories_scope_hash",
        "ix_memories_scope_status",
        "ix_memories_updated_at",
        "ix_memories_content_hash",
        "ix_memories_status",
        "ix_memories_owner_id",
        "ix_memories_scope",
        "ix_memories_entity_key",
        "ix_memories_memory_type",
    ):
        op.drop_index(index_name, table_name="memories")
    op.drop_table("memories")

    op.drop_index(
        "ix_task_dependencies_depends_on_id",
        table_name="task_dependencies",
    )
    op.drop_table("task_dependencies")

    for index_name in (
        "ix_tasks_status_priority",
        "ix_tasks_updated_at",
        "ix_tasks_run_id",
        "ix_tasks_owner",
        "ix_tasks_status",
    ):
        op.drop_index(index_name, table_name="tasks")
    op.drop_table("tasks")

    op.drop_index("ix_targets_updated_at", table_name="targets")
    op.drop_index("ix_targets_name", table_name="targets")
    op.drop_table("targets")
