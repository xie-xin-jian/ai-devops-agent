"""Run checkpoint persistence and resume tests."""

import threading
from types import SimpleNamespace

from fastapi.testclient import TestClient

from agent import comprehensive
from agent.action_router import get_action
from agent.pending_actions import PendingActionStore
from agent.rbac import system_admin_principal
from agent.run_checkpoint import (
    PHASE_COMPLETED,
    STATUS_COMPLETED,
    STATUS_INTERRUPTED,
    RunCheckpoint,
    RunCheckpointStore,
    repair_pending_tool_results,
)


def test_repair_pending_tool_results_does_not_reexecute_tools():
    messages = [
        {"role": "user", "content": "run tools"},
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "call_1",
                    "name": "read_file",
                    "input": {"path": "a.txt"},
                },
                {
                    "type": "tool_use",
                    "id": "call_2",
                    "name": "glob",
                    "input": {"pattern": "*.txt"},
                },
            ],
        },
    ]

    repaired, repaired_ids = repair_pending_tool_results(messages)

    assert repaired_ids == ["call_1", "call_2"]
    results = repaired[-1]["content"]
    assert [item["tool_use_id"] for item in results] == [
        "call_1",
        "call_2",
    ]
    assert all("interrupted" in item["content"] for item in results)


def test_run_checkpoint_store_lifecycle(tmp_path):
    store = RunCheckpointStore(tmp_path)
    checkpoint = RunCheckpoint(
        run_id="run-1",
        session_id="session-1",
        owner_id="alice",
        status=STATUS_INTERRUPTED,
        messages=[{"role": "user", "content": "hello"}],
    )

    store.save(checkpoint)

    loaded = store.get("run-1")
    assert loaded.status == STATUS_INTERRUPTED
    assert loaded.messages == [{"role": "user", "content": "hello"}]
    assert store.list(owner_id="alice")[0].run_id == "run-1"


def _checkpoint_agent(tmp_path, monkeypatch):
    agent = object.__new__(comprehensive.ComprehensiveAgent)
    agent.client = object()
    agent.model = "test-model"
    agent.recovery = SimpleNamespace(
        current_model="test-model",
        current_max_tokens=8000,
        has_escalated=False,
        recovery_count=0,
        consecutive_529=0,
    )
    agent.messages = []
    agent.session_id = "session-run"
    agent.health = None
    agent.principal = system_admin_principal()
    agent.audit_enabled = False
    agent.current_run_id = ""
    agent.current_action = get_action("general.chat")
    agent._last_user_query = ""
    agent._pending_compaction = False
    agent._pending_action_notifications = []
    agent._run_pending_action_ids = []
    agent.pending_action_store = PendingActionStore(
        tmp_path / "pending-actions.json"
    )
    agent.run_checkpoint_store = RunCheckpointStore(
        tmp_path / "runs"
    )
    agent.sandbox_manager = None
    agent.sandbox_session = None
    agent.tools = []
    agent.handlers = {}

    monkeypatch.setattr(comprehensive, "trigger_hooks", lambda *args: None)
    monkeypatch.setattr(comprehensive, "collect_background_results", lambda: [])
    monkeypatch.setattr(agent, "_compact_if_needed", lambda messages: messages)
    return agent


def test_normal_run_persists_completed_checkpoint(tmp_path, monkeypatch):
    agent = _checkpoint_agent(tmp_path, monkeypatch)
    monkeypatch.setattr(
        agent,
        "_call_api",
        lambda messages: SimpleNamespace(
            content=[SimpleNamespace(type="text", text="done")]
        ),
    )

    events = list(agent.run_stream("hello"))

    assert events[-1]["type"] == "done"
    checkpoint = agent.run_checkpoint_store.get(agent.current_run_id)
    assert checkpoint.status == STATUS_COMPLETED
    assert checkpoint.phase == PHASE_COMPLETED
    assert checkpoint.messages[-1]["content"][0]["text"] == "done"


def test_interrupted_checkpoint_can_resume_to_completion(
    tmp_path,
    monkeypatch,
):
    agent = _checkpoint_agent(tmp_path, monkeypatch)
    checkpoint = RunCheckpoint(
        run_id="run-interrupted",
        session_id="session-run",
        owner_id=agent.principal.id,
        status=STATUS_INTERRUPTED,
        action_code="file.read",
        user_message="read a.txt",
        messages=[
            {"role": "user", "content": "read a.txt"},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call_read",
                        "name": "read_file",
                        "input": {"path": "a.txt"},
                    },
                ],
            },
        ],
    )
    agent.run_checkpoint_store.save(checkpoint)
    monkeypatch.setattr(
        agent,
        "_call_api",
        lambda messages: SimpleNamespace(
            content=[SimpleNamespace(type="text", text="resumed")]
        ),
    )

    events = list(agent.resume_stream(checkpoint))

    assert events[-1]["type"] == "done"
    loaded = agent.run_checkpoint_store.get("run-interrupted")
    assert loaded.status == STATUS_COMPLETED
    result_message = next(
        message for message in loaded.messages
        if message["role"] == "user"
        and isinstance(message["content"], list)
        and any(
            block.get("type") == "tool_result"
            for block in message["content"]
        )
    )
    assert result_message["content"][0]["tool_use_id"] == "call_read"
    assert "interrupted" in result_message["content"][0]["content"]


def test_run_api_lists_and_resumes_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "agent.run_checkpoint.RUNS_DIR",
        tmp_path,
    )
    store = RunCheckpointStore(tmp_path)
    checkpoint = RunCheckpoint(
        run_id="run-api",
        session_id="session-api",
        owner_id="system",
        status=STATUS_INTERRUPTED,
        action_code="general.chat",
        messages=[{"role": "user", "content": "hello"}],
    )
    store.save(checkpoint)

    class FakeAgent:
        def resume_stream(self, loaded, cancel_event):
            yield {"type": "done", "text": "resumed", "total_turns": 1}

    def fake_session(session_id, principal):
        return session_id, {
            "agent": FakeAgent(),
            "run_lock": threading.Lock(),
            "cancel_event": threading.Event(),
        }

    from api import main as api_main
    monkeypatch.setattr(api_main, "get_or_create_session", fake_session)

    client = TestClient(api_main.app)
    listed = client.get("/api/runs/")
    resumed = client.post("/api/runs/run-api/resume/stream")

    assert listed.status_code == 200
    assert listed.json()["runs"][0]["run_id"] == "run-api"
    assert resumed.status_code == 200
    assert '"type": "done"' in resumed.text
