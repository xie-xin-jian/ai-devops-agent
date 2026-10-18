"""Dual-write tests for sessions, messages, runs and run snapshots."""

import pytest
import sqlalchemy
from sqlalchemy.pool import StaticPool

import agent.platform.config as config
from agent.persistence import database
from agent.persistence.models import Base
from agent.persistence.repositories import runs as run_repo
from agent.persistence.repositories import sessions as session_repo
from agent.sessions.state_store import RecoveryStore


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


def _store(tmp_path) -> RecoveryStore:
    return RecoveryStore(
        sessions_dir=tmp_path / "sessions",
        runs_dir=tmp_path / "runs",
    )


def _messages(count: int, *, prefix: str = "message") -> list[dict]:
    return [
        {
            "role": "user" if index % 2 == 0 else "assistant",
            "content": f"{prefix} {index}",
        }
        for index in range(count)
    ]


def test_session_mirror_writes_messages_in_sequence(tmp_path, sqlite_db):
    store = _store(tmp_path)

    store.save_session(
        "session-1",
        owner_id="alice",
        messages=_messages(3),
        target_id="tgt_1",
        title="disk check",
    )

    stored = session_repo.fetch_session("session-1")
    assert stored["owner_id"] == "alice"
    assert stored["target_id"] == "tgt_1"
    assert stored["title"] == "disk check"
    assert stored["message_count"] == 3
    assert session_repo.count_messages("session-1") == 3
    assert [item["content"] for item in stored["messages"]] == [
        "message 0",
        "message 1",
        "message 2",
    ]
    assert [item["role"] for item in stored["messages"]] == [
        "user",
        "assistant",
        "user",
    ]


def test_message_rewrite_drops_stale_rows(tmp_path, sqlite_db):
    """Context compaction replaces history, so the mirror must shrink too."""
    store = _store(tmp_path)
    store.save_session("session-1", owner_id="alice", messages=_messages(5))

    store.save_session(
        "session-1",
        owner_id="alice",
        messages=[
            {"role": "user", "content": "[Compacted] summary of 5 messages"},
        ],
    )

    assert session_repo.count_messages("session-1") == 1
    stored = session_repo.fetch_session("session-1")
    assert stored["message_count"] == 1
    assert stored["messages"][0]["content"].startswith("[Compacted]")


def test_unchanged_session_save_does_not_bump_version(tmp_path, sqlite_db):
    store = _store(tmp_path)
    messages = _messages(2)
    first = store.save_session("session-1", owner_id="alice", messages=messages)

    # Same content, explicitly replayed with the same timestamps.
    import agent.persistence.repositories.sessions as repo

    repo.upsert_session({**first, "messages": messages})
    repo.upsert_session({**first, "messages": messages})

    with database.session_scope() as session:
        version = session.execute(
            sqlalchemy.text(
                "SELECT version FROM sessions WHERE session_id = 'session-1'"
            )
        ).scalar()
        message_rows = session.execute(
            sqlalchemy.text(
                "SELECT count(*) FROM messages WHERE session_id = 'session-1'"
            )
        ).scalar()

    assert version == 1
    assert message_rows == 2


def test_session_ttl_is_recorded(tmp_path, sqlite_db):
    store = _store(tmp_path)
    record = store.save_session(
        "session-1",
        owner_id="alice",
        messages=[],
        ttl_seconds=600,
    )

    stored = session_repo.fetch_session("session-1")
    assert stored["expires_at"] == pytest.approx(
        float(record["updated_at"]) + 600
    )


def test_rename_session_keeps_ordering_timestamp(tmp_path, sqlite_db):
    store = _store(tmp_path)
    store.save_session("session-1", owner_id="alice", messages=_messages(1))
    before = session_repo.fetch_session("session-1")

    store.rename_session("session-1", "新名字")

    after = session_repo.fetch_session("session-1")
    assert after["title"] == "新名字"
    assert after["updated_at"] == before["updated_at"]


def test_reset_session_mirrors_delete(tmp_path, sqlite_db):
    store = _store(tmp_path)
    store.save_session("session-1", owner_id="alice", messages=_messages(2))

    store.reset_session("session-1")

    assert session_repo.fetch_session("session-1") is None
    assert session_repo.count_messages("session-1") == 0


def test_run_mirror_writes_snapshot(tmp_path, sqlite_db):
    store = _store(tmp_path)
    store.create_run(
        "run-1",
        session_id="session-1",
        owner_id="alice",
        user_message="check disk",
        messages=_messages(2),
    )

    stored = run_repo.fetch_run("run-1")
    assert stored["session_id"] == "session-1"
    assert stored["status"] == "running"
    assert stored["phase"] == "model"
    assert stored["safe_to_resume"] is True
    assert stored["message_count"] == 2
    assert [item["content"] for item in stored["messages"]] == [
        "message 0",
        "message 1",
    ]
    assert run_repo.count_run_snapshots() == 1


def test_run_snapshot_is_skipped_when_messages_unchanged(tmp_path, sqlite_db):
    store = _store(tmp_path)
    store.create_run(
        "run-1",
        session_id="session-1",
        owner_id="alice",
        user_message="check disk",
        messages=_messages(2),
    )
    created_at = run_repo.fetch_run("run-1")["created_at"]

    # Only the phase changes; the snapshot must keep its original timestamp.
    store.save_run(
        "run-1",
        session_id="session-1",
        owner_id="alice",
        source="chat",
        status="running",
        phase="executing_tool",
        user_message="check disk",
        messages=_messages(2),
        safe_to_resume=False,
        active_tool="bash",
    )

    stored = run_repo.fetch_run("run-1")
    assert stored["phase"] == "executing_tool"
    assert stored["active_tool"] == "bash"
    assert stored["safe_to_resume"] is False

    with database.session_scope() as session:
        snapshot_created_at = session.execute(
            sqlalchemy.text(
                "SELECT created_at FROM run_snapshots WHERE run_id = 'run-1'"
            )
        ).scalar()
    assert float(snapshot_created_at) == float(created_at)


def test_interrupt_stale_runs_only_touches_non_terminal(tmp_path, sqlite_db):
    store = _store(tmp_path)
    store.create_run(
        "run-running",
        session_id="session-1",
        owner_id="alice",
        user_message="a",
        messages=_messages(1),
    )
    store.create_run(
        "run-done",
        session_id="session-1",
        owner_id="alice",
        user_message="b",
        messages=_messages(1),
    )
    store.save_run(
        "run-done",
        session_id="session-1",
        owner_id="alice",
        source="chat",
        status="completed",
        phase="done",
        user_message="b",
        messages=_messages(1),
        safe_to_resume=True,
    )

    interrupted = store.interrupt_stale_runs("process restarted")

    assert [item["run_id"] for item in interrupted] == ["run-running"]
    assert run_repo.fetch_run("run-running")["status"] == "interrupted"
    assert run_repo.fetch_run("run-running")["phase"] == "interrupted"
    assert run_repo.fetch_run("run-done")["status"] == "completed"

    # A second recovery pass must not report the same run again.
    assert store.interrupt_stale_runs("process restarted") == []


def test_mark_resumed_mirrors_new_phase(tmp_path, sqlite_db):
    store = _store(tmp_path)
    store.create_run(
        "run-1",
        session_id="session-1",
        owner_id="alice",
        user_message="check disk",
        messages=_messages(1),
    )
    store.interrupt_stale_runs("process restarted")

    store.mark_resumed("run-1")

    stored = run_repo.fetch_run("run-1")
    assert stored["status"] == "running"
    assert stored["phase"] == "resuming"
    assert stored["interruption_reason"] == ""


def test_json_backend_skips_session_mirrors(tmp_path, monkeypatch, sqlite_db):
    monkeypatch.setattr(config, "PERSISTENCE_BACKEND", "json")
    store = _store(tmp_path)
    store.save_session("session-1", owner_id="alice", messages=_messages(2))
    store.create_run(
        "run-1",
        session_id="session-1",
        owner_id="alice",
        user_message="a",
        messages=_messages(1),
    )

    monkeypatch.setattr(config, "PERSISTENCE_BACKEND", "dual")
    assert session_repo.count_sessions() == 0
    assert session_repo.count_messages() == 0
    assert run_repo.count_runs() == 0


def test_consistency_check_reports_drift(tmp_path, monkeypatch, sqlite_db):
    from agent.persistence import consistency

    store = _store(tmp_path)
    monkeypatch.setattr(
        consistency,
        "RecoveryStore",
        lambda: _store(tmp_path),
    )
    store.save_session("session-1", owner_id="alice", messages=_messages(2))

    clean = consistency.compare(*consistency._sessions())
    assert clean["consistent"] is True

    session_repo.delete_session("session-1")
    drifted = consistency.compare(*consistency._sessions())
    assert drifted["consistent"] is False
    assert drifted["missing_in_postgres"] == ["session-1"]


def test_consistency_check_script_requires_mirror(monkeypatch, capsys):
    import sys

    from scripts import check_persistence_consistency as consistency

    monkeypatch.setattr(config, "PERSISTENCE_BACKEND", "json")
    monkeypatch.setattr(sys, "argv", ["check_persistence_consistency.py"])
    assert consistency.main() == 1
    assert "PERSISTENCE_BACKEND must be dual or postgres" in capsys.readouterr().out


def test_import_script_migrates_sessions_and_runs(tmp_path, monkeypatch, sqlite_db):
    from scripts import migrate_store_to_postgres as migrate

    monkeypatch.setattr(
        migrate,
        "RecoveryStore",
        lambda: _store(tmp_path),
    )
    store = _store(tmp_path)
    store.save_session("session-1", owner_id="alice", messages=_messages(2))
    store.create_run(
        "run-1",
        session_id="session-1",
        owner_id="alice",
        user_message="check disk",
        messages=_messages(2),
    )

    sessions = migrate.MIGRATORS["sessions"]()
    runs = migrate.MIGRATORS["runs"]()

    assert sessions == {"seen": 1, "written": 1}
    assert runs == {"seen": 1, "written": 1}
    assert session_repo.count_messages("session-1") == 2
    assert run_repo.fetch_run("run-1")["message_count"] == 2

    # Re-running the import must be idempotent.
    assert migrate.MIGRATORS["sessions"]() == {"seen": 1, "written": 1}
    assert session_repo.count_sessions() == 1
    assert session_repo.count_messages("session-1") == 2
