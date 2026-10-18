from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

import agent.platform.config as app_config
from agent.persistence.models import (
    AuditEventRecord,
    Base,
    BackgroundTaskRecord,
    CronJobRecord,
    CronLogRecord,
    EvalBatchRecord,
    EvalScoreRecord,
    EvalToolCallRecord,
    EvalTrialRecord,
    MemoryEntryRecord,
    MessageRecord,
    PendingActionRecord,
    RunRecord,
    RunSnapshotRecord,
    RunUsageRecord,
    SessionRecord,
    TargetRecord,
    TaskDependencyRecord,
    TaskRecord,
)


_ = (
    AuditEventRecord,
    BackgroundTaskRecord,
    CronJobRecord,
    CronLogRecord,
    EvalBatchRecord,
    EvalScoreRecord,
    EvalToolCallRecord,
    EvalTrialRecord,
    MemoryEntryRecord,
    MessageRecord,
    PendingActionRecord,
    RunRecord,
    RunSnapshotRecord,
    RunUsageRecord,
    SessionRecord,
    TargetRecord,
    TaskDependencyRecord,
    TaskRecord,
)
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

_migration_url = os.environ.get("ALEMBIC_DATABASE_URL", "").strip()
_migration_url = _migration_url or app_config.DATABASE_URL

if not _migration_url:
    raise RuntimeError("DATABASE_URL is required to run migrations")

config.set_main_option("sqlalchemy.url", _migration_url)
target_url = _migration_url
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=target_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
