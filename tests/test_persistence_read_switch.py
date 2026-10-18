"""Read-path switch tests: JSON by default, PostgreSQL when switched on."""

import pytest
import sqlalchemy
from sqlalchemy.pool import StaticPool

import agent.platform.config as config
from agent.memory import store as memory_store_module
from agent.memory.service import MemorySystem
from agent.orchestration import tasks as tasks_module
from agent.orchestration.pending_actions import PendingActionStore
from agent.orchestration.tasks import Task, can_start, create_task, load_task, save_task
from agent.persistence import database
from agent.persistence import consistency
from agent.persistence.models import Base
from agent.persistence.routing import READABLE_DOMAINS, read_status
from agent.sessions.state_store import RecoveryStore
from agent.targets.store import TargetStore


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
    monkeypatch.setattr(config, "PERSISTENCE_READ", "json")
    monkeypatch.setattr(config, "PERSISTENCE_READ_DOMAINS", ())
    yield engine
    database.dispose_engine()
    monkeypatch.setattr(database, "_engine", None)
    monkeypatch.setattr(database, "_session_factory", None)


def _switch_reads_to_postgres(monkeypatch, *domains):
    monkeypatch.setattr(config, "PERSISTENCE_READ", "postgres")
    monkeypatch.setattr(config, "PERSISTENCE_READ_DOMAINS", tuple(domains))


def _isolate_stores(tmp_path, monkeypatch) -> RecoveryStore:
    monkeypatch.setattr(
        tasks_module,
        "TASKS_DIR",
        tmp_path / "tasks",
    )
    monkeypatch.setattr(
        memory_store_module,
        "MEMORY_DIR",
        tmp_path / "memory",
    )
    return RecoveryStore(
        sessions_dir=tmp_path / "sessions",
        runs_dir=tmp_path / "runs",
    )


def test_read_status_defaults_to_json(sqlite_db):
    status = read_status()

    assert status["read_mode"] == "json"
    assert status["postgres_reads"] == []
    assert status["json_reads"] == list(READABLE_DOMAINS)


def test_targets_read_from_postgres_after_switch(tmp_path, monkeypatch, sqlite_db):
    project = tmp_path / "trip"
    project.mkdir()
    monkeypatch.setattr(config, "TARGET_BROWSE_ROOTS", (tmp_path.resolve(),))
    target_path = tmp_path / "targets.json"
    monkeypatch.setattr("agent.targets.store.TARGETS_PATH", target_path)

    created = TargetStore().create({"name": "trip", "root": str(project)})
    # Remove the local copy: only PostgreSQL can answer now.
    target_path.unlink()

    assert TargetStore().get(created.id) is None

    _switch_reads_to_postgres(monkeypatch, "targets")

    store = TargetStore()
    assert store.get(created.id).name == "trip"
    assert [item.id for item in store.list()] == [created.id]
    assert store.get("tgt_missing") is None


def test_tasks_read_from_postgres_after_switch(tmp_path, monkeypatch, sqlite_db):
    monkeypatch.setattr(tasks_module, "TASKS_DIR", tmp_path / "tasks")
    dependency = create_task("dependency")
    dependency.status = "completed"
    save_task(dependency)
    task = create_task("main task", blockedBy=[dependency.id])

    for path in (tmp_path / "tasks").glob("*.json"):
        path.unlink()

    _switch_reads_to_postgres(monkeypatch, "tasks")

    stored = load_task(task.id)
    assert stored.subject == "main task"
    assert stored.blockedBy == [dependency.id]
    assert can_start(task.id) is True
    assert len(tasks_module.list_tasks()) == 2


def test_task_dependency_missing_is_detected_from_postgres(
    tmp_path,
    monkeypatch,
    sqlite_db,
):
    monkeypatch.setattr(tasks_module, "TASKS_DIR", tmp_path / "tasks")
    task = Task(
        id="task_orphan",
        subject="orphan",
        description="",
        status="pending",
        owner=None,
        blockedBy=["task_not_here"],
    )
    save_task(task)

    _switch_reads_to_postgres(monkeypatch, "tasks")

    assert can_start("task_orphan") is False
    assert "missing deps" in tasks_module.claim_task("task_orphan")


def test_memories_read_from_postgres_after_switch(tmp_path, monkeypatch, sqlite_db):
    monkeypatch.setattr(memory_store_module, "MEMORY_DIR", tmp_path / "memory")
    MemorySystem().add("deploy uses systemd", scope="global")
    (tmp_path / "memory" / "memories.jsonl").unlink()

    assert MemorySystem().memories == []

    _switch_reads_to_postgres(monkeypatch, "memories")

    restored = MemorySystem()
    assert len(restored.memories) == 1
    assert restored.memories[0]["content"] == "deploy uses systemd"
    assert restored.get(restored.memories[0]["id"]) is not None


def test_actions_read_from_postgres_after_switch(tmp_path, monkeypatch, sqlite_db):
    actions_path = tmp_path / "actions.json"
    store = PendingActionStore(actions_path)
    record = store.create_tool_call(
        "bash",
        {"command": "systemctl restart trip"},
        session_id="session-1",
        run_id="run-1",
        tool_use_id="call-1",
        owner_id="alice",
    )
    store.confirm(record.id, actor="tester")
    actions_path.unlink()

    assert PendingActionStore(actions_path).get(record.id) is None

    _switch_reads_to_postgres(monkeypatch, "actions")

    reader = PendingActionStore(actions_path)
    assert reader.get(record.id).status == "confirmed"
    assert [item.id for item in reader.list(status="confirmed")] == [record.id]
    assert reader.list(status="pending") == []


def test_sessions_and_runs_read_from_postgres_after_switch(
    tmp_path,
    monkeypatch,
    sqlite_db,
):
    store = _isolate_stores(tmp_path, monkeypatch)
    store.save_session(
        "session-1",
        owner_id="alice",
        messages=[{"role": "user", "content": "check disk"}],
        title="disk",
    )
    store.create_run(
        "run-1",
        session_id="session-1",
        owner_id="alice",
        user_message="check disk",
        messages=[{"role": "user", "content": "check disk"}],
    )
    for path in (tmp_path / "sessions").glob("*.json"):
        path.unlink()
    for path in (tmp_path / "runs").glob("*.json"):
        path.unlink()

    assert store.get_session("session-1") is None
    assert store.get_run("run-1") is None

    _switch_reads_to_postgres(monkeypatch, "sessions", "runs")

    session = store.get_session("session-1")
    assert session["title"] == "disk"
    assert session["messages"] == [{"role": "user", "content": "check disk"}]
    assert [item["session_id"] for item in store.list_sessions(light=True)] == [
        "session-1"
    ]

    run = store.get_run("run-1")
    assert run["status"] == "running"
    assert run["safe_to_resume"] is True
    assert run["messages"] == [{"role": "user", "content": "check disk"}]
    listed = store.list_runs(limit=10, include_messages=True)
    assert [item["run_id"] for item in listed] == ["run-1"]
    assert listed[0]["messages"][0]["content"] == "check disk"


def test_session_owner_filter_matches_local_semantics(tmp_path, monkeypatch, sqlite_db):
    store = _isolate_stores(tmp_path, monkeypatch)
    store.save_session("session-mine", owner_id="alice", messages=[])
    store.save_session("session-nobody", owner_id="", messages=[])
    store.save_session("session-other", owner_id="bob", messages=[])

    json_side = [item["session_id"] for item in store.list_sessions(light=True)]
    assert set(json_side) == {"session-mine", "session-nobody", "session-other"}

    _switch_reads_to_postgres(monkeypatch, "sessions")

    pg_side = [
        item["session_id"] for item in store.list_sessions(owner_id="alice", light=True)
    ]
    assert set(pg_side) == {"session-mine", "session-nobody"}


def test_read_switch_falls_back_to_json_when_postgres_fails(
    tmp_path,
    monkeypatch,
    sqlite_db,
):
    monkeypatch.setattr(tasks_module, "TASKS_DIR", tmp_path / "tasks")
    task = create_task("still local")

    def unreachable():
        raise RuntimeError("database unreachable")

    monkeypatch.setattr(database, "get_engine", unreachable)
    _switch_reads_to_postgres(monkeypatch, "tasks")

    assert load_task(task.id).subject == "still local"
    assert len(tasks_module.list_tasks()) == 1


def test_consistency_watcher_is_disabled_without_mirror(monkeypatch):
    monkeypatch.setattr(config, "PERSISTENCE_BACKEND", "json")
    assert consistency.consistency_enabled() is False
    assert consistency.start_consistency_watcher() is None

    monkeypatch.setattr(config, "PERSISTENCE_BACKEND", "dual")
    monkeypatch.setattr(config, "PERSISTENCE_CONSISTENCY_INTERVAL_SECONDS", 0)
    assert consistency.consistency_enabled() is False


def test_drift_report_writes_audit_only_on_change(monkeypatch):
    events = []
    monkeypatch.setattr(
        consistency,
        "record_event",
        lambda *args, **kwargs: events.append((args, kwargs)),
    )
    monkeypatch.setattr(consistency, "_last_drift", None)

    drifting = {
        "domains_with_drift": ["sessions"],
        "results": {"sessions": {"consistent": False}},
    }
    clean = {"domains_with_drift": [], "results": {}}

    # The first observation always reports, even when it is clean.
    assert consistency._handle_report(clean) is False
    assert len(events) == 1
    assert events[0][0][0] == "persistence.consistency.ok"
    consistency._handle_report(clean)
    assert len(events) == 1

    assert consistency._handle_report(drifting) is True
    assert len(events) == 2
    assert events[1][0][0] == "persistence.consistency.drift"
    assert consistency._handle_report(drifting) is True
    assert len(events) == 2

    assert consistency._handle_report(clean) is False
    assert len(events) == 3
    assert events[2][0][0] == "persistence.consistency.ok"

    consistency._handle_report(clean)
    assert len(events) == 3
