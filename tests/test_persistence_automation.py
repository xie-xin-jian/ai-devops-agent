"""Dual-write and CAS tests for pending actions, Cron and background tasks."""

import json
from datetime import datetime

import pytest
import sqlalchemy
from sqlalchemy.pool import StaticPool

import agent.platform.config as config
from agent.orchestration import background as background_module
from agent.orchestration import cron as cron_module
from agent.orchestration.pending_actions import PendingActionStore
from agent.persistence import database, writer
from agent.persistence.models import Base
from agent.persistence.repositories import actions as action_repo
from agent.persistence.repositories import background as background_repo
from agent.persistence.repositories import cron as cron_repo


@pytest.fixture
def sqlite_db(monkeypatch):
    engine = sqlalchemy.create_engine(
        "sqlite+pysqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    monkeypatch.setattr(database, "_engine", engine)
    monkeypatch.setattr(database, "_session_factory", None)
    monkeypatch.setattr(config, "PERSISTENCE_BACKEND", "dual")
    monkeypatch.setattr(config, "DATABASE_URL", "sqlite+pysqlite://")
    yield engine
    database.dispose_engine()
    monkeypatch.setattr(database, "_engine", None)
    monkeypatch.setattr(database, "_session_factory", None)


def _new_action(store: PendingActionStore, **overrides):
    kwargs = {
        "session_id": "session-1",
        "run_id": "run-1",
        "tool_use_id": "call-1",
        "owner_id": "alice",
        "summary": "执行命令: rm -rf build",
    }
    kwargs.update(overrides)
    return store.create_tool_call("bash", {"command": "rm -rf build"}, **kwargs)


def test_pending_action_store_mirrors_lifecycle(tmp_path, sqlite_db):
    store = PendingActionStore(tmp_path / "actions.json")
    record = _new_action(store)

    stored = action_repo.fetch_action(record.id)
    assert stored["status"] == "pending"
    assert stored["tool_use_id"] == "call-1"
    assert stored["owner_id"] == "alice"
    assert stored["payload"]["tool"] == "bash"

    store.confirm(record.id, actor="tester")
    stored = action_repo.fetch_action(record.id)
    assert stored["status"] == "confirmed"
    assert stored["confirmed_by"] == "tester"
    assert stored["result_payload"]["execution_enabled"] is False

    store.finish(
        record.id,
        status="executed",
        result_payload={"execution_enabled": True, "success": True},
    )
    stored = action_repo.fetch_action(record.id)
    assert stored["status"] == "executed"
    assert stored["result_payload"]["success"] is True


def test_pending_action_cancel_is_mirrored(tmp_path, sqlite_db):
    store = PendingActionStore(tmp_path / "actions.json")
    record = _new_action(store)

    store.cancel(record.id, actor="tester", reason="not needed")

    stored = action_repo.fetch_action(record.id)
    assert stored["status"] == "canceled"
    assert stored["canceled_by"] == "tester"
    assert stored["cancel_reason"] == "not needed"


def test_confirm_cas_rejects_second_approval(tmp_path, sqlite_db):
    """A second approval must lose the race instead of overwriting state."""
    store = PendingActionStore(tmp_path / "actions.json")
    record = _new_action(store)
    payload = record.to_dict()

    payload["status"] = "confirmed"
    payload["confirmed_by"] = "first"
    payload["confirmed_at"] = 1_700_000_100.0
    assert action_repo.confirm_action(record.id, payload) is not None

    payload["confirmed_by"] = "second"
    assert action_repo.confirm_action(record.id, payload) is None

    stored = action_repo.fetch_action(record.id)
    assert stored["status"] == "confirmed"
    assert stored["confirmed_by"] == "first"
    assert stored["version"] == 2


def test_finish_cas_requires_confirmed_state(tmp_path, sqlite_db):
    store = PendingActionStore(tmp_path / "actions.json")
    record = _new_action(store)
    payload = {**record.to_dict(), "status": "executed"}

    # Still pending: the terminal transition must be refused.
    assert action_repo.finish_action(record.id, payload) is None

    payload["status"] = "confirmed"
    assert action_repo.confirm_action(record.id, payload) is not None
    payload["status"] = "executed"
    assert action_repo.finish_action(record.id, payload) is not None
    assert action_repo.fetch_action(record.id)["status"] == "executed"


def test_recover_interrupted_actions_only_fails_confirmed(tmp_path, sqlite_db):
    store = PendingActionStore(tmp_path / "actions.json")
    pending = _new_action(store, session_id="session-p")
    confirmed = _new_action(store, session_id="session-c")
    store.confirm(confirmed.id, actor="tester")

    changed = action_repo.recover_interrupted_actions("process restarted")

    assert changed == 1
    assert action_repo.fetch_action(confirmed.id)["status"] == "failed"
    assert action_repo.fetch_action(confirmed.id)["result_payload"]["interrupted"]
    assert action_repo.fetch_action(pending.id)["status"] == "pending"


def test_action_store_recovery_mirrors_failure(tmp_path, sqlite_db):
    store = PendingActionStore(tmp_path / "actions.json")
    record = _new_action(store)
    store.confirm(record.id, actor="tester")

    recovered = store.recover_interrupted("process restarted")

    assert [item.id for item in recovered] == [record.id]
    stored = action_repo.fetch_action(record.id)
    assert stored["status"] == "failed"
    assert stored["result_payload"]["error"] == "process restarted"


def test_cron_job_mirror_and_delete(tmp_path, monkeypatch, sqlite_db):
    monkeypatch.setattr(
        cron_module,
        "DURABLE_CRON_PATH",
        tmp_path / ".scheduled_tasks.json",
    )
    with cron_module.cron_lock:
        cron_module.scheduled_jobs.clear()

    job, _ = cron_module.schedule_job(
        "0 9 * * *",
        "daily inspection",
        name="Daily",
        description="check disk",
    )
    assert cron_repo.fetch_cron_jobs()[0]["id"] == job.id
    assert cron_repo.fetch_cron_jobs()[0]["cron"] == "0 9 * * *"

    cron_module.cancel_job(job.id)
    assert cron_repo.fetch_cron_jobs() == []


def test_loading_durable_jobs_mirrors_missing_rows(tmp_path, monkeypatch, sqlite_db):
    """A job written before the mirror existed must still get a PG row."""
    durable_path = tmp_path / ".scheduled_tasks.json"
    monkeypatch.setattr(cron_module, "DURABLE_CRON_PATH", durable_path)
    durable_path.write_text(
        json.dumps({
            "cron_legacy": {
                "id": "cron_legacy",
                "cron": "0 9 * * *",
                "prompt": "legacy task",
                "recurring": True,
                "durable": True,
            }
        }),
        encoding="utf-8",
    )
    with cron_module.cron_lock:
        cron_module.scheduled_jobs.clear()
    assert cron_repo.count_cron_jobs() == 0

    cron_module.load_durable_jobs()

    stored = cron_repo.fetch_cron_jobs()
    assert [job["id"] for job in stored] == ["cron_legacy"]
    assert stored[0]["enabled"] is True

    minute = datetime(2026, 10, 16, 9, 0).timestamp()
    assert cron_repo.claim_due_cron_jobs(["cron_legacy"], minute_epoch=minute) == [
        "cron_legacy"
    ]


def test_cron_claim_happens_once_per_minute(tmp_path, monkeypatch, sqlite_db):
    monkeypatch.setattr(
        cron_module,
        "DURABLE_CRON_PATH",
        tmp_path / ".scheduled_tasks.json",
    )
    with cron_module.cron_lock:
        cron_module.scheduled_jobs.clear()
    job, _ = cron_module.schedule_job("* * * * *", "check disk")

    minute = datetime(2026, 10, 16, 10, 0).timestamp()
    first = cron_repo.claim_due_cron_jobs([job.id], minute_epoch=minute)
    second = cron_repo.claim_due_cron_jobs([job.id], minute_epoch=minute)
    next_minute = cron_repo.claim_due_cron_jobs(
        [job.id],
        minute_epoch=minute + 60,
    )

    assert first == [job.id]
    assert second == []
    assert next_minute == [job.id]
    stored = cron_repo.fetch_cron_jobs()[0]
    assert stored["last_fired_at"] == minute + 60
    assert stored["fire_count"] == 2


def test_cron_claim_skips_disabled_and_unknown_jobs(sqlite_db):
    assert cron_repo.claim_due_cron_jobs([], minute_epoch=1.0) == []
    assert cron_repo.claim_due_cron_jobs(["cron_missing"], minute_epoch=1.0) == []


def test_cron_scheduler_uses_postgres_claim_for_durable_jobs(
    tmp_path,
    monkeypatch,
    sqlite_db,
):
    """A durable job already claimed for this minute must not fire again."""
    monkeypatch.setattr(
        cron_module,
        "DURABLE_CRON_PATH",
        tmp_path / ".scheduled_tasks.json",
    )
    monkeypatch.setattr(cron_module, "_ensure_cron_worker_started", lambda: None)
    monkeypatch.setattr(cron_module, "save_durable_jobs", lambda: None)
    monkeypatch.setattr(
        cron_module,
        "_cron_execution_queue",
        __import__("queue").Queue(),
    )
    with cron_module.cron_lock:
        cron_module.scheduled_jobs.clear()
        cron_module._last_fired.clear()

    job, _ = cron_module.schedule_job("* * * * *", "check disk")
    minute = datetime.now().replace(second=0, microsecond=0)
    assert cron_repo.claim_due_cron_jobs(
        [job.id],
        minute_epoch=minute.timestamp(),
    ) == [job.id]

    def stop_loop(_seconds):
        raise StopIteration

    monkeypatch.setattr(cron_module.time, "sleep", stop_loop)
    with pytest.raises(StopIteration):
        cron_module.cron_scheduler_loop()

    assert cron_module._cron_execution_queue.qsize() == 0


def test_cron_log_mirror_is_idempotent(tmp_path, monkeypatch, sqlite_db):
    monkeypatch.setattr(cron_module, "CRON_LOG_DIR", tmp_path / "logs")
    job = cron_module.CronJob(
        id="cron_log",
        cron="* * * * *",
        prompt="check disk",
    )
    fired_at = datetime(2026, 10, 16, 10, 0)

    cron_module._save_cron_run_log(job, fired_at, "ok")
    cron_module._save_cron_run_log(job, fired_at, "ok")

    assert cron_repo.count_cron_logs() == 1
    stored = cron_repo.fetch_cron_logs("cron_log")[0]
    assert stored["success"] is True
    assert stored["output"] == "ok"
    assert stored["fired_at_epoch"] == fired_at.timestamp()


def test_background_task_mirror_and_interrupted_cas(tmp_path, monkeypatch, sqlite_db):
    monkeypatch.setattr(background_module, "BACKGROUND_DIR", tmp_path)
    monkeypatch.setattr(background_module, "record_event", lambda *a, **k: None)

    background_module._persist_task("bg_missing")
    assert background_repo.count_background_tasks() == 0

    with background_module.background_lock:
        background_module.background_tasks["bg_1"] = {
            "tool_use_id": "call-1",
            "command": "pip install -r requirements.txt",
            "status": "running",
            "run_id": "run-1",
            "parent_run_id": "run-0",
            "session_id": "session-1",
            "owner_id": "alice",
            "source": "background",
            "created_at": 1_700_000_000.0,
        }
    background_module._persist_task("bg_1")

    stored = background_repo.fetch_background_task("bg_1")
    assert stored["status"] == "running"
    assert stored["parent_run_id"] == "run-0"

    recovered = background_module.recover_interrupted_background_tasks(
        "process restarted"
    )

    assert [item["background_id"] for item in recovered] == ["bg_1"]
    stored = background_repo.fetch_background_task("bg_1")
    assert stored["status"] == "failed"
    assert stored["interruption_reason"] == "process restarted"

    # The CAS must not fire twice for the same task.
    assert background_repo.mark_background_interrupted(
        "bg_1",
        reason="again",
        at=1_700_000_500.0,
    ) is False


def test_json_backend_skips_automation_mirrors(tmp_path, monkeypatch, sqlite_db):
    monkeypatch.setattr(config, "PERSISTENCE_BACKEND", "json")
    store = PendingActionStore(tmp_path / "actions.json")
    record = _new_action(store)
    store.confirm(record.id, actor="tester")

    monkeypatch.setattr(config, "PERSISTENCE_BACKEND", "dual")
    assert action_repo.count_actions() == 0


def test_claim_returns_none_when_database_is_unreachable(monkeypatch):
    """Cron must fall back to the local gate, not stop firing silently."""
    monkeypatch.setattr(config, "PERSISTENCE_BACKEND", "dual")
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql+psycopg://db/ai_devops")
    monkeypatch.setattr(database, "_engine", None)
    monkeypatch.setattr(database, "_session_factory", None)

    def unreachable():
        raise RuntimeError("database unreachable")

    monkeypatch.setattr(database, "get_engine", unreachable)

    assert writer.claim_due_cron_jobs(["cron_x"], minute_epoch=1.0) is None


def test_cron_claim_compiles_lock_clause_for_postgres():
    """The claim query must use FOR UPDATE SKIP LOCKED on PostgreSQL."""
    from sqlalchemy import select
    from sqlalchemy.dialects import postgresql

    from agent.persistence.models import CronJobRecord

    statement = (
        select(CronJobRecord)
        .where(CronJobRecord.id.in_(["cron_x"]))
        .order_by(CronJobRecord.id)
        .with_for_update(skip_locked=True)
    )
    compiled = str(statement.compile(dialect=postgresql.dialect()))

    assert "FOR UPDATE SKIP LOCKED" in compiled


def test_mirror_maintenance_deletes(sqlite_db):
    """The maintenance deletes used to clean up a verification run."""
    from agent.persistence.repositories import audit as audit_repo
    from agent.persistence.repositories import background as background_repo
    from agent.persistence.repositories import cron as cron_repo
    from agent.persistence.repositories import usage as usage_repo

    action = {
        "id": "act_cleanup",
        "session_id": "session-coverage",
        "run_id": "run-coverage",
        "status": "pending",
        "created_at": 1_700_000_000.0,
        "updated_at": 1_700_000_000.0,
    }
    assert action_repo.upsert_action(action) is True
    assert action_repo.delete_action("act_cleanup") is True
    assert action_repo.fetch_action("act_cleanup") is None
    assert action_repo.delete_action("act_cleanup") is False

    assert background_repo.upsert_background_task({
        "background_id": "bg_cleanup",
        "status": "running",
        "created_at": 1_700_000_000.0,
        "updated_at": 1_700_000_000.0,
    }) is True
    assert background_repo.delete_background_task("bg_cleanup") is True
    assert background_repo.fetch_background_task("bg_cleanup") is None

    assert cron_repo.upsert_cron_log({
        "id": "cron_cleanup__20260102_030405",
        "job_id": "cron_cleanup",
        "fired_at": "2026-01-02T03:04:05",
        "output": "cleanup",
    }) is True
    assert cron_repo.delete_cron_log("cron_cleanup__20260102_030405") is True
    assert cron_repo.fetch_cron_logs("cron_cleanup") == []

    for index in range(2):
        assert audit_repo.persist_audit_event({
            "id": f"evt_cleanup_{index}",
            "occurred_at": 1_700_000_000.0,
            "event_type": "coverage.check",
            "title": "cleanup",
            "session_id": "session-coverage",
            "run_id": "run-coverage",
            "created_at": 1_700_000_000.0,
        }) is True
    assert audit_repo.delete_audit_events_for(session_id="session-coverage") == 2
    assert audit_repo.delete_audit_events_for(session_id="session-coverage") == 0
    with pytest.raises(ValueError):
        audit_repo.delete_audit_events_for()

    assert usage_repo.persist_run_usage(run_id="run-coverage", input_tokens=1) is True
    assert usage_repo.delete_run_usage("run-coverage") == 1
    assert usage_repo.delete_run_usage("run-coverage") == 0
