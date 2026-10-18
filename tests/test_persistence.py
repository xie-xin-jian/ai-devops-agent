"""Persistence mode and dual-write tests."""

from types import SimpleNamespace

import agent.platform.config as config
from agent.core import pipeline
from agent.observability import audit
from agent.persistence import writer


def test_tests_do_not_inherit_the_local_env():
    """A developer's .env must not turn the suite into a dual-write run.

    ``agent.platform.config`` loads ``.env`` with ``override=True``; without
    the isolation fixture every test that writes a target or a task would
    mirror it into the real database.
    """
    assert config.PERSISTENCE_BACKEND == "json"
    assert config.DATABASE_URL == ""
    assert config.PERSISTENCE_READ == "json"


def test_json_mode_keeps_json_only(tmp_path, monkeypatch):
    events_path = tmp_path / "events.jsonl"
    monkeypatch.setattr(config, "PERSISTENCE_BACKEND", "json")
    monkeypatch.setattr(audit, "AUDIT_EVENTS_PATH", events_path)
    called = []
    monkeypatch.setattr(
        writer,
        "persist_audit_event",
        lambda event: called.append(event) or True,
    )

    event = audit.record_event("test.event", "json mode")

    assert event is not None
    assert events_path.exists()
    assert called == []


def test_dual_mode_writes_json_and_postgres(tmp_path, monkeypatch):
    events_path = tmp_path / "events.jsonl"
    monkeypatch.setattr(config, "PERSISTENCE_BACKEND", "dual")
    monkeypatch.setattr(audit, "AUDIT_EVENTS_PATH", events_path)
    called = []
    monkeypatch.setattr(
        writer,
        "persist_audit_event",
        lambda event: called.append(event) or True,
    )

    event = audit.record_event(
        "test.event",
        "dual mode",
        session_id="session-1",
    )

    assert event is not None
    assert events_path.exists()
    assert called[0].id == event.id


def test_postgres_mode_requires_pg_write(tmp_path, monkeypatch):
    events_path = tmp_path / "events.jsonl"
    monkeypatch.setattr(config, "PERSISTENCE_BACKEND", "postgres")
    monkeypatch.setattr(audit, "AUDIT_EVENTS_PATH", events_path)
    monkeypatch.setattr(writer, "persist_audit_event", lambda event: False)

    event = audit.record_event("test.event", "pg mode")

    assert event is None
    assert not events_path.exists()


def test_usage_dual_write_receives_per_call_cost(monkeypatch):
    monkeypatch.setattr(config, "PERSISTENCE_BACKEND", "dual")
    captured = []
    monkeypatch.setattr(
        pipeline,
        "persist_run_usage",
        lambda **kwargs: captured.append(kwargs) or True,
    )
    agent = object.__new__(pipeline.AgentPipelineMixin)
    agent.current_run_id = "run-1"
    agent.session_id = "session-1"
    agent._current_turn = 2
    agent.recovery = SimpleNamespace(current_model="test-model")
    response = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=1000,
            output_tokens=500,
            cache_read_input_tokens=100,
            cache_creation_input_tokens=50,
        )
    )

    agent._record_usage(response)

    assert captured[0]["run_id"] == "run-1"
    assert captured[0]["session_id"] == "session-1"
    assert captured[0]["turn"] == 2
    assert captured[0]["input_tokens"] == 1000
    assert captured[0]["output_tokens"] == 500
    assert captured[0]["cache_write_tokens"] == 50
    assert captured[0]["estimated_cost_cny"] > 0


def test_persistence_status_reports_backend(monkeypatch):
    monkeypatch.setattr(config, "PERSISTENCE_BACKEND", "dual")
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql+psycopg://db")

    status = writer.persistence_status()

    assert status["backend"] == "dual"
    assert status["database_url_configured"] is True
