"""SQLAlchemy models for the PostgreSQL persistence phases."""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


JSON_VALUE = JSON().with_variant(JSONB, "postgresql")
# SQLite only auto-increments a column typed exactly as INTEGER, so the
# BIGINT surrogate keys need a dialect variant to stay usable in tests.
BIGINT_PK = BigInteger().with_variant(Integer, "sqlite")


class Base(DeclarativeBase):
    pass


class AuditEventRecord(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    occurred_at: Mapped[float] = mapped_column(Float, index=True)
    event_type: Mapped[str] = mapped_column(String(120), index=True)
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[str] = mapped_column(String(32), default="success")
    severity: Mapped[str] = mapped_column(String(32), default="info")
    actor: Mapped[str] = mapped_column(String(100), default="system")
    session_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    run_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    action_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    action_code: Mapped[str] = mapped_column(String(120), default="")
    tool_name: Mapped[str] = mapped_column(String(120), default="")
    risk_level: Mapped[str] = mapped_column(String(32), default="")
    correlation_id: Mapped[str] = mapped_column(String(120), default="")
    payload: Mapped[dict] = mapped_column(JSON_VALUE, default=dict)
    event_metadata: Mapped[dict] = mapped_column(
        "metadata",
        JSON_VALUE,
        default=dict,
    )
    created_at: Mapped[float] = mapped_column(
        Float,
        default=time.time,
        index=True,
    )

    __table_args__ = (
        Index("ix_audit_events_session_time", "session_id", "occurred_at"),
        Index("ix_audit_events_run_time", "run_id", "occurred_at"),
    )


class RunUsageRecord(Base):
    __tablename__ = "run_usage"

    id: Mapped[int] = mapped_column(
        BIGINT_PK,
        primary_key=True,
        autoincrement=True,
    )
    run_id: Mapped[str] = mapped_column(String(120), index=True)
    session_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    turn: Mapped[int] = mapped_column(Integer, default=0)
    model_id: Mapped[str] = mapped_column(String(200), default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_cny: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[float] = mapped_column(
        Float,
        default=time.time,
        index=True,
    )

    __table_args__ = (
        Index("ix_run_usage_run_turn", "run_id", "turn"),
    )


class TargetRecord(Base):
    """Deployment target configuration.

    ``version`` is a monotonic revision counter maintained by the database.
    It is not part of the JSON record; it exists so the PG-native read path
    can detect concurrent updates instead of silently overwriting them.
    """

    __tablename__ = "targets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    root: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    service: Mapped[str] = mapped_column(String(120), default="")
    health_url: Mapped[str] = mapped_column(Text, default="")
    deploy_command: Mapped[str] = mapped_column(Text, default="")
    restart_command: Mapped[str] = mapped_column(Text, default="")
    log_path: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[float] = mapped_column(Float, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class TaskRecord(Base):
    """Task metadata; dependencies live in ``task_dependencies``."""

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    subject: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    owner: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
        index=True,
    )
    run_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    source: Mapped[str] = mapped_column(String(32), default="task")
    priority: Mapped[str] = mapped_column(String(16), default="medium")
    result: Mapped[str] = mapped_column(Text, default="")
    task_metadata: Mapped[dict] = mapped_column(
        "metadata",
        JSON_VALUE,
        default=dict,
    )
    created_at: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[float] = mapped_column(Float, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)

    __table_args__ = (
        Index("ix_tasks_status_priority", "status", "priority"),
    )


class TaskDependencyRecord(Base):
    """Edge of the task dependency graph.

    ``depends_on_id`` intentionally has no foreign key: the JSON store allows
    a task to declare a dependency that does not exist yet, and ``can_start``
    reports it as a missing dependency instead of failing the write.
    """

    __tablename__ = "task_dependencies"

    task_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    depends_on_id: Mapped[str] = mapped_column(
        String(80),
        primary_key=True,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class MemoryEntryRecord(Base):
    """Long-term memory record.

    Named ``MemoryEntryRecord`` to avoid colliding with the domain model
    ``agent.memory.models.MemoryRecord``.
    """

    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    content: Mapped[str] = mapped_column(Text)
    memory_type: Mapped[str] = mapped_column(
        String(32),
        default="semantic",
        index=True,
    )
    entity_type: Mapped[str] = mapped_column(String(60), default="")
    entity_key: Mapped[str] = mapped_column(String(200), default="", index=True)
    entity_value: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(120), default="general")
    tags: Mapped[list] = mapped_column(JSON_VALUE, default=list)
    scope: Mapped[str] = mapped_column(String(120), default="global", index=True)
    owner_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    session_id: Mapped[str] = mapped_column(String(120), default="")
    run_id: Mapped[str] = mapped_column(String(120), default="")
    source: Mapped[str] = mapped_column(String(60), default="agent")
    confidence: Mapped[float] = mapped_column(Float, default=0.8)
    importance: Mapped[int] = mapped_column(Integer, default=3)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    content_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    supersedes: Mapped[list] = mapped_column(JSON_VALUE, default=list)
    superseded_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[float] = mapped_column(Float, index=True)
    last_accessed_at: Mapped[float] = mapped_column(Float, default=0.0)
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)

    __table_args__ = (
        Index("ix_memories_scope_status", "scope", "status"),
        Index("ix_memories_scope_hash", "scope", "content_hash"),
    )


class PendingActionRecord(Base):
    """Human-approval request created for a governed tool call."""

    __tablename__ = "pending_actions"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    target_id: Mapped[str] = mapped_column(String(120), default="")
    run_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    tool_use_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    owner_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    action_code: Mapped[str] = mapped_column(String(160), default="")
    title: Mapped[str] = mapped_column(String(300), default="")
    risk_level: Mapped[str] = mapped_column(String(32), default="")
    agent_mode: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    source_message: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSON_VALUE, default=dict)
    steps: Mapped[list] = mapped_column(JSON_VALUE, default=list)
    impact: Mapped[str] = mapped_column(Text, default="")
    rollback_plan: Mapped[str] = mapped_column(Text, default="")
    verification: Mapped[str] = mapped_column(Text, default="")
    result_payload: Mapped[dict] = mapped_column(JSON_VALUE, default=dict)
    created_at: Mapped[float] = mapped_column(Float, index=True)
    updated_at: Mapped[float] = mapped_column(Float, index=True)
    confirmed_by: Mapped[str] = mapped_column(String(120), default="")
    confirmed_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    canceled_by: Mapped[str] = mapped_column(String(120), default="")
    canceled_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    cancel_reason: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)

    __table_args__ = (
        Index("ix_pending_actions_status_time", "status", "created_at"),
        Index("ix_pending_actions_session_time", "session_id", "created_at"),
    )


class CronJobRecord(Base):
    """Scheduled agent prompt.

    ``last_fired_at`` is the cross-process dedupe key: a scheduler claims a
    minute by writing it inside the same transaction that locks the row.
    """

    __tablename__ = "cron_jobs"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    cron_expr: Mapped[str] = mapped_column("cron", String(120))
    prompt: Mapped[str] = mapped_column(Text)
    recurring: Mapped[bool] = mapped_column(Boolean, default=True)
    durable: Mapped[bool] = mapped_column(Boolean, default=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[float] = mapped_column(Float, index=True)
    last_fired_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    fire_count: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)


class CronLogRecord(Base):
    """One Cron execution result."""

    __tablename__ = "cron_logs"

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(80), index=True)
    cron_expr: Mapped[str] = mapped_column("cron", String(120), default="")
    prompt: Mapped[str] = mapped_column(Text, default="")
    fired_at: Mapped[str] = mapped_column(String(40), default="")
    fired_at_epoch: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    finished_at: Mapped[str] = mapped_column(String(40), default="")
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    output: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    run_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    session_id: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[float] = mapped_column(Float, index=True)


class BackgroundTaskRecord(Base):
    """Long-running command detached from the Agent loop."""

    __tablename__ = "background_tasks"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    tool_use_id: Mapped[str] = mapped_column(String(120), default="")
    command: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    run_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    parent_run_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    session_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    owner_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    source: Mapped[str] = mapped_column(String(32), default="background")
    error: Mapped[str] = mapped_column(Text, default="")
    interruption_reason: Mapped[str] = mapped_column(Text, default="")
    output: Mapped[str] = mapped_column(Text, default="")
    notified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[float] = mapped_column(Float, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)

    __table_args__ = (
        Index("ix_background_tasks_status_time", "status", "updated_at"),
    )


class SessionRecord(Base):
    """Chat session metadata.

    ``expires_at`` records the TTL policy at write time so a reader can find
    stale sessions without knowing the running manager's configuration.
    """

    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    target_id: Mapped[str] = mapped_column(String(120), default="")
    title: Mapped[str] = mapped_column(String(200), default="")
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[float] = mapped_column(Float, index=True)
    expires_at: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class MessageRecord(Base):
    """One Agent message inside a session.

    ``seq`` is the position in the conversation; the unique constraint on
    ``(session_id, seq)`` is what guarantees ordering survives a rewrite of
    the message list (context compaction, message repair).
    """

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(
        BIGINT_PK,
        primary_key=True,
        autoincrement=True,
    )
    session_id: Mapped[str] = mapped_column(String(120), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(32), default="user")
    content: Mapped[Any] = mapped_column(JSON_VALUE, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[float] = mapped_column(Float, index=True)

    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "seq",
            name="uq_messages_session_seq",
        ),
        Index("ix_messages_session_seq", "session_id", "seq"),
    )


class RunRecord(Base):
    """One Agent run with its resume metadata."""

    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    owner_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    source: Mapped[str] = mapped_column(String(32), default="chat")
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    phase: Mapped[str] = mapped_column(String(40), default="model")
    user_message: Mapped[str] = mapped_column(Text, default="")
    safe_to_resume: Mapped[bool] = mapped_column(Boolean, default=True)
    active_tool: Mapped[str] = mapped_column(String(120), default="")
    interruption_reason: Mapped[str] = mapped_column(Text, default="")
    resume_count: Mapped[int] = mapped_column(Integer, default=0)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[float] = mapped_column(Float, index=True)
    finished_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)

    __table_args__ = (
        Index("ix_runs_status_time", "status", "updated_at"),
        Index("ix_runs_session_time", "session_id", "updated_at"),
    )


class RunSnapshotRecord(Base):
    """Message snapshot captured at a run's safe point.

    Kept as one JSONB document per run: it is read and written as a whole,
    and the plan explicitly keeps large snapshots out of the hot tables.
    """

    __tablename__ = "run_snapshots"

    run_id: Mapped[str] = mapped_column(
        String(120),
        ForeignKey("runs.run_id", ondelete="CASCADE"),
        primary_key=True,
    )
    session_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    messages: Mapped[list] = mapped_column(JSON_VALUE, default=list)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[float] = mapped_column(Float, index=True)


class EvalBatchRecord(Base):
    """One evaluation run: a suite, a version label and a model."""

    __tablename__ = "eval_batches"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    suite: Mapped[str] = mapped_column(String(64), default="smoke", index=True)
    label: Mapped[str] = mapped_column(String(120), default="")
    model_id: Mapped[str] = mapped_column(String(200), default="")
    trials_per_case: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(24), default="running", index=True)
    total_cases: Mapped[int] = mapped_column(Integer, default=0)
    planned_trials: Mapped[int] = mapped_column(Integer, default=0)
    config: Mapped[dict] = mapped_column(JSON_VALUE, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[float] = mapped_column(Float, index=True)
    started_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    finished_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class EvalTrialRecord(Base):
    """One case run once (one trial of one case inside a batch)."""

    __tablename__ = "eval_trials"

    id: Mapped[int] = mapped_column(
        BIGINT_PK,
        primary_key=True,
        autoincrement=True,
    )
    batch_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("eval_batches.id", ondelete="CASCADE"),
        index=True,
    )
    case_id: Mapped[str] = mapped_column(String(120), index=True)
    category: Mapped[str] = mapped_column(String(32), default="", index=True)
    severity: Mapped[str] = mapped_column(String(16), default="medium")
    topic: Mapped[str] = mapped_column(String(64), default="")
    trial_no: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(24), default="running", index=True)
    run_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    session_id: Mapped[str] = mapped_column(String(120), default="")
    final_answer: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_cny: Mapped[float] = mapped_column(Float, default=0.0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    approvals_requested: Mapped[int] = mapped_column(Integer, default=0)
    approvals_granted: Mapped[int] = mapped_column(Integer, default=0)
    trajectory: Mapped[list] = mapped_column(JSON_VALUE, default=list)
    created_at: Mapped[float] = mapped_column(Float, index=True)
    updated_at: Mapped[float] = mapped_column(Float, index=True)

    __table_args__ = (
        UniqueConstraint(
            "batch_id",
            "case_id",
            "trial_no",
            name="uq_eval_trials_batch_case_trial",
        ),
        Index("ix_eval_trials_batch_category", "batch_id", "category"),
    )


class EvalToolCallRecord(Base):
    """One tool call inside a trial.

    Kept as its own table (not only inside ``eval_trials.trajectory``) so
    questions like "which tool fails most often" are a single GROUP BY.
    """

    __tablename__ = "eval_tool_calls"

    id: Mapped[int] = mapped_column(
        BIGINT_PK,
        primary_key=True,
        autoincrement=True,
    )
    trial_id: Mapped[int] = mapped_column(
        BIGINT_PK,
        ForeignKey("eval_trials.id", ondelete="CASCADE"),
        index=True,
    )
    batch_id: Mapped[str] = mapped_column(String(64), index=True)
    case_id: Mapped[str] = mapped_column(String(120), index=True)
    step: Mapped[int] = mapped_column(Integer, default=0)
    tool: Mapped[str] = mapped_column(String(120), default="", index=True)
    arguments: Mapped[dict] = mapped_column(JSON_VALUE, default=dict)
    output: Mapped[str] = mapped_column(Text, default="")
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[float] = mapped_column(Float)


class EvalScoreRecord(Base):
    """One rule result for one trial."""

    __tablename__ = "eval_scores"

    id: Mapped[int] = mapped_column(
        BIGINT_PK,
        primary_key=True,
        autoincrement=True,
    )
    trial_id: Mapped[int] = mapped_column(
        BIGINT_PK,
        ForeignKey("eval_trials.id", ondelete="CASCADE"),
        index=True,
    )
    batch_id: Mapped[str] = mapped_column(String(64), index=True)
    case_id: Mapped[str] = mapped_column(String(120), index=True)
    rule: Mapped[str] = mapped_column(String(64), default="", index=True)
    status: Mapped[str] = mapped_column(String(16), default="pass", index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    detail: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[dict] = mapped_column(JSON_VALUE, default=dict)
    created_at: Mapped[float] = mapped_column(Float)


__all__ = [
    "AuditEventRecord",
    "BackgroundTaskRecord",
    "Base",
    "CronJobRecord",
    "CronLogRecord",
    "EvalBatchRecord",
    "EvalScoreRecord",
    "EvalToolCallRecord",
    "EvalTrialRecord",
    "MemoryEntryRecord",
    "MessageRecord",
    "PendingActionRecord",
    "RunRecord",
    "RunSnapshotRecord",
    "RunUsageRecord",
    "SessionRecord",
    "TargetRecord",
    "TaskDependencyRecord",
    "TaskRecord",
]
