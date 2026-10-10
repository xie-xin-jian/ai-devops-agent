"""Session and safe-point run persistence tests."""

from types import SimpleNamespace

from agent.sessions.state_store import (
    RUN_STATUS_INTERRUPTED,
    RUN_STATUS_RUNNING,
    RecoveryStore,
    deserialize_messages,
    serialize_messages,
)
from agent.core import comprehensive
from agent.core import pipeline
from agent.platform.identity import system_admin_principal


def test_serialize_messages_round_trip_tool_blocks():
    messages = [
        {"role": "user", "content": "check disk"},
        {
            "role": "assistant",
            "content": [
                SimpleNamespace(type="text", text="Checking."),
                SimpleNamespace(
                    type="tool_use",
                    id="call_1",
                    name="disk_usage",
                    input={},
                ),
            ],
        },
        {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": "call_1",
                "content": "disk ok",
            }],
        },
    ]

    restored = deserialize_messages(serialize_messages(messages))

    assert restored[0] == {
        "role": "user",
        "content": "check disk",
    }
    assert restored[1]["content"] == [
        {"type": "text", "text": "Checking."},
        {
            "type": "tool_use",
            "id": "call_1",
            "name": "disk_usage",
            "input": {},
        },
    ]
    assert restored[2]["content"][0]["tool_use_id"] == "call_1"


def test_session_state_lifecycle(tmp_path):
    store = RecoveryStore(
        sessions_dir=tmp_path / ".sessions",
        runs_dir=tmp_path / ".runs",
    )

    store.save_session(
        "session-1",
        owner_id="alice",
        messages=[{"role": "user", "content": "hello"}],
    )
    restored = store.get_session("session-1")

    assert restored["owner_id"] == "alice"
    assert restored["messages"][0]["content"] == "hello"
    assert store.list_sessions(owner_id="alice")[0]["session_id"] == "session-1"

    store.reset_session("session-1")
    assert store.get_session("session-1") is None


def test_interrupt_stale_runs_preserves_safe_point(tmp_path):
    store = RecoveryStore(
        sessions_dir=tmp_path / ".sessions",
        runs_dir=tmp_path / ".runs",
    )
    store.create_run(
        "run-safe",
        session_id="session-1",
        owner_id="alice",
        user_message="check disk",
        messages=[{"role": "user", "content": "check disk"}],
    )
    store.save_run(
        "run-unsafe",
        session_id="session-1",
        owner_id="alice",
        source="chat",
        status=RUN_STATUS_RUNNING,
        phase="executing_tool",
        user_message="restart nginx",
        messages=[{"role": "user", "content": "restart nginx"}],
        safe_to_resume=False,
        active_tool="bash",
    )
    store.save_run(
        "run-legacy",
        session_id="session-1",
        owner_id="alice",
        source="chat",
        status="waiting_approval",
        phase="waiting_approval",
        user_message="legacy run",
        messages=[{"role": "user", "content": "legacy run"}],
        safe_to_resume=False,
    )

    interrupted = store.interrupt_stale_runs("process restarted")

    assert {item["run_id"] for item in interrupted} == {
        "run-safe",
        "run-unsafe",
        "run-legacy",
    }
    safe = store.get_run("run-safe")
    unsafe = store.get_run("run-unsafe")
    assert safe["status"] == RUN_STATUS_INTERRUPTED
    assert safe["safe_to_resume"] is True
    assert unsafe["safe_to_resume"] is False
    assert unsafe["active_tool"] == ""
    assert unsafe["interruption_reason"] == "process restarted"


def test_agent_run_persists_session_and_completed_run(
    tmp_path,
    monkeypatch,
):
    store = RecoveryStore(
        sessions_dir=tmp_path / ".sessions",
        runs_dir=tmp_path / ".runs",
    )
    agent = object.__new__(comprehensive.ComprehensiveAgent)
    agent.session_id = "session-1"
    agent.principal = system_admin_principal()
    agent.state_store = store
    agent.audit_enabled = False
    agent.current_run_id = ""
    agent.messages = []
    agent.model = "test-model"
    agent.recovery = SimpleNamespace(current_model="test-model")
    agent._pending_compaction = False
    agent._last_user_query = ""
    agent.sandbox_manager = None
    agent._current_turn = 0

    monkeypatch.setattr(pipeline, "collect_background_results", lambda: [])
    monkeypatch.setattr(agent, "_compact_if_needed", lambda messages: messages)
    monkeypatch.setattr(
        agent,
        "_call_api",
        lambda messages: SimpleNamespace(content=[
            SimpleNamespace(type="text", text="hello back")
        ]),
    )

    events = list(agent.run_stream("hello"))

    assert events[-1]["type"] == "done"
    session = store.get_session("session-1")
    assert session["messages"][0]["content"] == "hello"
    run = store.list_runs()[0]
    assert run["status"] == "completed"
    assert run["safe_to_resume"] is False
