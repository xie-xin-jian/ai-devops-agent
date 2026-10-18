"""Integration tests against a live PostgreSQL instance.

They are skipped unless ``PERSISTENCE_TEST_DATABASE_URL`` points at a
database that already has the Alembic migrations applied:

    docker compose up -d postgres
    alembic upgrade head
    $env:PERSISTENCE_TEST_DATABASE_URL="postgresql+psycopg://ai_devops:change-me@127.0.0.1:5432/ai_devops"
    python -m pytest tests/test_persistence_pg_integration.py -q

Rows created here use a ``pgtest_`` id prefix and are removed afterwards.
"""

from __future__ import annotations

import os
import threading
import time
import uuid

import pytest
import sqlalchemy

import agent.platform.config as config
from agent.persistence import database, writer
from agent.persistence.models import (
    BackgroundTaskRecord,
    CronJobRecord,
    CronLogRecord,
    MemoryEntryRecord,
    MessageRecord,
    PendingActionRecord,
    RunRecord,
    RunSnapshotRecord,
    SessionRecord,
    TargetRecord,
    TaskDependencyRecord,
    TaskRecord,
)
from agent.persistence.repositories import actions as action_repo
from agent.persistence.repositories import background as background_repo
from agent.persistence.repositories import cron as cron_repo
from agent.persistence.repositories import memories as memory_repo
from agent.persistence.repositories import runs as run_repo
from agent.persistence.repositories import sessions as session_repo
from agent.persistence.repositories import targets as target_repo
from agent.persistence.repositories import tasks as task_repo


DATABASE_URL = os.environ.get("PERSISTENCE_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="set PERSISTENCE_TEST_DATABASE_URL to run PostgreSQL integration tests",
)


@pytest.fixture
def pg(monkeypatch):
    engine = sqlalchemy.create_engine(DATABASE_URL, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(sqlalchemy.text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - environment dependent
        engine.dispose()
        pytest.skip(f"PostgreSQL not reachable: {exc}")

    inspector = sqlalchemy.inspect(engine)
    missing = [
        table
        for table in (
            "targets",
            "tasks",
            "task_dependencies",
            "memories",
            "pending_actions",
            "cron_jobs",
            "cron_logs",
            "background_tasks",
            "sessions",
            "messages",
            "runs",
            "run_snapshots",
        )
        if not inspector.has_table(table)
    ]
    if missing:
        engine.dispose()
        pytest.skip(f"run 'alembic upgrade head' first, missing: {missing}")

    monkeypatch.setattr(config, "PERSISTENCE_BACKEND", "dual")
    monkeypatch.setattr(config, "DATABASE_URL", DATABASE_URL)
    monkeypatch.setattr(database, "_engine", engine)
    monkeypatch.setattr(database, "_session_factory", None)
    yield engine
    database.dispose_engine()
    monkeypatch.setattr(database, "_engine", None)
    monkeypatch.setattr(database, "_session_factory", None)


def _cleanup(
    engine,
    *,
    target_ids=(),
    task_ids=(),
    memory_ids=(),
    action_ids=(),
    cron_job_ids=(),
    background_ids=(),
    session_ids=(),
    run_ids=(),
):
    with engine.begin() as connection:
        if run_ids:
            connection.execute(
                sqlalchemy.delete(RunSnapshotRecord).where(
                    RunSnapshotRecord.run_id.in_(list(run_ids))
                )
            )
            connection.execute(
                sqlalchemy.delete(RunRecord).where(
                    RunRecord.run_id.in_(list(run_ids))
                )
            )
        if session_ids:
            connection.execute(
                sqlalchemy.delete(MessageRecord).where(
                    MessageRecord.session_id.in_(list(session_ids))
                )
            )
            connection.execute(
                sqlalchemy.delete(SessionRecord).where(
                    SessionRecord.session_id.in_(list(session_ids))
                )
            )
        if action_ids:
            connection.execute(
                sqlalchemy.delete(PendingActionRecord).where(
                    PendingActionRecord.id.in_(list(action_ids))
                )
            )
        if cron_job_ids:
            connection.execute(
                sqlalchemy.delete(CronLogRecord).where(
                    CronLogRecord.job_id.in_(list(cron_job_ids))
                )
            )
            connection.execute(
                sqlalchemy.delete(CronJobRecord).where(
                    CronJobRecord.id.in_(list(cron_job_ids))
                )
            )
        if background_ids:
            connection.execute(
                sqlalchemy.delete(BackgroundTaskRecord).where(
                    BackgroundTaskRecord.id.in_(list(background_ids))
                )
            )
        if task_ids:
            connection.execute(
                sqlalchemy.delete(TaskDependencyRecord).where(
                    TaskDependencyRecord.task_id.in_(list(task_ids))
                )
            )
            connection.execute(
                sqlalchemy.delete(TaskRecord).where(
                    TaskRecord.id.in_(list(task_ids))
                )
            )
        if target_ids:
            connection.execute(
                sqlalchemy.delete(TargetRecord).where(
                    TargetRecord.id.in_(list(target_ids))
                )
            )
        if memory_ids:
            connection.execute(
                sqlalchemy.delete(MemoryEntryRecord).where(
                    MemoryEntryRecord.id.in_(list(memory_ids))
                )
            )


def test_target_roundtrip_and_optimistic_locking(pg):
    target_id = f"pgtest_tgt_{uuid.uuid4().hex[:12]}"
    payload = {
        "id": target_id,
        "name": "pg integration target",
        "root": "/srv/pgtest",
        "description": "initial",
        "created_at": 1_700_000_000.0,
        "updated_at": 1_700_000_000.0,
    }
    try:
        assert target_repo.upsert_target(payload) is True
        # Repeating the same mirror write must not create a second row.
        assert target_repo.upsert_target(payload) is True
        assert target_repo.fetch_target(target_id)["description"] == "initial"

        first = target_repo.upsert_target(
            {**payload, "description": "first", "updated_at": 1_700_000_100.0},
            expected_version=1,
        )
        second = target_repo.upsert_target(
            {**payload, "description": "second", "updated_at": 1_700_000_200.0},
            expected_version=1,
        )
        assert first is True
        assert second is False
        assert target_repo.fetch_target(target_id)["description"] == "first"
        assert target_repo.delete_target(target_id) is True
    finally:
        _cleanup(pg, target_ids=[target_id])


def test_task_dependencies_are_synced_in_order(pg):
    task_id = f"pgtest_task_{uuid.uuid4().hex[:12]}"
    dep_a = f"pgtest_dep_{uuid.uuid4().hex[:8]}"
    dep_b = f"pgtest_dep_{uuid.uuid4().hex[:8]}"
    record = {
        "id": task_id,
        "subject": "pg integration task",
        "description": "",
        "status": "pending",
        "owner": None,
        "blockedBy": [dep_a, dep_b],
        "run_id": "",
        "source": "task",
        "metadata": {"k": "v"},
        "priority": "high",
        "created_at": 1_700_000_000.0,
        "updated_at": 1_700_000_000.0,
        "result": "",
    }
    try:
        assert task_repo.upsert_task(record) is True
        assert task_repo.fetch_task(task_id)["blockedBy"] == [dep_a, dep_b]
        assert task_repo.fetch_task(task_id)["metadata"] == {"k": "v"}

        reordered = {**record, "blockedBy": [dep_b, dep_a], "updated_at": 1_700_000_100.0}
        assert task_repo.upsert_task(reordered) is True
        assert task_repo.fetch_task(task_id)["blockedBy"] == [dep_b, dep_a]

        without_deps = {**record, "blockedBy": [], "updated_at": 1_700_000_200.0}
        assert task_repo.upsert_task(without_deps) is True
        assert task_repo.fetch_task(task_id)["blockedBy"] == []
        assert task_repo.delete_task(task_id) is True
    finally:
        _cleanup(pg, task_ids=[task_id])


def test_memory_mirror_roundtrip(pg):
    memory_ids = [f"pgtest_mem_{uuid.uuid4().hex[:12]}" for _ in range(2)]
    records = [
        {
            "id": memory_ids[0],
            "content": "pg integration memory one",
            "scope": "global",
            "status": "active",
            "tags": ["pg", "test"],
            "content_hash": "a" * 64,
            "created_at": 1_700_000_000.0,
            "updated_at": 1_700_000_000.0,
        },
        {
            "id": memory_ids[1],
            "content": "pg integration memory two",
            "scope": "global",
            "status": "active",
            "tags": [],
            "content_hash": "b" * 64,
            "created_at": 1_700_000_000.0,
            "updated_at": 1_700_000_000.0,
        },
    ]
    try:
        assert memory_repo.upsert_memories(records) == 2
        assert memory_repo.fetch_memory(memory_ids[0])["tags"] == ["pg", "test"]

        archived = {
            **records[0],
            "status": "archived",
            "updated_at": 1_700_000_100.0,
        }
        assert memory_repo.upsert_memories([archived]) == 1
        assert memory_repo.fetch_memory(memory_ids[0])["status"] == "archived"
        assert memory_repo.delete_memory(memory_ids[0]) is True
        assert memory_repo.fetch_memory(memory_ids[0]) is None
    finally:
        _cleanup(pg, memory_ids=memory_ids)


def test_writer_reports_postgres_failure(pg, monkeypatch):
    def explode(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "agent.persistence.repositories.targets.upsert_target",
        explode,
    )

    assert writer.persist_target({
        "id": "pgtest_unused",
        "name": "x",
        "root": "/tmp",
    }) is False


ACTION_TEMPLATE = {
    "session_id": "pgtest_session",
    "target_id": "",
    "run_id": "pgtest_run",
    "tool_use_id": "pgtest_call",
    "owner_id": "pgtest_user",
    "action_code": "tool.bash",
    "title": "pg integration action",
    "risk_level": "high",
    "agent_mode": "react",
    "status": "pending",
    "source_message": "please restart the service",
    "summary": "restart service",
    "payload": {"tool": "bash", "input": {"command": "systemctl restart trip"}},
    "steps": [{"tool": "bash", "input": {"command": "systemctl restart trip"}}],
    "impact": "restarts the service",
    "rollback_plan": "",
    "verification": "check health url",
    "result_payload": {"execution_enabled": True},
    "created_at": 1_700_000_000.0,
    "updated_at": 1_700_000_000.0,
    "confirmed_by": "",
    "confirmed_at": None,
    "canceled_by": "",
    "canceled_at": None,
    "cancel_reason": "",
}


def test_concurrent_confirm_only_one_approval_wins(pg):
    action_id = f"pgtest_act_{uuid.uuid4().hex[:12]}"
    record = {**ACTION_TEMPLATE, "id": action_id}
    try:
        assert action_repo.upsert_action(record) is True

        results: list[tuple[str, bool]] = []
        barrier = threading.Barrier(2)
        lock = threading.Lock()

        def approve(actor: str) -> None:
            payload = {
                **record,
                "status": "confirmed",
                "confirmed_by": actor,
                "confirmed_at": time.time(),
            }
            barrier.wait()
            outcome = action_repo.confirm_action(action_id, payload) is not None
            with lock:
                results.append((actor, outcome))

        threads = [
            threading.Thread(target=approve, args=(f"approver-{index}",))
            for index in range(2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert len(results) == 2
        assert sum(1 for _, won in results if won) == 1

        stored = action_repo.fetch_action(action_id)
        assert stored["status"] == "confirmed"
        assert stored["confirmed_by"] in {"approver-0", "approver-1"}
        assert stored["version"] == 2
    finally:
        _cleanup(pg, action_ids=[action_id])


def test_recover_interrupted_actions_is_idempotent(pg):
    action_id = f"pgtest_act_{uuid.uuid4().hex[:12]}"
    record = {
        **ACTION_TEMPLATE,
        "id": action_id,
        "status": "confirmed",
        "confirmed_by": "pgtest_user",
        "confirmed_at": 1_700_000_100.0,
    }
    try:
        assert action_repo.upsert_action(record) is True

        # The mirror upsert already stores status=confirmed, so recovery
        # must flip it once and report zero rows the second time.
        assert action_repo.recover_interrupted_actions("pg integration restart") == 1
        assert action_repo.recover_interrupted_actions("pg integration restart") == 0

        stored = action_repo.fetch_action(action_id)
        assert stored["status"] == "failed"
        assert stored["result_payload"]["interrupted"] is True
    finally:
        _cleanup(pg, action_ids=[action_id])


def test_cron_claim_is_exclusive_across_connections(pg):
    job_id = f"pgtest_cron_{uuid.uuid4().hex[:12]}"
    job = {
        "id": job_id,
        "cron": "* * * * *",
        "prompt": "pg integration cron",
        "recurring": True,
        "durable": True,
        "name": "pgtest",
        "description": "",
        "enabled": True,
        "created_at": 1_700_000_000.0,
        "updated_at": 1_700_000_000.0,
    }
    minute = 1_800_000_000.0
    try:
        assert cron_repo.upsert_cron_job(job) is True

        claims: list[list[str]] = []
        barrier = threading.Barrier(2)
        lock = threading.Lock()

        def claim() -> None:
            barrier.wait()
            won = cron_repo.claim_due_cron_jobs([job_id], minute_epoch=minute)
            with lock:
                claims.append(won)

        threads = [threading.Thread(target=claim) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert sorted(len(won) for won in claims) == [0, 1]
        stored = cron_repo.fetch_cron_jobs()[0]
        assert stored["last_fired_at"] == minute
        assert stored["fire_count"] == 1

        # Same minute again: nobody may claim it.
        assert cron_repo.claim_due_cron_jobs([job_id], minute_epoch=minute) == []
        assert cron_repo.claim_due_cron_jobs(
            [job_id],
            minute_epoch=minute + 60,
        ) == [job_id]
    finally:
        _cleanup(pg, cron_job_ids=[job_id])


def test_background_interrupt_cas_runs_once(pg):
    background_id = f"pgtest_bg_{uuid.uuid4().hex[:12]}"
    task = {
        "background_id": background_id,
        "tool_use_id": "pgtest_call",
        "command": "pip install -r requirements.txt",
        "status": "running",
        "run_id": "pgtest_run",
        "parent_run_id": "pgtest_parent",
        "session_id": "pgtest_session",
        "owner_id": "pgtest_user",
        "source": "background",
        "created_at": 1_700_000_000.0,
        "updated_at": 1_700_000_000.0,
    }
    try:
        assert background_repo.upsert_background_task(task) is True
        assert background_repo.mark_background_interrupted(
            background_id,
            reason="pg integration restart",
            at=1_700_000_500.0,
        ) is True
        assert background_repo.mark_background_interrupted(
            background_id,
            reason="pg integration restart",
            at=1_700_000_600.0,
        ) is False

        stored = background_repo.fetch_background_task(background_id)
        assert stored["status"] == "failed"
        assert stored["parent_run_id"] == "pgtest_parent"
        assert stored["interruption_reason"] == "pg integration restart"
    finally:
        _cleanup(pg, background_ids=[background_id])


def _session_record(session_id: str, messages: list[dict]) -> dict:
    return {
        "session_id": session_id,
        "owner_id": "pgtest_user",
        "status": "active",
        "target_id": "",
        "title": "pg integration session",
        "messages": messages,
        "created_at": 1_700_000_000.0,
        "updated_at": 1_700_000_000.0,
    }


def test_session_roundtrip_and_message_rewrite(pg):
    session_id = f"pgtest_sess_{uuid.uuid4().hex[:12]}"
    messages = [
        {"role": "user", "content": "check disk"},
        {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
        {"role": "user", "content": "now memory"},
    ]
    try:
        assert session_repo.upsert_session(
            _session_record(session_id, messages),
            ttl_seconds=600,
        ) is True

        stored = session_repo.fetch_session(session_id)
        assert stored["message_count"] == 3
        assert stored["expires_at"] == pytest.approx(1_700_000_000.0 + 600)
        assert [item["role"] for item in stored["messages"]] == [
            "user",
            "assistant",
            "user",
        ]
        assert stored["messages"][1]["content"] == [{"type": "text", "text": "ok"}]

        # Compaction shrinks the conversation: stale seq rows must disappear.
        compacted = _session_record(
            session_id,
            [{"role": "user", "content": "[Compacted] summary"}],
        )
        compacted["updated_at"] = 1_700_000_100.0
        assert session_repo.upsert_session(compacted) is True

        stored = session_repo.fetch_session(session_id)
        assert stored["message_count"] == 1
        assert session_repo.count_messages(session_id) == 1
        assert stored["messages"][0]["content"] == "[Compacted] summary"
    finally:
        _cleanup(pg, session_ids=[session_id])


def test_run_roundtrip_and_snapshot_skip(pg):
    run_id = f"pgtest_run_{uuid.uuid4().hex[:12]}"
    session_id = f"pgtest_sess_{uuid.uuid4().hex[:12]}"
    messages = [
        {"role": "user", "content": "check disk"},
        {"role": "assistant", "content": "disk is fine"},
    ]
    record = {
        "run_id": run_id,
        "session_id": session_id,
        "owner_id": "pgtest_user",
        "source": "chat",
        "status": "running",
        "phase": "model",
        "user_message": "check disk",
        "messages": messages,
        "safe_to_resume": True,
        "active_tool": "",
        "interruption_reason": "",
        "resume_count": 0,
        "created_at": 1_700_000_000.0,
        "updated_at": 1_700_000_000.0,
        "finished_at": None,
    }
    try:
        assert run_repo.upsert_run(record) is True
        stored = run_repo.fetch_run(run_id)
        assert stored["message_count"] == 2
        assert [item["content"] for item in stored["messages"]] == [
            "check disk",
            "disk is fine",
        ]
        snapshot_created_at = 1_700_000_000.0

        assert run_repo.upsert_run({
            **record,
            "phase": "executing_tool",
            "safe_to_resume": False,
            "active_tool": "bash",
            "updated_at": 1_700_000_100.0,
        }) is True

        stored = run_repo.fetch_run(run_id)
        assert stored["phase"] == "executing_tool"
        assert stored["safe_to_resume"] is False
        assert stored["active_tool"] == "bash"

        with pg.begin() as connection:
            created_at = connection.execute(
                sqlalchemy.select(RunSnapshotRecord.created_at).where(
                    RunSnapshotRecord.run_id == run_id
                )
            ).scalar()
        assert float(created_at) == snapshot_created_at
    finally:
        _cleanup(pg, run_ids=[run_id])


def test_interrupt_stale_runs_is_idempotent(pg):
    running_id = f"pgtest_run_{uuid.uuid4().hex[:12]}"
    done_id = f"pgtest_run_{uuid.uuid4().hex[:12]}"
    base = {
        "session_id": "pgtest_session",
        "owner_id": "pgtest_user",
        "source": "chat",
        "phase": "model",
        "user_message": "check disk",
        "safe_to_resume": True,
        "active_tool": "",
        "interruption_reason": "",
        "resume_count": 0,
        "created_at": 1_700_000_000.0,
        "updated_at": 1_700_000_000.0,
        "finished_at": None,
    }
    try:
        assert run_repo.upsert_run({
            **base,
            "run_id": running_id,
            "status": "running",
        }) is True
        assert run_repo.upsert_run({
            **base,
            "run_id": done_id,
            "status": "completed",
            "finished_at": 1_700_000_050.0,
        }) is True

        assert run_repo.interrupt_stale_runs("pg integration restart") == 1
        assert run_repo.interrupt_stale_runs("pg integration restart") == 0

        interrupted = run_repo.fetch_run(running_id)
        assert interrupted["status"] == "interrupted"
        assert interrupted["phase"] == "interrupted"
        assert interrupted["active_tool"] == ""
        assert run_repo.fetch_run(done_id)["status"] == "completed"
    finally:
        _cleanup(pg, run_ids=[running_id, done_id])
