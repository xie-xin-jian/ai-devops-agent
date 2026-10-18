"""Dual-write tests for targets, tasks and memories.

These run against an in-memory SQLite database wired into the same
``session_scope`` used by PostgreSQL, so the repository code, the writer
gate and the store hooks are all exercised without a live database.
"""

import pytest
import sqlalchemy
from sqlalchemy.pool import StaticPool

import agent.platform.config as config
from agent.memory import store as memory_store_module
from agent.memory.service import MemorySystem
from agent.orchestration import tasks as tasks_module
from agent.orchestration.tasks import Task, delete_task, save_task
from agent.persistence import database, writer
from agent.persistence.models import Base
from agent.persistence.repositories import common as repo_common
from agent.persistence.repositories import memories as memory_repo
from agent.persistence.repositories import targets as target_repo
from agent.persistence.repositories import tasks as task_repo
from agent.targets import store as target_store_module
from agent.targets.store import TargetStore


@pytest.fixture
def sqlite_db(monkeypatch):
    """Wire the persistence layer to a single in-memory SQLite connection."""
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


def _target_payload(target_id: str = "tgt_test", **overrides) -> dict:
    payload = {
        "id": target_id,
        "name": "trip assistant",
        "root": "/srv/trip",
        "description": "travel helper",
        "service": "trip.service",
        "health_url": "http://127.0.0.1:8001/health",
        "deploy_command": "docker compose up -d",
        "restart_command": "systemctl restart trip",
        "log_path": "/var/log/trip.log",
        "created_at": 1_700_000_000.0,
        "updated_at": 1_700_000_000.0,
    }
    payload.update(overrides)
    return payload


def test_target_repository_roundtrip(sqlite_db):
    assert target_repo.upsert_target(_target_payload()) is True

    stored = target_repo.fetch_target("tgt_test")
    assert stored["name"] == "trip assistant"
    assert stored["root"] == "/srv/trip"
    assert stored["service"] == "trip.service"
    assert target_repo.count_targets() == 1

    assert target_repo.delete_target("tgt_test") is True
    assert target_repo.fetch_target("tgt_test") is None
    assert target_repo.delete_target("tgt_test") is False


def test_target_upsert_is_idempotent_and_bumps_version_on_change(sqlite_db):
    payload = _target_payload()
    target_repo.upsert_target(payload)
    target_repo.upsert_target(payload)

    assert target_repo.count_targets() == 1
    with database.session_scope() as session:
        version = session.execute(
            sqlalchemy.text("SELECT version FROM targets WHERE id = 'tgt_test'")
        ).scalar()
    assert version == 1

    changed = _target_payload(description="updated", updated_at=1_700_000_100.0)
    target_repo.upsert_target(changed)

    with database.session_scope() as session:
        version = session.execute(
            sqlalchemy.text("SELECT version FROM targets WHERE id = 'tgt_test'")
        ).scalar()
    assert version == 2
    assert target_repo.fetch_target("tgt_test")["description"] == "updated"


def test_target_version_conflict_is_reported_not_overwritten(sqlite_db):
    target_repo.upsert_target(_target_payload())

    first = target_repo.upsert_target(
        _target_payload(description="first writer", updated_at=1_700_000_100.0),
        expected_version=1,
    )
    second = target_repo.upsert_target(
        _target_payload(description="second writer", updated_at=1_700_000_200.0),
        expected_version=1,
    )

    assert first is True
    assert second is False
    assert target_repo.fetch_target("tgt_test")["description"] == "first writer"


def test_target_store_mirrors_create_update_delete(tmp_path, monkeypatch, sqlite_db):
    project = tmp_path / "trip"
    project.mkdir()
    monkeypatch.setattr(config, "TARGET_BROWSE_ROOTS", (tmp_path.resolve(),))
    store = TargetStore(tmp_path / "targets.json")

    created = store.create({"name": "trip", "root": str(project)})
    assert target_repo.fetch_target(created.id)["root"] == str(project.resolve())

    store.update(created.id, {"description": "checked in"})
    assert target_repo.fetch_target(created.id)["description"] == "checked in"

    store.delete(created.id)
    assert target_repo.fetch_target(created.id) is None


def test_task_store_mirrors_dependencies(tmp_path, monkeypatch, sqlite_db):
    monkeypatch.setattr(tasks_module, "TASKS_DIR", tmp_path)

    task = Task(
        id="task_1",
        subject="deploy trip",
        description="",
        status="pending",
        owner=None,
        blockedBy=["task_0"],
    )
    save_task(task)
    assert task_repo.fetch_task("task_1")["blockedBy"] == ["task_0"]

    task.blockedBy = ["task_2", "task_0"]
    task.status = "in_progress"
    task.owner = "agent"
    save_task(task)

    stored = task_repo.fetch_task("task_1")
    assert stored["blockedBy"] == ["task_2", "task_0"]
    assert stored["status"] == "in_progress"
    assert stored["owner"] == "agent"
    assert task_repo.count_task_dependencies() == 2

    delete_task("task_1")
    assert task_repo.fetch_task("task_1") is None
    assert task_repo.count_task_dependencies() == 0


def test_memory_store_mirrors_full_list(tmp_path, monkeypatch, sqlite_db):
    monkeypatch.setattr(memory_store_module, "MEMORY_DIR", tmp_path)
    system = MemorySystem()

    system.add("deploy target uses systemd unit trip.service", scope="global")
    system.add("cpu alert threshold is eighty percent", scope="global")
    assert memory_repo.count_memories() == 2

    target = next(
        memory
        for memory in memory_repo.fetch_memories(scope="global")
        if "systemd" in memory["content"]
    )
    system.archive(target["id"])

    stored = memory_repo.fetch_memory(target["id"])
    assert stored["status"] == "archived"
    assert stored["version"] >= 2
    assert memory_repo.count_memories() == 2


def test_json_backend_does_not_touch_postgres(tmp_path, monkeypatch, sqlite_db):
    monkeypatch.setattr(config, "PERSISTENCE_BACKEND", "json")
    monkeypatch.setattr(memory_store_module, "MEMORY_DIR", tmp_path / "memory")
    monkeypatch.setattr(tasks_module, "TASKS_DIR", tmp_path / "tasks")
    store = TargetStore(tmp_path / "targets.json")

    store_path = tmp_path / "projects"
    store_path.mkdir()
    monkeypatch.setattr(config, "TARGET_BROWSE_ROOTS", (tmp_path.resolve(),))
    store.create({"name": "trip", "root": str(store_path)})
    save_task(Task(
        id="task_1",
        subject="deploy",
        description="",
        status="pending",
        owner=None,
        blockedBy=[],
    ))
    MemorySystem().add("json backend keeps mirroring disabled")

    monkeypatch.setattr(config, "PERSISTENCE_BACKEND", "dual")
    assert target_repo.count_targets() == 0
    assert task_repo.count_tasks() == 0
    assert memory_repo.count_memories() == 0


def test_writer_isolates_repository_failures(monkeypatch, sqlite_db):
    def explode(*args, **kwargs):
        raise RuntimeError("database exploded")

    monkeypatch.setattr("agent.persistence.repositories.targets.upsert_target", explode)

    assert writer.persist_target(_target_payload()) is False


def test_writer_counts_calls_failures_and_skips(monkeypatch, sqlite_db):
    """Mirror failures are swallowed, so they must at least be counted."""
    from agent.persistence import writer as writer_module

    writer_module.reset_mirror_stats()

    assert writer.persist_target(_target_payload()) is True
    stats = writer.mirror_stats()
    assert stats["totals"] == {
        "calls": 1,
        "failures": 0,
        "skipped": 0,
        "deferred": 0,
    }
    assert stats["by_writer"]["persist_target"]["calls"] == 1

    # A record the repository refuses counts as skipped, not as a failure.
    assert writer.persist_target({"name": "no id"}) is False
    stats = writer.mirror_stats()
    assert stats["totals"] == {
        "calls": 2,
        "failures": 0,
        "skipped": 1,
        "deferred": 0,
    }

    def explode(*args, **kwargs):
        raise RuntimeError("database exploded")

    monkeypatch.setattr(
        "agent.persistence.repositories.targets.upsert_target",
        explode,
    )
    assert writer.persist_target(_target_payload("tgt_boom")) is False
    stats = writer.mirror_stats()
    assert stats["totals"] == {
        "calls": 2,
        "failures": 1,
        "skipped": 1,
        "deferred": 0,
    }
    assert stats["enabled"] is True

    writer_module.reset_mirror_stats()
    assert writer.mirror_stats()["by_writer"] == {}


def test_writer_counts_nothing_when_the_mirror_is_off(monkeypatch, sqlite_db):
    from agent.persistence import writer as writer_module

    monkeypatch.setattr(config, "PERSISTENCE_BACKEND", "json")
    writer_module.reset_mirror_stats()

    assert writer.persist_target(_target_payload()) is False
    assert writer.persist_memories([]) == 0
    assert writer.claim_due_cron_jobs(["cron_x"], minute_epoch=0.0) is None
    assert writer.mirror_stats()["totals"] == {
        "calls": 0,
        "failures": 0,
        "skipped": 0,
        "deferred": 0,
    }


def test_mirror_stops_hammering_a_dead_database(monkeypatch, sqlite_db):
    """One failure opens a cooldown so later writes do not pay the timeout."""
    from agent.persistence import database as database_module
    from agent.persistence import writer as writer_module

    writer_module.reset_mirror_stats()
    monkeypatch.setattr(config, "DB_FAILURE_COOLDOWN_SECONDS", 60)
    attempts = []

    def explode():
        attempts.append(1)
        raise RuntimeError("database is down")

    real_get_engine = database_module.get_engine
    monkeypatch.setattr(database_module, "get_engine", explode)

    assert writer.persist_target(_target_payload("tgt_first")) is False
    assert writer.persist_target(_target_payload("tgt_second")) is False
    assert writer.persist_target(_target_payload("tgt_third")) is False

    stats = writer.mirror_stats()
    assert stats["totals"]["failures"] == 1
    assert stats["totals"]["deferred"] == 2
    assert stats["circuit_open"] is True
    assert len(attempts) == 1

    # A successful write closes the circuit again.
    monkeypatch.setattr(database_module, "get_engine", real_get_engine)
    writer_module.reset_mirror_stats()
    assert writer.persist_target(_target_payload("tgt_ok")) is True
    assert writer.mirror_stats()["circuit_open"] is False


def test_engine_sets_a_connect_timeout(monkeypatch):
    """A dead database must fail in seconds, not after the OS TCP timeout.

    Measured before the fix: one mirror write took 130s when PostgreSQL was
    stopped, which stalled the API request that triggered it.
    """
    import sqlalchemy

    from agent.persistence import database as database_module

    captured: dict = {}
    real_create_engine = sqlalchemy.create_engine

    def spy(url, **kwargs):
        captured.update(kwargs)
        return real_create_engine(url, **kwargs)

    monkeypatch.setattr(sqlalchemy, "create_engine", spy)
    monkeypatch.setattr(config, "PERSISTENCE_BACKEND", "dual")
    monkeypatch.setattr(
        config,
        "DATABASE_URL",
        "postgresql+psycopg://u:p@127.0.0.1:5432/db",
    )
    monkeypatch.setattr(config, "DB_CONNECT_TIMEOUT", 5)
    database_module.dispose_engine()
    try:
        database_module.get_engine()
    finally:
        database_module.dispose_engine()

    assert captured["connect_args"] == {"connect_timeout": 5}
    assert captured["pool_timeout"] == 5


def test_import_script_migrators_are_idempotent(tmp_path, monkeypatch, sqlite_db):
    from scripts import migrate_store_to_postgres as migrate

    monkeypatch.setattr(target_store_module, "TARGETS_PATH", tmp_path / "targets.json")
    monkeypatch.setattr(tasks_module, "TASKS_DIR", tmp_path / "tasks")
    monkeypatch.setattr(memory_store_module, "MEMORY_DIR", tmp_path / "memory")

    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(config, "TARGET_BROWSE_ROOTS", (tmp_path.resolve(),))
    TargetStore().create({"name": "trip", "root": str(projects)})
    save_task(Task(
        id="task_1",
        subject="deploy",
        description="",
        status="pending",
        owner=None,
        blockedBy=[],
    ))
    MemorySystem().add("import script keeps memories idempotent")

    first = {
        name: migrate.MIGRATORS[name]()
        for name in ("targets", "tasks", "memories")
    }
    second = {
        name: migrate.MIGRATORS[name]()
        for name in ("targets", "tasks", "memories")
    }

    assert first == second
    assert first["targets"] == {"seen": 1, "written": 1}
    assert first["tasks"] == {"seen": 1, "written": 1}
    assert first["memories"] == {"seen": 1, "written": 1}
    assert target_repo.count_targets() == 1
    assert task_repo.count_tasks() == 1
    assert memory_repo.count_memories() == 1


def test_repository_rejects_unusable_ids(sqlite_db):
    assert target_repo.upsert_target({"name": "no id"}) is False
    assert memory_repo.upsert_memory({"id": "x" * 80, "content": "too long"}) is False
    assert memory_repo.upsert_memories([]) == 0


def test_upsert_statement_compiles_for_postgres():
    """The PG upsert must emit ON CONFLICT with a guarded DO UPDATE."""
    from sqlalchemy.dialects import postgresql, sqlite

    from agent.persistence.models import MemoryEntryRecord, TaskRecord

    for dialect, comparison in (
        (postgresql.dialect(), "IS DISTINCT FROM"),
        (sqlite.dialect(), "IS NOT"),
    ):
        statement = repo_common.build_upsert_statement(
            TaskRecord,
            {
                "id": "task_1",
                "subject": "deploy",
                "description": "",
                "status": "pending",
                "owner": None,
                "run_id": "",
                "source": "task",
                "priority": "medium",
                "result": "",
                "task_metadata": {},
                "created_at": 1.0,
                "updated_at": 2.0,
                "version": 1,
            },
            dialect=dialect.name,
            conflict_columns=["id"],
            update_columns=task_repo._UPDATE_COLUMNS,
        )
        compiled = str(statement.compile(dialect=dialect))
        assert "ON CONFLICT" in compiled
        assert "DO UPDATE" in compiled
        assert (
            f"tasks.updated_at {comparison} excluded.updated_at" in compiled
        )
        assert "tasks.version + " in compiled
        assert "metadata" in compiled

    statement = repo_common.build_upsert_statement(
        MemoryEntryRecord,
        {
            "id": "mem_1",
            "content": "remember this",
            "tags": ["a"],
            "supersedes": [],
            "version": 1,
        },
        dialect="postgresql",
        conflict_columns=["id"],
        update_columns=memory_repo._UPDATE_COLUMNS,
    )
    compiled = str(statement.compile(dialect=postgresql.dialect()))
    assert "DO UPDATE" in compiled


def test_models_compile_for_postgres():
    """Every model must produce valid DDL for the PostgreSQL dialect."""
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateIndex, CreateTable

    dialect = postgresql.dialect()
    for table in Base.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(dialect=dialect))
        assert "CREATE TABLE" in ddl
        for index in table.indexes:
            assert "CREATE INDEX" in str(CreateIndex(index).compile(dialect=dialect))


def test_memory_mirror_batches_rows_into_one_statement(sqlite_db):
    """A full-list mirror must not cost one round trip per record."""
    from sqlalchemy import event

    executed = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        executed.append((statement, executemany))

    event.listen(sqlite_db, "before_cursor_execute", _record)
    try:
        records = [
            {
                "id": f"mem_batch_{index}",
                "content": f"batched memory {index}",
                "status": "active",
                "tags": [],
                "supersedes": [],
                "created_at": 1_700_000_000.0,
                "updated_at": 1_700_000_000.0 + index,
            }
            for index in range(3)
        ]
        assert memory_repo.upsert_memories(records) == 3
    finally:
        event.remove(sqlite_db, "before_cursor_execute", _record)

    inserts = [
        (statement, executemany)
        for statement, executemany in executed
        if "INSERT INTO memories" in statement
    ]
    assert len(inserts) == 1
    assert inserts[0][1] is True
    assert memory_repo.count_memories() == 3


def test_batched_upsert_updates_each_row_with_its_own_values(sqlite_db):
    """A batched conflict update must not reuse the first row's payload."""
    first = [
        {
            "id": f"mem_batch_{index}",
            "content": f"batched memory {index}",
            "content_hash": f"{index}" * 8,
            "importance": index + 1,
            "status": "active",
            "tags": [],
            "supersedes": [],
            "created_at": 1_700_000_000.0,
            "updated_at": 1_700_000_000.0,
        }
        for index in range(3)
    ]
    assert memory_repo.upsert_memories(first) == 3

    changed = [
        {
            **record,
            "content_hash": f"changed-{index}",
            "importance": 5,
            "updated_at": 1_700_000_100.0 + index,
        }
        for index, record in enumerate(first)
    ]
    assert memory_repo.upsert_memories(changed) == 3

    for index, record in enumerate(changed):
        stored = memory_repo.fetch_memory(record["id"])
        assert stored["content_hash"] == f"changed-{index}", record["id"]
        assert stored["importance"] == 5


def test_upsert_set_clause_uses_excluded_not_literals():
    """Guard the batch path at the SQL level, independent of the dialect."""
    from sqlalchemy.dialects import postgresql

    from agent.persistence.models import MemoryEntryRecord

    statement = repo_common.build_upsert_statement(
        MemoryEntryRecord,
        {
            "id": "mem_1",
            "content": "first",
            "content_hash": "deadbeef",
            "importance": 3,
            "tags": [],
            "supersedes": [],
            "version": 1,
        },
        dialect="postgresql",
        conflict_columns=["id"],
        update_columns=memory_repo._UPDATE_COLUMNS,
    )
    compiled = str(statement.compile(dialect=postgresql.dialect()))

    assert "content_hash = excluded.content_hash" in compiled
    assert "importance = excluded.importance" in compiled
    assert "deadbeef" not in compiled


def test_memory_access_count_reaches_the_mirror(tmp_path, monkeypatch, sqlite_db):
    """Access counters change without touching ``updated_at``.

    The mirror used to skip any row whose ``updated_at`` was unchanged, so a
    memory that had been used kept its old ``access_count`` in PostgreSQL
    while the local file moved on. Found by the JSON-vs-PostgreSQL check
    after a normal chat session.
    """
    monkeypatch.setattr(memory_store_module, "MEMORY_DIR", tmp_path)
    system = MemorySystem()
    record = system.add("deploy uses systemd", scope="global")
    assert memory_repo.fetch_memory(record["id"])["access_count"] == 0

    system._access_deltas[record["id"]] = 3
    system._access_last_accessed[record["id"]] = 1_700_000_000.0
    assert system.flush_access_stats(force=True) == 1

    stored = memory_repo.fetch_memory(record["id"])
    assert stored["access_count"] == 3
    assert stored["last_accessed_at"] == 1_700_000_000.0
    assert stored["version"] >= 2


def test_unchanged_row_is_not_rewritten(sqlite_db):
    """Replaying identical content must not bump the revision counter."""
    payload = _target_payload()
    assert target_repo.upsert_target(payload) is True
    assert target_repo.upsert_target(payload) is True

    with database.session_scope() as session:
        version = session.execute(
            sqlalchemy.text("SELECT version FROM targets WHERE id = 'tgt_test'")
        ).scalar()
    assert version == 1
