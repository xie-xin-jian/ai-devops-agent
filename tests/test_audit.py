"""Audit event storage, redaction, and API tests."""

from fastapi.testclient import TestClient

from agent.observability.audit import (
    AuditStore,
    RESULT_BLOCKED,
    record_event,
)


def test_audit_store_redacts_sensitive_values():
    event = record_event(
        "tool.started",
        "Tool started",
        payload={
            "api_key": "secret-key",
            "authorization": "Bearer abc123",
            "command": "echo ok",
        },
    )

    assert event is not None
    stored = AuditStore().list_events()[0]
    assert stored.payload["api_key"] == "***"
    assert stored.payload["authorization"] == "***"
    assert stored.payload["command"] == "echo ok"


def test_audit_store_filters_and_orders_run_trace():
    store = AuditStore()
    first = record_event(
        "run.started",
        "started",
        session_id="session-1",
        run_id="run-1",
    )
    second = record_event(
        "tool.completed",
        "completed",
        session_id="session-1",
        run_id="run-1",
        result=RESULT_BLOCKED,
    )
    record_event(
        "run.started",
        "other",
        session_id="session-2",
        run_id="run-2",
    )

    assert first is not None
    assert second is not None
    assert len(store.list_events(session_id="session-1")) == 2
    trace = store.get_run_trace("run-1")
    assert [event.event_type for event in trace] == [
        "run.started",
        "tool.completed",
    ]


def test_audit_api_lists_events_and_timeline():
    record_event(
        "run.started",
        "started",
        session_id="session-api",
        run_id="run-api",
    )
    record_event(
        "policy.blocked",
        "blocked",
        session_id="session-api",
        run_id="run-api",
        result=RESULT_BLOCKED,
    )

    from api.main import app
    client = TestClient(app)
    events = client.get("/api/audit/events?session_id=session-api")
    timeline = client.get("/api/audit/timeline?session_id=session-api")
    run = client.get("/api/audit/runs/run-api")

    assert events.status_code == 200
    assert len(events.json()["events"]) == 2
    assert timeline.status_code == 200
    assert timeline.json()["summary"]["blocked"] == 1
    assert run.status_code == 200
    assert len(run.json()["events"]) == 2
