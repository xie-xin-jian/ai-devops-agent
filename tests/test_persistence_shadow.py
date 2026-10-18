"""Shadow-read tests: compare one request's answers without changing them."""

import json

import pytest
import sqlalchemy
from sqlalchemy.pool import StaticPool

import agent.platform.config as config
from agent.observability import audit
from agent.persistence import database
from agent.persistence import consistency
from agent.persistence.models import Base
from agent.persistence.routing import reset_shadow_stats, shadow_status
from agent.persistence.repositories import targets as target_repo
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
    monkeypatch.setattr(config, "PERSISTENCE_SHADOW", False)
    monkeypatch.setattr(config, "PERSISTENCE_SHADOW_COOLDOWN_SECONDS", 0)
    reset_shadow_stats()
    yield engine
    database.dispose_engine()
    monkeypatch.setattr(database, "_engine", None)
    monkeypatch.setattr(database, "_session_factory", None)
    reset_shadow_stats()


def _store(tmp_path) -> RecoveryStore:
    return RecoveryStore(
        sessions_dir=tmp_path / "sessions",
        runs_dir=tmp_path / "runs",
    )


def _switch(monkeypatch, *domains, shadow=True):
    monkeypatch.setattr(config, "PERSISTENCE_READ", "postgres")
    monkeypatch.setattr(config, "PERSISTENCE_READ_DOMAINS", tuple(domains))
    monkeypatch.setattr(config, "PERSISTENCE_SHADOW", shadow)


def _audit_events() -> list[dict]:
    path = audit.AUDIT_EVENTS_PATH
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def test_shadow_disabled_does_not_read_local_store(tmp_path, monkeypatch, sqlite_db):
    store = _store(tmp_path)
    store.save_session("s-1", owner_id="alice", messages=[])
    calls = []
    monkeypatch.setattr(
        type(store),
        "_local_get_session",
        lambda self, session_id: calls.append(session_id) or None,
    )

    _switch(monkeypatch, "sessions", shadow=False)
    assert store.get_session("s-1")["session_id"] == "s-1"

    assert calls == []
    assert shadow_status()["shadow_mismatches"] == 0


def test_shadow_reports_missing_local_record(tmp_path, monkeypatch, sqlite_db):
    store = _store(tmp_path)
    store.save_session("s-1", owner_id="alice", messages=[])
    (tmp_path / "sessions" / "s-1.json").unlink()

    _switch(monkeypatch, "sessions")
    session = store.get_session("s-1")

    # The PostgreSQL answer still wins; shadow only complains.
    assert session["session_id"] == "s-1"
    status = shadow_status()
    assert status["shadow_checks"] == 1
    assert status["shadow_mismatches"] == 1
    assert status["shadow_last_mismatch"] == "sessions:s-1"

    events = [
        event for event in _audit_events()
        if event.get("event_type") == "persistence.shadow.mismatch"
    ]
    assert len(events) == 1
    assert events[0]["severity"] == "high"
    assert events[0]["payload"]["key"] == "s-1"


def test_shadow_agrees_when_both_sides_match(tmp_path, monkeypatch, sqlite_db):
    store = _store(tmp_path)
    store.save_session(
        "s-1",
        owner_id="alice",
        messages=[{"role": "user", "content": "check disk"}],
        title="disk",
    )

    _switch(monkeypatch, "sessions")
    session = store.get_session("s-1")

    assert session["title"] == "disk"
    status = shadow_status()
    assert status["shadow_checks"] == 1
    assert status["shadow_mismatches"] == 0
    assert _audit_events() == []


def test_shadow_ignores_storage_only_differences(tmp_path, monkeypatch, sqlite_db):
    """A legacy JSON run without safe_to_resume must not look like drift."""
    store = _store(tmp_path)
    store.create_run(
        "r-1",
        session_id="s-1",
        owner_id="alice",
        user_message="check disk",
        messages=[{"role": "user", "content": "check disk"}],
    )
    run_path = tmp_path / "runs" / "r-1.json"
    legacy = json.loads(run_path.read_text(encoding="utf-8"))
    legacy.pop("safe_to_resume")
    legacy.pop("active_tool")
    legacy.pop("interruption_reason")
    run_path.write_text(json.dumps(legacy), encoding="utf-8")
    # Mirror the legacy record, which is what the import path does.
    from agent.persistence import writer

    assert writer.persist_run(legacy, force=True) is True

    _switch(monkeypatch, "runs")
    run = store.get_run("r-1")

    assert run["run_id"] == "r-1"
    assert run["safe_to_resume"] is False
    assert shadow_status()["shadow_mismatches"] == 0


def test_shadow_cooldown_limits_audit_events(tmp_path, monkeypatch, sqlite_db):
    monkeypatch.setattr(config, "PERSISTENCE_SHADOW_COOLDOWN_SECONDS", 3600)
    store = _store(tmp_path)
    store.save_session("s-1", owner_id="alice", messages=[])
    (tmp_path / "sessions" / "s-1.json").unlink()

    _switch(monkeypatch, "sessions")
    for _ in range(3):
        store.get_session("s-1")

    assert shadow_status()["shadow_mismatches"] == 3
    events = [
        event for event in _audit_events()
        if event.get("event_type") == "persistence.shadow.mismatch"
    ]
    assert len(events) == 1


def test_shadow_only_for_switched_domains(tmp_path, monkeypatch, sqlite_db):
    store = _store(tmp_path)
    store.save_session("s-1", owner_id="alice", messages=[])
    (tmp_path / "sessions" / "s-1.json").unlink()

    # Shadow is on, but sessions still read from JSON.
    monkeypatch.setattr(config, "PERSISTENCE_READ", "postgres")
    monkeypatch.setattr(config, "PERSISTENCE_READ_DOMAINS", ("targets",))
    monkeypatch.setattr(config, "PERSISTENCE_SHADOW", True)

    assert store.get_session("s-1") is None
    assert shadow_status()["shadow_checks"] == 0


def test_shadow_applies_to_targets(tmp_path, monkeypatch, sqlite_db):
    project = tmp_path / "trip"
    project.mkdir()
    monkeypatch.setattr(config, "TARGET_BROWSE_ROOTS", (tmp_path.resolve(),))
    target_path = tmp_path / "targets.json"
    monkeypatch.setattr("agent.targets.store.TARGETS_PATH", target_path)
    created = TargetStore().create({"name": "trip", "root": str(project)})
    target_path.unlink()

    _switch(monkeypatch, "targets")
    target = TargetStore().get(created.id)

    assert target.name == "trip"
    assert target_repo.fetch_target(created.id)["name"] == "trip"
    assert shadow_status()["shadow_mismatches"] == 1
    assert shadow_status()["shadow_last_mismatch"] == f"targets:{created.id}"


def test_consistency_check_still_reads_json_after_cutover(
    tmp_path,
    monkeypatch,
    sqlite_db,
):
    """The checker must not compare PostgreSQL against itself."""
    store = _store(tmp_path)
    monkeypatch.setattr(consistency, "RecoveryStore", lambda: _store(tmp_path))
    store.save_session("s-1", owner_id="alice", messages=[])

    _switch(monkeypatch, "sessions", shadow=False)
    # Reads are switched, so the store itself would answer from PostgreSQL.
    assert store.get_session("s-1")["session_id"] == "s-1"

    report = consistency.run_consistency_check(domains=["sessions"])
    assert report["consistent"] is True

    with database.session_scope() as session:
        session.execute(
            sqlalchemy.text("DELETE FROM sessions WHERE session_id = 's-1'")
        )

    drifted = consistency.run_consistency_check(domains=["sessions"])
    assert drifted["consistent"] is False
    assert drifted["results"]["sessions"]["missing_in_postgres"] == ["s-1"]
