"""create agent evaluation tables

Revision ID: 0005_eval_tables
Revises: 0004_session_tables
Create Date: 2026-10-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0005_eval_tables"
down_revision: Union[str, None] = "0004_session_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "eval_batches",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("suite", sa.String(length=64), nullable=False, server_default="smoke"),
        sa.Column("label", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("model_id", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("trials_per_case", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="running"),
        sa.Column("total_cases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("planned_trials", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "config",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("started_at", sa.Float(), nullable=True),
        sa.Column("finished_at", sa.Float(), nullable=True),
    )
    op.create_index("ix_eval_batches_suite", "eval_batches", ["suite"])
    op.create_index("ix_eval_batches_status", "eval_batches", ["status"])
    op.create_index("ix_eval_batches_created_at", "eval_batches", ["created_at"])

    op.create_table(
        "eval_trials",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "batch_id",
            sa.String(length=64),
            sa.ForeignKey("eval_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("case_id", sa.String(length=120), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="medium"),
        sa.Column("topic", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("trial_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="running"),
        sa.Column("run_id", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("session_id", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("final_answer", sa.Text(), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("tool_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_cny", sa.Float(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("approvals_requested", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("approvals_granted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "trajectory",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.UniqueConstraint(
            "batch_id",
            "case_id",
            "trial_no",
            name="uq_eval_trials_batch_case_trial",
        ),
    )
    op.create_index("ix_eval_trials_batch_id", "eval_trials", ["batch_id"])
    op.create_index("ix_eval_trials_case_id", "eval_trials", ["case_id"])
    op.create_index("ix_eval_trials_category", "eval_trials", ["category"])
    op.create_index("ix_eval_trials_status", "eval_trials", ["status"])
    op.create_index("ix_eval_trials_run_id", "eval_trials", ["run_id"])
    op.create_index("ix_eval_trials_created_at", "eval_trials", ["created_at"])
    op.create_index("ix_eval_trials_updated_at", "eval_trials", ["updated_at"])
    op.create_index(
        "ix_eval_trials_batch_category",
        "eval_trials",
        ["batch_id", "category"],
    )

    op.create_table(
        "eval_tool_calls",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "trial_id",
            sa.BigInteger(),
            sa.ForeignKey("eval_trials.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("batch_id", sa.String(length=64), nullable=False),
        sa.Column("case_id", sa.String(length=120), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool", sa.String(length=120), nullable=False, server_default=""),
        sa.Column(
            "arguments",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("output", sa.Text(), nullable=False, server_default=""),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.Float(), nullable=False),
    )
    op.create_index("ix_eval_tool_calls_trial_id", "eval_tool_calls", ["trial_id"])
    op.create_index("ix_eval_tool_calls_batch_id", "eval_tool_calls", ["batch_id"])
    op.create_index("ix_eval_tool_calls_case_id", "eval_tool_calls", ["case_id"])
    op.create_index("ix_eval_tool_calls_tool", "eval_tool_calls", ["tool"])

    op.create_table(
        "eval_scores",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "trial_id",
            sa.BigInteger(),
            sa.ForeignKey("eval_trials.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("batch_id", sa.String(length=64), nullable=False),
        sa.Column("case_id", sa.String(length=120), nullable=False),
        sa.Column("rule", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pass"),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "evidence",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.Float(), nullable=False),
    )
    op.create_index("ix_eval_scores_trial_id", "eval_scores", ["trial_id"])
    op.create_index("ix_eval_scores_batch_id", "eval_scores", ["batch_id"])
    op.create_index("ix_eval_scores_case_id", "eval_scores", ["case_id"])
    op.create_index("ix_eval_scores_rule", "eval_scores", ["rule"])
    op.create_index("ix_eval_scores_status", "eval_scores", ["status"])


def downgrade() -> None:
    for index_name in (
        "ix_eval_scores_status",
        "ix_eval_scores_rule",
        "ix_eval_scores_case_id",
        "ix_eval_scores_batch_id",
        "ix_eval_scores_trial_id",
    ):
        op.drop_index(index_name, table_name="eval_scores")
    op.drop_table("eval_scores")

    for index_name in (
        "ix_eval_tool_calls_tool",
        "ix_eval_tool_calls_case_id",
        "ix_eval_tool_calls_batch_id",
        "ix_eval_tool_calls_trial_id",
    ):
        op.drop_index(index_name, table_name="eval_tool_calls")
    op.drop_table("eval_tool_calls")

    for index_name in (
        "ix_eval_trials_batch_category",
        "ix_eval_trials_updated_at",
        "ix_eval_trials_created_at",
        "ix_eval_trials_run_id",
        "ix_eval_trials_status",
        "ix_eval_trials_category",
        "ix_eval_trials_case_id",
        "ix_eval_trials_batch_id",
    ):
        op.drop_index(index_name, table_name="eval_trials")
    op.drop_table("eval_trials")

    op.drop_index("ix_eval_batches_created_at", table_name="eval_batches")
    op.drop_index("ix_eval_batches_status", table_name="eval_batches")
    op.drop_index("ix_eval_batches_suite", table_name="eval_batches")
    op.drop_table("eval_batches")
